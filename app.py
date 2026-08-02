#!/usr/bin/env python3
"""
Aplicación web Flask para el gestor de descarga de música.
Interfaz web moderna con soporte completo para videos embebidos de YouTube.
"""

import os
import sys
import re
import json
import shutil
import threading
import time
import webbrowser
import logging
from pathlib import Path
from urllib.parse import quote
from dotenv import load_dotenv

# Configurar TensorFlow para reducir verbosidad de logs
# Solo mostrar errores críticos, una línea por ejecución
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # 0=all, 1=info, 2=warnings, 3=errors only
os.environ['TF_CPP_MIN_VLOG_LEVEL'] = '3'  # Desactivar logs verbosos

# Importar Flask
try:
    from flask import Flask, render_template, request, jsonify, send_file
    from flask_cors import CORS
except ImportError:
    print("❌ Flask no está instalado. Instala con: pip install flask flask-cors")
    exit(1)

def _get_config_dir() -> Path:
    """Directorio donde se guarda el .env. Fijo: junto al .exe si está empaquetado, sino junto a app.py."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


# Cargar variables de entorno antes de resolver la ruta de la BD (siempre desde la misma ubicación)
load_dotenv(_get_config_dir() / '.env')

# Resolver ruta de la base de datos (si falla la por defecto, preguntar al usuario)
from database import MusicDatabase, get_or_choose_db_path
_db_path = get_or_choose_db_path()
if _db_path is None:
    print("❌ No se pudo abrir o crear la base de datos. Se canceló la elección de ubicación.")
    sys.exit(1)

# Importar módulos del proyecto (download_youtube usa DB_PATH del entorno)
from download_youtube import (
    download_audio, get_video_info, extract_metadata_from_title,
    detect_genre_online, get_output_folder, check_file_exists,
    register_song_in_db, add_id3_tags,
    save_rejected_video, is_rejected_video, sanitize_filename,
    check_audio_volume, apply_volume_offset,
    get_liked_videos_from_url, process_imported_mp3,
    redownload_full, get_genre_from_essentia,
    generate_waveform_data,
    SUPPORTED_COOKIE_BROWSERS, get_cookies_browser, get_cookies_file,
    apply_cookies_to_opts, has_cookies_configured
)
from download_quick import download_quick
from query_db import show_statistics, search_songs
import uuid

# Importar clasificador TF para precarga en background
try:
    from genre_classifier_tf import preload_model_async, is_model_ready
    TF_CLASSIFIER_AVAILABLE = True
except ImportError:
    TF_CLASSIFIER_AVAILABLE = False

# Inicializar base de datos (ruta ya resuelta en get_or_choose_db_path)
DB_PATH = os.getenv('DB_PATH', None)
db = MusicDatabase(DB_PATH)
MUSIC_FOLDER = os.getenv('MUSIC_FOLDER', os.path.expanduser('~/Music'))

# Tiempo máximo (segundos) que /api/playlist puede tardar antes de devolver un
# resultado parcial. Evita que la interfaz se quede colgada indefinidamente.
try:
    PLAYLIST_TIMEOUT = int(os.getenv('PLAYLIST_TIMEOUT', '180'))
except (TypeError, ValueError):
    PLAYLIST_TIMEOUT = 180

# Crear aplicación Flask
app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.urandom(24)

# Configurar logging para suprimir logs automáticos de polling de estado
class StatusPollingFilter(logging.Filter):
    """Filtro para suprimir logs de polling de estado de descargas."""
    def filter(self, record):
        # Suprimir logs de Werkzeug para rutas de polling de estado
        # Werkzeug registra en el formato: "GET /api/download/status/xxx HTTP/1.1" 200
        message = str(record.getMessage())
        if '/api/download/status/' in message:
            return False
        # /api/logs se consulta cada segundo desde la consola web: no ensuciar
        # (y además evitaría un bucle de ruido, porque su propio log se capturaría)
        if '/api/logs' in message:
            return False
        return True

# Aplicar filtro al logger de Werkzeug
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.addFilter(StatusPollingFilter())

# ============================================================================
# Captura de la salida del servidor para mostrarla en la consola de la web
# ----------------------------------------------------------------------------
# Todo lo que el backend imprime con print() se duplica en un buffer circular
# que el navegador consulta vía GET /api/logs. Así la consola flotante muestra
# el progreso real del servidor y se distingue "está trabajando" de "colgado".
# ============================================================================
from collections import deque

LOG_CHANNELS = ('download', 'database', 'playlist', 'import', 'testing', 'config', 'server')
_log_buffer = deque(maxlen=4000)
_log_lock = threading.Lock()
_log_seq = 0
_log_ctx = threading.local()


def set_log_channel(channel, request_id=None):
    """Asocia el hilo actual a una pestaña de la consola web (y a una petición)."""
    _log_ctx.channel = channel if channel in LOG_CHANNELS else 'server'
    _log_ctx.rid = request_id


# Línea de acceso de Werkzeug: '... "GET /api/x HTTP/1.1" 200 -'. Es ruido en la
# consola web (el navegador ya sabe qué ha pedido), así que no se guarda.
_ACCESS_LOG_RE = re.compile(r'"(GET|POST|PUT|DELETE|HEAD|OPTIONS|PATCH) .*HTTP/[\d.]+"\s+\d{3}')


def _push_log_line(text):
    """Añade una línea al buffer que consume la consola web."""
    global _log_seq
    text = text.rstrip('\r\n')
    if not text.strip():
        return
    if _ACCESS_LOG_RE.search(text):
        return
    with _log_lock:
        _log_seq += 1
        _log_buffer.append({
            'seq': _log_seq,
            'ts': time.strftime('%H:%M:%S'),
            'channel': getattr(_log_ctx, 'channel', 'server'),
            'rid': getattr(_log_ctx, 'rid', None),
            'text': text[:2000],
        })


class _TeeStream:
    """Escribe en la salida real y, además, en el buffer de la consola web."""

    def __init__(self, stream):
        self._stream = stream
        self._partial = {}

    def write(self, data):
        try:
            if self._stream is not None:
                self._stream.write(data)
        except Exception:
            pass
        try:
            # Acumular por hilo hasta tener líneas completas
            tid = threading.get_ident()
            buf = self._partial.get(tid, '') + str(data)
            parts = buf.split('\n')
            self._partial[tid] = parts.pop()
            for line in parts:
                _push_log_line(line)
        except Exception:
            pass
        return len(data) if data else 0

    def flush(self):
        try:
            if self._stream is not None:
                self._stream.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return bool(self._stream) and self._stream.isatty()
        except Exception:
            return False

    def __getattr__(self, name):
        return getattr(self.__dict__.get('_stream'), name)


if not isinstance(sys.stdout, _TeeStream):
    sys.stdout = _TeeStream(sys.stdout)
if not isinstance(sys.stderr, _TeeStream):
    sys.stderr = _TeeStream(sys.stderr)


# Cada endpoint escribe en la pestaña de la consola web que le corresponde
_LOG_CHANNEL_BY_PATH = (
    ('/api/playlist', 'playlist'),
    ('/api/youtube/search', 'download'),
    ('/api/download', 'download'),
    ('/api/import', 'import'),
    ('/api/songs', 'database'),
    ('/api/database', 'database'),
    ('/api/test', 'testing'),
    ('/api/config', 'config'),
    ('/api/cookies', 'config'),
)


@app.before_request
def _tag_log_channel():
    path = request.path or ''
    # log_id (opcional) lo manda el cliente para poder seguir SOLO esta petición
    rid = request.args.get('log_id') or None
    for prefix, channel in _LOG_CHANNEL_BY_PATH:
        if path.startswith(prefix):
            set_log_channel(channel, rid)
            return
    set_log_channel('server', rid)


@app.route('/api/logs', methods=['GET'])
def get_server_logs():
    """Devuelve las líneas de log del servidor posteriores a `since`.

    Query params:
      since:   último `seq` recibido (omitirlo devuelve las últimas 150 líneas;
               -1 no devuelve líneas, sólo el `last_seq` actual, útil para que
               el cliente marque el punto de partida antes de una operación)
      channel: lista separada por comas de canales a filtrar (ej: playlist,server)
      rid:     devolver sólo las líneas de la petición con ese `log_id` (tiene
               prioridad sobre `channel`; así una carga cancelada no mezcla su
               salida con la nueva)
    """
    since = request.args.get('since', type=int)
    channel = request.args.get('channel')
    rid = request.args.get('rid')

    with _log_lock:
        items = list(_log_buffer)
        last_seq = _log_seq

    if since == -1:
        items = []
    elif since is None:
        items = items[-150:]
    else:
        items = [item for item in items if item['seq'] > since]

    if rid:
        items = [item for item in items if item.get('rid') == rid]
    elif channel:
        wanted = {c.strip() for c in channel.split(',') if c.strip()}
        items = [item for item in items if item['channel'] in wanted]

    # last_seq es global (no filtrado) para que el cliente avance siempre
    return jsonify({'success': True, 'logs': items, 'last_seq': last_seq})

# Manejador de errores global para asegurar respuestas JSON
@app.errorhandler(404)
def not_found(error):
    """Maneja errores 404 devolviendo JSON."""
    return jsonify({'success': False, 'error': 'Ruta no encontrada'}), 404

@app.errorhandler(500)
def internal_error(error):
    """Maneja errores 500 devolviendo JSON."""
    return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Maneja cualquier excepción no capturada devolviendo JSON."""
    import traceback
    traceback.print_exc()
    return jsonify({'success': False, 'error': str(e)}), 500

# Estado global para descargas y tareas
download_status = {}
download_logs = {}
import_status = {}
import_logs = {}
direct_download_tasks = {}
redownload_full_status = {}


def _normalize_file_path_from_db(file_path_raw: str):
    """
    Convierte una ruta guardada en la BD a una ruta válida en el SO actual.
    En Windows, rutas WSL/Linux como /mnt/c/Users/... se convierten a C:\\Users\\...
    """
    if not file_path_raw or not file_path_raw.strip():
        return None
    path_str = file_path_raw.strip()
    if sys.platform == 'win32':
        # WSL: /mnt/c/... -> C:\...
        if path_str.startswith('/mnt/') and len(path_str) > 5:
            drive_letter = path_str[5]  # 'c', 'd', etc.
            rest = path_str[6:].replace('/', os.sep)
            path_str = f'{drive_letter.upper()}:{os.sep}{rest}'
    path_obj = Path(path_str)
    try:
        path_obj = path_obj.resolve()
    except (OSError, RuntimeError):
        pass
    return path_obj


def _fetch_albumart_for_song(song: dict):
    """
    Busca album art para una canción siguiendo esta prioridad:
    1. APIC embebida en el MP3
    2. Thumbnail directo de YouTube (si video_id es ID válido de YT)
    3. iTunes Search API — portada cuadrada 600x600, mayor calidad
    4. Búsqueda en YouTube via yt-dlp (si hay ID en el título, lo usa directamente;
       si no, busca por artista+título)
    Devuelve la URL del thumbnail o None si no se encuentra.
    """
    import urllib.request
    import urllib.parse

    video_id = (song.get('video_id') or '').strip()
    title = (song.get('title') or '').strip()
    artist = (song.get('artist') or '').strip()

    # Título limpio (sin el [video_id] del nombre de archivo)
    clean_title = re.sub(r'\[[A-Za-z0-9_-]{11}\]', '', title).strip(' -–')

    # 1. APIC embebida en el MP3
    file_path_raw = (song.get('file_path') or '').strip()
    if file_path_raw:
        path_obj = _normalize_file_path_from_db(file_path_raw)
        if path_obj and path_obj.exists() and path_obj.is_file():
            try:
                from mutagen.id3 import ID3
                from mutagen.mp3 import MP3 as _MP3
                _audio = _MP3(str(path_obj), ID3=ID3)
                if any(k.startswith('APIC') for k in _audio.keys()):
                    return f'/api/database/song/{video_id}/cover'
            except Exception:
                pass

    # 2. Thumbnail directo de YouTube para IDs válidos (11 caracteres alfanuméricos)
    if re.match(r'^[A-Za-z0-9_-]{11}$', video_id):
        return f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg'

    # 3. iTunes Search API — portadas cuadradas de alta calidad (600x600)
    # Va antes del thumbnail de YouTube para importadas porque el video puede estar borrado
    if artist or clean_title:
        try:
            # Evitar duplicar el artista si el título ya empieza por él ("Yves Larock - Rise Up…")
            search_title = clean_title
            if artist and search_title.lower().startswith(artist.lower()):
                search_title = search_title[len(artist):].lstrip(' \t-–').strip()
            term = f'{artist} {search_title}'.strip() if search_title else artist
            search_url = (
                f'https://itunes.apple.com/search?term={urllib.parse.quote(term)}'
                f'&media=music&limit=5'
            )
            req = urllib.request.Request(search_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                for r in (data.get('results') or []):
                    art = (r.get('artworkUrl100') or '').replace('100x100bb', '600x600bb')
                    if art:
                        return art
        except Exception:
            pass

    # 4. ID de YouTube extraído del título — verificar que la imagen existe antes de devolverla
    yt_id_in_title = re.search(r'\[([A-Za-z0-9_-]{11})\]', title)
    if yt_id_in_title:
        yt_id = yt_id_in_title.group(1)
        for res in ('maxresdefault', 'hqdefault', 'mqdefault'):
            yt_url = f'https://i.ytimg.com/vi/{yt_id}/{res}.jpg'
            try:
                req = urllib.request.Request(yt_url, headers={'User-Agent': 'Mozilla/5.0'})
                req.get_method = lambda: 'HEAD'
                with urllib.request.urlopen(req, timeout=5) as r:
                    if r.status == 200:
                        return yt_url
            except Exception:
                pass

    # 5. Búsqueda en YouTube via yt-dlp (último recurso)
    if artist or clean_title:
        try:
            import yt_dlp as _yt_dlp
            search_query = f'{artist} - {clean_title}' if artist and clean_title else (artist or clean_title)
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'skip_download': True,
                'socket_timeout': 10,
                'ignoreerrors': True,
            }
            apply_cookies_to_opts(ydl_opts)
            with _yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f'ytsearch1:{search_query}', download=False)
                entries = (info or {}).get('entries') or []
                if entries and entries[0]:
                    vid = entries[0].get('id')
                    if vid and re.match(r'^[A-Za-z0-9_-]{11}$', vid):
                        return f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg'
        except Exception:
            pass

    return None


@app.route('/')
def index():
    """Página principal."""
    return render_template('index.html')


@app.route('/api/playlist', methods=['GET'])
def get_playlist():
    """Obtiene la lista de canciones de la playlist."""
    start_time = time.time()
    playlist_url = request.args.get('url', 'https://music.youtube.com/playlist?list=LM')
    limit = int(request.args.get('limit', 20))
    hide_ignored = request.args.get('hide_ignored', 'true').lower() == 'true'
    
    print(f"[{time.strftime('%H:%M:%S')}] 🎵 GET /api/playlist - Iniciando carga de playlist")
    print(f"    URL: {playlist_url}")
    print(f"    Límite: {limit}, Ocultar ignoradas: {hide_ignored}")
    print(f"    Cookies configuradas: {'sí' if has_cookies_configured() else 'NO (la playlist devolverá 0 canciones)'}")
    print(f"    Tiempo máximo de la petición: {PLAYLIST_TIMEOUT}s")

    try:
        videos_data = []
        batch_size = limit * 5  # Tamaño de cada lote a obtener
        start_index = 1  # Índice inicial (1-based)
        max_batches = 10  # Máximo de lotes a intentar (para evitar bucles infinitos)
        batch_count = 0
        skipped_count = 0  # Contador de canciones omitidas
        timed_out = False  # Se agotó PLAYLIST_TIMEOUT antes de completar

        print(f"[{time.strftime('%H:%M:%S')}] 🔄 Procesando playlist en lotes hasta encontrar {limit} videos válidos...")

        # Si hide_ignored está activado, obtener videos en lotes hasta tener suficientes válidos
        # Si no está activado, solo obtener un lote
        while len(videos_data) < limit and batch_count < max_batches:
            if time.time() - start_time > PLAYLIST_TIMEOUT:
                timed_out = True
                print(f"[{time.strftime('%H:%M:%S')}] ⏱️  Tiempo máximo agotado ({PLAYLIST_TIMEOUT}s): devolviendo lo encontrado hasta ahora")
                break

            batch_count += 1
            current_batch_size = batch_size if hide_ignored else limit

            print(f"[{time.strftime('%H:%M:%S')}] 🔍 Lote {batch_count}/{max_batches}: Obteniendo videos desde índice {start_index} (hasta {start_index + current_batch_size - 1})...")
            batch_start = time.time()
            liked_videos = get_liked_videos_from_url(playlist_url, limit=current_batch_size, start_index=start_index)
            batch_elapsed = time.time() - batch_start

            if not liked_videos:
                print(f"    ⚠️  No se obtuvieron más videos de la playlist (lote vacío tras {batch_elapsed:.1f}s)")
                break

            print(f"    ✅ Obtenidos {len(liked_videos)} videos en este lote ({batch_elapsed:.1f}s)")

            # Procesar los videos del lote actual
            for idx, video in enumerate(liked_videos, 1):
                # Si ya tenemos suficientes videos y hide_ignored está activado, parar
                if hide_ignored and len(videos_data) >= limit:
                    print(f"    ✅ Ya se encontraron {limit} videos válidos, deteniendo procesamiento")
                    break

                if time.time() - start_time > PLAYLIST_TIMEOUT:
                    timed_out = True
                    print(f"[{time.strftime('%H:%M:%S')}] ⏱️  Tiempo máximo agotado ({PLAYLIST_TIMEOUT}s) en el video {idx}/{len(liked_videos)} del lote {batch_count}")
                    break

                video_id = video['id']
                url = video['url']
                title = video['title']
                
                # PRIMERO: Verificar si está rechazada o descargada (verificación rápida)
                is_rejected = is_rejected_video(video_id)

                # Buscar en BD por video_id directamente (sin verificar que el archivo exista
                # en disco: la BD es la fuente de verdad para el filtrado de playlist; el check
                # de archivo fallaría con rutas de Windows sincronizadas via OneDrive o si el
                # usuario renombró/movió los archivos).
                existing_song = db.get_song_by_video_id(video_id)
                matched_by = 'video_id' if existing_song else None

                # Si no la encuentra por video_id, intentar por artista+título.
                # Esto permite reconocer canciones importadas manualmente (que se
                # guardan con video_id="imported_<hash>") o redescargadas con otro id.
                if not existing_song:
                    # Usar metadata cacheada si existe; si no, extraerla del título
                    cached_meta = db.get_cached_metadata(video_id) or {}
                    cand_artist = cached_meta.get('artist') or video.get('artist')
                    cand_title = cached_meta.get('title')
                    if not cand_title:
                        try:
                            extracted = extract_metadata_from_title(title, '', None) or {}
                            cand_artist = cand_artist or extracted.get('artist')
                            cand_title = extracted.get('title') or title
                        except Exception:
                            cand_title = title
                    if cand_artist and cand_title:
                        # Buscar en BD sin verificar existencia del archivo en disco
                        found = db.find_song(artist=cand_artist, title=cand_title)
                        existing_song = found[0] if found else None
                        if existing_song:
                            matched_by = f"artista+título: {cand_artist} / {cand_title}"

                if hide_ignored and (is_rejected or existing_song):
                    skipped_count += 1
                    if existing_song:
                        reason = f"ya descargada [{matched_by}]"
                    else:
                        reason = "ignorada"
                    print(f"[{time.strftime('%H:%M:%S')}] ⏭️  [{skipped_count}] Omitida ({reason}): {(title or '')[:70]}")
                    continue

                print(f"[{time.strftime('%H:%M:%S')}]   [{idx}/{len(liked_videos)}] Procesando ({time.time() - start_time:.0f}s transcurridos): {(title or '')[:70]}")

                # Info del video SOLO si ya está en caché. Aquí no se consulta a
                # YouTube: la petición por canción tarda 18-50s (la extracción con
                # cookies falla y sólo responde el reintento sin cookies), así que
                # listar 20 canciones nuevas costaba minutos y parecía un cuelgue.
                # Para pintar la lista basta con el título de la entrada plana y la
                # miniatura estándar de YouTube; la info completa se obtiene al
                # descargar, que es cuando de verdad hace falta.
                video_info = db.get_cached_video_info(video_id)
                if video_info:
                    print(f"      → ✅ Info desde caché")

                # Metadatos: de caché si existen; si no, del título (sin red).
                # No se cachean los extraídos aquí: al no tener la descripción del
                # vídeo son de peor calidad que los que calcula la descarga, y
                # cachearlos empeoraría los tags del MP3.
                metadata = db.get_cached_metadata(video_id)
                if not metadata:
                    try:
                        title_from_info = video_info.get('title', title) if video_info else title
                        description = video_info.get('description', '') if video_info else ''
                        metadata = extract_metadata_from_title(title_from_info, description, video_info)
                    except Exception as e:
                        print(f"      → ⚠️  Error extrayendo metadatos: {e}")
                        metadata = {}

                # Asegurar que metadata nunca sea None
                if metadata is None:
                    metadata = {}

                # Miniatura: de la info cacheada o construida a partir del id
                thumbnail = (video_info or {}).get('thumbnail') or ''
                if not thumbnail and re.match(r'^[A-Za-z0-9_-]{11}$', video_id or ''):
                    thumbnail = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'

                # Obtener género desde caché o detectar
                # (metadata puede traer la clave con valor None: de ahí el `or`)
                genre = db.get_cached_genre(video_id)
                if not genre:
                    genre = (metadata.get('genre') if metadata else None) or 'Sin Clasificar'

                # Artista: metadatos > canal de la entrada plana > desconocido
                artist = (metadata.get('artist') if metadata else None) \
                         or video.get('artist') or 'Desconocido'

                # Obtener información de progreso si está descargando
                is_downloading = video_id in download_status and download_status[video_id].get('status') == 'downloading'
                progress = 0
                if is_downloading:
                    progress = download_status[video_id].get('progress', 0)
                
                videos_data.append({
                    'id': video_id,
                    'title': title,
                    'url': url,
                    'thumbnail': thumbnail,
                    'genre': genre,
                    'artist': artist,
                    'is_rejected': is_rejected,
                    'is_downloaded': existing_song is not None,
                    'is_downloading': is_downloading,
                    'progress': progress
                })
                print(f"      → ✅ Agregada a la lista ({len(videos_data)}/{limit})")
            
            # Si no tenemos suficientes videos válidos y hide_ignored está activado, obtener el siguiente lote
            if hide_ignored and len(videos_data) < limit:
                start_index += len(liked_videos)
                print(f"    📊 Progreso: {len(videos_data)}/{limit} válidos encontrados, {skipped_count} omitidas. Obteniendo siguiente lote...")
            else:
                # Si hide_ignored no está activado o ya tenemos suficientes, no necesitamos más lotes
                break
        
        elapsed = time.time() - start_time
        print(f"[{time.strftime('%H:%M:%S')}] ✅ GET /api/playlist - Completado en {elapsed:.2f}s")
        print(f"    📊 Resultado: {len(videos_data)}/{limit} videos válidos mostrados")
        if skipped_count > 0:
            print(f"    ⏭️  {skipped_count} canciones omitidas (ya descargadas o ignoradas)")
        print(f"    📦 Lotes procesados: {batch_count}")
        if timed_out:
            print(f"    ⚠️  Resultado PARCIAL: se agotó el tiempo máximo ({PLAYLIST_TIMEOUT}s). "
                  f"Sube PLAYLIST_TIMEOUT en el .env o baja el número de canciones.")
        return jsonify({
            'success': True,
            'videos': videos_data,
            'count': len(videos_data),
            'timed_out': timed_out,
            'skipped': skipped_count,
            'batches': batch_count,
            'elapsed': round(elapsed, 2)
        })
    except Exception as e:
        elapsed = time.time() - start_time
        import traceback
        print(f"[{time.strftime('%H:%M:%S')}] ❌ GET /api/playlist - Error después de {elapsed:.2f}s")
        print(f"    Error: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/download', methods=['POST'])
def download_song():
    """Descarga una canción."""
    data = request.json
    video_id = data.get('video_id')
    video_url = data.get('url')
    
    if not video_id or not video_url:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    def download_thread():
        try:
            download_status[video_id] = {'status': 'downloading', 'progress': 0, 'downloaded_bytes': 0, 'total_bytes': 0}
            download_logs[video_id] = []

            def add_log(msg):
                """Añade un mensaje al log de la descarga (lo verá la consola flotante)."""
                download_logs[video_id].append(str(msg))
                try:
                    print(f"[{time.strftime('%H:%M:%S')}] [{video_id[:8]}] {msg}")
                except Exception:
                    pass

            add_log(f"🚀 Iniciando descarga de {video_url}")

            # Estado para evitar spam del callback de progreso (solo logueamos hitos)
            progress_state = {'last_logged_pct': -10}

            # Callback para actualizar el progreso
            def update_progress(d):
                status = d.get('status', '')
                if status == 'downloading':
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    if total and total > 0:
                        # Calcular progreso entre 20% y 80% (la descarga real)
                        download_progress = int((downloaded / total) * 60)  # 0-60% de la descarga
                        progress = 20 + download_progress  # 20% a 80%
                        download_status[video_id].update({
                            'status': 'downloading',
                            'progress': min(progress, 80),
                            'downloaded_bytes': downloaded,
                            'total_bytes': total,
                            'speed': d.get('speed', 0),
                            'eta': d.get('eta', 0)
                        })
                        # Log cada ~25% de la descarga real
                        real_pct = int((downloaded / total) * 100)
                        if real_pct - progress_state['last_logged_pct'] >= 25 or real_pct == 100:
                            progress_state['last_logged_pct'] = real_pct
                            mb_done = downloaded / (1024 * 1024)
                            mb_total = total / (1024 * 1024)
                            speed_mb = (d.get('speed') or 0) / (1024 * 1024)
                            add_log(f"⬇️  Descargando... {real_pct}% ({mb_done:.1f}/{mb_total:.1f} MB) a {speed_mb:.2f} MB/s")
                    else:
                        download_status[video_id].update({
                            'status': 'downloading',
                            'downloaded_bytes': downloaded,
                            'total_bytes': 0
                        })
                elif status == 'finished':
                    download_status[video_id]['progress'] = 80
                    add_log("✅ Descarga del audio finalizada, procesando...")

            # Obtener información del video
            download_status[video_id]['progress'] = 5
            add_log("🔎 Obteniendo información del video...")
            video_info = get_video_info(video_url)
            if not video_info:
                add_log("❌ No se pudo obtener información del video")
                download_status[video_id] = {'status': 'error', 'error': 'No se pudo obtener información del video'}
                return

            title = video_info.get('title', '')
            description = video_info.get('description', '')
            add_log(f"🎬 Título: {title}")

            # Extraer metadatos
            download_status[video_id]['progress'] = 10
            add_log("🏷️  Extrayendo metadatos del título...")
            metadata = extract_metadata_from_title(title, description, video_info)
            if metadata.get('artist'):
                add_log(f"   👤 Artista: {metadata.get('artist')}")
            if metadata.get('title'):
                add_log(f"   🎵 Tema:    {metadata.get('title')}")
            if metadata.get('year'):
                add_log(f"   📅 Año:     {metadata.get('year')}")

            # Detectar género si no está
            if not metadata.get('genre'):
                download_status[video_id]['progress'] = 15
                add_log("🎼 Detectando género online...")
                detected_genre = detect_genre_online(
                    metadata.get('artist'),
                    metadata.get('title', title),
                    video_info=video_info,
                    title=title,
                    description=description
                )
                if detected_genre:
                    metadata['genre'] = detected_genre
                    add_log(f"   ✓ Género detectado: {detected_genre}")
                else:
                    metadata['genre'] = 'Sin Clasificar'
                    add_log("   ⚠️  No se pudo detectar género (Sin Clasificar)")
            else:
                add_log(f"🎼 Género ya definido: {metadata.get('genre')}")

            # Obtener carpeta de salida
            output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))
            add_log(f"📁 Carpeta destino: {output_folder}")

            # Crear nombre de archivo
            if metadata.get('artist'):
                filename = f"{metadata['artist']} - {metadata['title']}"
            else:
                filename = metadata.get('title', title)

            filename = sanitize_filename(filename)
            output_path = output_folder / filename

            # Descargar (el progreso se actualizará automáticamente con el callback)
            download_status[video_id]['progress'] = 20
            add_log(f"⬇️  Descargando audio: {filename}.mp3")
            if download_audio(video_url, str(output_path), metadata, progress_callback=update_progress):
                download_status[video_id]['progress'] = 80
                mp3_file = Path(str(output_path) + '.mp3')
                if not mp3_file.exists():
                    mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
                    if mp3_files:
                        mp3_file = mp3_files[0]

                download_status[video_id]['progress'] = 85

                download_status[video_id]['progress'] = 90
                add_log("🏷️  Añadiendo metadatos ID3...")
                add_id3_tags(str(mp3_file), metadata, video_info)

                download_status[video_id]['progress'] = 95
                add_log("💾 Registrando en base de datos...")
                register_song_in_db(video_id, video_url, mp3_file, metadata, video_info, download_source='playlist')

                add_log(f"✅ Descarga completada: {mp3_file.name}")
                download_status[video_id] = {'status': 'completed', 'progress': 100, 'file': str(mp3_file)}
            else:
                add_log("❌ Error en la descarga del audio")
                download_status[video_id] = {'status': 'error', 'error': 'Error en la descarga'}

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            try:
                download_logs[video_id].append(f"❌ Excepción: {e}")
                download_logs[video_id].append(tb)
            except Exception:
                pass
            download_status[video_id] = {'status': 'error', 'error': str(e), 'error_detail': tb}
    
    threading.Thread(target=download_thread, daemon=True).start()
    return jsonify({'success': True, 'message': 'Descarga iniciada'})


@app.route('/api/download/status/<task_id>', methods=['GET'])
def get_download_status(task_id):
    """Obtiene el estado de una descarga."""
    # Intentar como video_id primero
    status = download_status.get(task_id, {})
    if status:
        status_type = status.get('status', 'unknown')
        progress = status.get('progress', 0)
        
        # Solo loguear cuando hay actividad relevante (no en cada polling)
        # Loguear solo en cambios de estado o progreso significativo
        if status_type in ['downloading', 'completed', 'error']:
            if status_type == 'downloading' and progress > 0:
                # Solo loguear cada 10% de progreso para no saturar
                if progress % 10 == 0 or progress in [5, 20, 50, 80, 90, 95]:
                    print(f"[{time.strftime('%H:%M:%S')}] 📥 Estado descarga {task_id[:8]}...: {status_type} ({progress}%)")
            elif status_type in ['completed', 'error']:
                print(f"[{time.strftime('%H:%M:%S')}] {'✅' if status_type == 'completed' else '❌'} Descarga {task_id[:8]}...: {status_type}")
        
        logs = download_logs.get(task_id, [])
        return jsonify({
            'status': status,
            'logs': logs
        })
    
    # Si no, intentar como task_id de descarga directa
    task_status = direct_download_tasks.get(task_id, {})
    if task_status:
        status_type = task_status.get('status', 'idle')
        if status_type in ['completed', 'error']:
            print(f"[{time.strftime('%H:%M:%S')}] {'✅' if status_type == 'completed' else '❌'} Descarga directa {task_id[:8]}...: {status_type}")
        
        return jsonify({
            'status': task_status.get('status', 'idle'),
            'error': task_status.get('error'),
            'error_detail': task_status.get('error_detail'),
            'file': task_status.get('file')
        })
    
    # No loguear cuando el estado es 'idle' (polling normal)
    return jsonify({'status': 'idle'})


@app.route('/api/reject', methods=['POST'])
def reject_song():
    """Marca una canción como rechazada."""
    data = request.json
    video_id = data.get('video_id')
    video_url = data.get('url')
    title = data.get('title', '')
    
    if not video_id:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    save_rejected_video(video_id, url=video_url, title=title, reason="Ignorar siempre")
    return jsonify({'success': True, 'message': 'Canción marcada como rechazada'})


@app.route('/api/download/direct', methods=['POST'])
def download_direct():
    """Descarga directa con metadatos completos."""
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    task_id = str(uuid.uuid4())
    direct_download_tasks[task_id] = {'status': 'downloading', 'url': url}
    
    def download_thread():
        try:
            # Extraer video_id de la URL
            match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', url)
            video_id = match.group(1) if match else None
            
            if not video_id:
                direct_download_tasks[task_id] = {'status': 'error', 'error': 'URL inválida'}
                return
            
            # Usar la misma lógica que download_song
            download_status[video_id] = {'status': 'downloading'}
            download_logs[video_id] = []
            
            try:
                video_info = get_video_info(url)
            except Exception as e_info:
                import traceback
                tb = traceback.format_exc()
                err_msg = f"No se pudo obtener información del video: {e_info}"
                direct_download_tasks[task_id] = {'status': 'error', 'error': err_msg, 'error_detail': tb}
                download_logs[video_id].append(f"[ERROR] {err_msg}\n{tb}")
                return
            if not video_info:
                direct_download_tasks[task_id] = {'status': 'error', 'error': 'No se pudo obtener información del video (get_video_info devolvió vacío)'}
                return
            
            title = video_info.get('title', '')
            description = video_info.get('description', '')
            
            metadata = extract_metadata_from_title(title, description, video_info)
            
            if not metadata.get('genre'):
                detected_genre = detect_genre_online(
                    metadata.get('artist'),
                    metadata.get('title', title),
                    video_info=video_info,
                    title=title,
                    description=description
                )
                if detected_genre:
                    metadata['genre'] = detected_genre
                else:
                    metadata['genre'] = 'Sin Clasificar'
            
            output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))
            
            if metadata.get('artist'):
                filename = f"{metadata['artist']} - {metadata['title']}"
            else:
                filename = metadata.get('title', title)
            
            filename = sanitize_filename(filename)
            output_path = output_folder / filename
            
            if download_audio(url, str(output_path), metadata):
                mp3_file = Path(str(output_path) + '.mp3')
                if not mp3_file.exists():
                    mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
                    if mp3_files:
                        mp3_file = mp3_files[0]
                
                add_id3_tags(str(mp3_file), metadata, video_info)
                register_song_in_db(video_id, url, mp3_file, metadata, video_info, download_source='direct')
                
                direct_download_tasks[task_id] = {'status': 'completed', 'file': str(mp3_file)}
                download_status[video_id] = {'status': 'completed', 'file': str(mp3_file)}
            else:
                direct_download_tasks[task_id] = {'status': 'error', 'error': 'Error en la descarga (download_audio devolvió False)'}
                
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            direct_download_tasks[task_id] = {'status': 'error', 'error': str(e), 'error_detail': tb}
            if video_id:
                download_logs[video_id].append(tb)
    
    threading.Thread(target=download_thread, daemon=True).start()
    return jsonify({'success': True, 'task_id': task_id, 'message': 'Descarga iniciada'})


@app.route('/api/download/quick', methods=['POST'])
def download_quick_endpoint():
    """Descarga rápida sin metadatos avanzados. Devuelve task_id para poder consultar estado y errores."""
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    task_id = str(uuid.uuid4())
    direct_download_tasks[task_id] = {'status': 'downloading', 'url': url}
    
    def quick_download_thread():
        import traceback
        try:
            download_quick(url)
            direct_download_tasks[task_id] = {'status': 'completed', 'file': ''}
        except BaseException as e:
            tb = traceback.format_exc()
            err_msg = str(e)
            direct_download_tasks[task_id] = {
                'status': 'error',
                'error': err_msg,
                'error_detail': tb
            }
            print(f"[{time.strftime('%H:%M:%S')}] ❌ Error en descarga rápida: {err_msg}\n{tb}")
    
    threading.Thread(target=quick_download_thread, daemon=True).start()
    return jsonify({'success': True, 'task_id': task_id, 'message': 'Descarga rápida iniciada'})


@app.route('/api/video/info', methods=['POST'])
def get_video_info_endpoint():
    """Obtiene información de un video."""
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    try:
        video_info = get_video_info(url)
        if video_info:
            return jsonify({'success': True, 'info': video_info})
        else:
            return jsonify({'success': False, 'error': 'No se pudo obtener información del video'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


def _format_duration_seconds(seconds):
    """Convierte segundos en una cadena tipo m:ss o h:mm:ss."""
    try:
        seconds = int(seconds) if seconds is not None else None
    except (ValueError, TypeError):
        return None, None
    if not seconds or seconds < 0:
        return None, None
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return seconds, f'{h}:{m:02d}:{s:02d}'
    return seconds, f'{m}:{s:02d}'


def _search_youtube_innertube(query: str, limit: int = 8) -> list:
    """Busca en YouTube usando la API interna (InnerTube) sin yt-dlp."""
    import urllib.request as _urlreq
    import urllib.parse as _urlparse

    url = 'https://www.youtube.com/youtubei/v1/search?prettyPrint=false'
    payload = json.dumps({
        'query': query,
        'context': {
            'client': {
                'clientName': 'WEB',
                'clientVersion': '2.20240101.00.00',
                'hl': 'es',
                'gl': 'ES',
            }
        }
    }).encode('utf-8')

    req = _urlreq.Request(url, data=payload, headers={
        'Content-Type': 'application/json',
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'X-YouTube-Client-Name': '1',
        'X-YouTube-Client-Version': '2.20240101.00.00',
        'Accept-Language': 'es-ES,es;q=0.9',
    })

    with _urlreq.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode('utf-8'))

    results = []
    sections = (
        data.get('contents', {})
        .get('twoColumnSearchResultsRenderer', {})
        .get('primaryContents', {})
        .get('sectionListRenderer', {})
        .get('contents', [])
    )

    for section in sections:
        for item in section.get('itemSectionRenderer', {}).get('contents', []):
            v = item.get('videoRenderer')
            if not v:
                continue
            video_id = v.get('videoId', '')
            if not video_id:
                continue

            title = ''
            try:
                title = v['title']['runs'][0]['text']
            except (KeyError, IndexError):
                pass

            uploader = ''
            try:
                uploader = v['ownerText']['runs'][0]['text']
            except (KeyError, IndexError):
                pass

            duration_str = ''
            duration_sec = 0
            try:
                duration_str = v['lengthText']['simpleText']
                parts = [int(x) for x in duration_str.split(':')]
                if len(parts) == 2:
                    duration_sec = parts[0] * 60 + parts[1]
                elif len(parts) == 3:
                    duration_sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
            except (KeyError, ValueError):
                pass

            view_count = None
            try:
                vt = v['viewCountText']['simpleText'].replace(',', '').replace('.', '').split()[0]
                view_count = int(vt)
            except (KeyError, ValueError, IndexError):
                pass

            results.append({
                'id': video_id,
                'url': f'https://www.youtube.com/watch?v={video_id}',
                'title': title,
                'uploader': uploader,
                'duration': duration_sec,
                'duration_str': duration_str,
                'thumbnail': f'https://i.ytimg.com/vi/{video_id}/mqdefault.jpg',
                'view_count': view_count,
            })
            if len(results) >= limit:
                return results

    return results


@app.route('/api/youtube/search', methods=['GET'])
def search_youtube_endpoint():
    """Busca videos en YouTube por texto, devolviendo sugerencias para descarga.

    Query params:
      q: texto a buscar (mínimo 2 caracteres)
      limit: número máximo de resultados (1-20, por defecto 8)
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    query = (request.args.get('q') or '').strip()
    try:
        limit = int(request.args.get('limit', 8))
    except (ValueError, TypeError):
        limit = 8
    limit = max(1, min(20, limit))

    if not query or len(query) < 2:
        return jsonify({'success': True, 'query': query, 'results': []})

    search_start = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] 🔎 GET /api/youtube/search - \"{query}\" (máx {limit} resultados)")

    # Intentar primero InnerTube (más rápido, sin yt-dlp)
    try:
        print(f"    → Intentando InnerTube (rápido)...")
        results = _search_youtube_innertube(query, limit)
        if results:
            print(f"[{time.strftime('%H:%M:%S')}] ✅ InnerTube devolvió {len(results)} resultados en {time.time() - search_start:.2f}s")
            return jsonify({'success': True, 'query': query, 'results': results})
        print(f"    ⚠️  InnerTube no devolvió resultados ({time.time() - search_start:.2f}s), pasando a yt-dlp")
    except Exception as e:
        print(f"    ⚠️  InnerTube falló ({type(e).__name__}: {e}), pasando a yt-dlp")

    # Fallback: yt-dlp con timeout real via thread
    try:
        import yt_dlp as _yt_dlp
    except ImportError:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ yt-dlp no está instalado")
        return jsonify({'success': False, 'error': 'yt-dlp no está instalado'}), 500

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
        'ignoreerrors': True,
        'default_search': 'ytsearch',
        'socket_timeout': 8,
        'extractor_retries': 0,
        'retries': 0,
    }
    apply_cookies_to_opts(ydl_opts)

    def _do_ytdlp_search():
        with _yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f'ytsearch{limit}:{query}', download=False)
        entries = (info or {}).get('entries') or []
        out = []
        for entry in entries:
            if not entry:
                continue
            video_id = entry.get('id') or ''
            if not video_id:
                continue
            thumbnail = entry.get('thumbnail')
            if not thumbnail:
                thumbs = entry.get('thumbnails') or []
                thumbnail = thumbs[-1].get('url') if thumbs else None
            if not thumbnail:
                thumbnail = f'https://i.ytimg.com/vi/{video_id}/mqdefault.jpg'
            duration_sec, duration_str = _format_duration_seconds(entry.get('duration'))
            out.append({
                'id': video_id,
                'url': entry.get('url') or f'https://www.youtube.com/watch?v={video_id}',
                'title': entry.get('title') or '',
                'uploader': entry.get('uploader') or entry.get('channel') or '',
                'duration': duration_sec,
                'duration_str': duration_str,
                'thumbnail': thumbnail,
                'view_count': entry.get('view_count'),
            })
        return out

    try:
        print(f"    → Buscando con yt-dlp (timeout 10s)...")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_ytdlp_search)
            results = future.result(timeout=10)
        print(f"[{time.strftime('%H:%M:%S')}] ✅ yt-dlp devolvió {len(results)} resultados en {time.time() - search_start:.2f}s")
        return jsonify({'success': True, 'query': query, 'results': results})
    except FuturesTimeout:
        print(f"[{time.strftime('%H:%M:%S')}] ⏱️  yt-dlp no respondió en 10s (total {time.time() - search_start:.2f}s)")
        return jsonify({'success': False, 'error': 'YouTube tardó demasiado en responder. Prueba en unos segundos.'}), 504
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Error en yt-dlp tras {time.time() - search_start:.2f}s: {type(e).__name__}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

    entries = (info or {}).get('entries') or []
    results = []
    for entry in entries:
        if not entry:
            continue
        video_id = entry.get('id') or ''
        if not video_id:
            continue
        thumbnail = entry.get('thumbnail')
        if not thumbnail:
            thumbs = entry.get('thumbnails') or []
            if thumbs:
                thumbnail = thumbs[-1].get('url')
        if not thumbnail:
            thumbnail = f'https://i.ytimg.com/vi/{video_id}/mqdefault.jpg'

        duration_sec, duration_str = _format_duration_seconds(entry.get('duration'))

        results.append({
            'id': video_id,
            'url': entry.get('url') or f'https://www.youtube.com/watch?v={video_id}',
            'title': entry.get('title') or '',
            'uploader': entry.get('uploader') or entry.get('channel') or '',
            'duration': duration_sec,
            'duration_str': duration_str,
            'thumbnail': thumbnail,
            'view_count': entry.get('view_count'),
        })

    return jsonify({'success': True, 'query': query, 'results': results})


@app.route('/api/database/songs', methods=['GET'])
def get_database_songs():
    """Obtiene canciones de la base de datos."""
    try:
        search = request.args.get('search', '')
        show_ignored = request.args.get('show_ignored', 'false').lower() == 'true'
        try:
            limit_arg = int(request.args.get('limit', 100))
            limit = None if limit_arg <= 0 else limit_arg
        except (ValueError, TypeError):
            limit = 100
        
        # Verificar que la base de datos esté inicializada
        if db is None:
            return jsonify({'success': False, 'error': 'Base de datos no inicializada'}), 500
        
        # Obtener canciones filtrando por búsqueda directamente en SQL (el límite se aplica sobre los ya filtrados)
        songs = db.get_all_songs(limit=limit, search=search if search else None)

        # Convertir a formato serializable (asegurar que todos los valores sean JSON-serializables)
        serializable_songs = []
        for song in songs:
            serializable_song = {}
            for key, value in song.items():
                # Convertir valores None, datetime, etc. a strings
                if value is None:
                    serializable_song[key] = None
                elif key == 'waveform_data' and isinstance(value, str) and value.strip().startswith('['):
                    try:
                        serializable_song[key] = json.loads(value)
                    except json.JSONDecodeError:
                        serializable_song[key] = None
                elif isinstance(value, (int, float, str, bool)):
                    serializable_song[key] = value
                else:
                    # Convertir cualquier otro tipo a string
                    serializable_song[key] = str(value)
            # Asegurar que los campos de volumen estén siempre presentes (para que la UI los muestre)
            if 'volume_lufs' not in serializable_song:
                serializable_song['volume_lufs'] = None
            if 'volume_offset_db' not in serializable_song:
                serializable_song['volume_offset_db'] = None
            if 'waveform_data' not in serializable_song:
                serializable_song['waveform_data'] = None
            serializable_songs.append(serializable_song)
        
        # Filtrar ignoradas si es necesario
        if not show_ignored:
            # Verificar si hay canciones rechazadas en la base de datos
            serializable_songs = [s for s in serializable_songs if not s.get('is_rejected', False)]
        
        return jsonify({
            'success': True,
            'songs': serializable_songs,
            'count': len(serializable_songs)
        })
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()
        return jsonify({'success': False, 'error': error_msg}), 500


@app.route('/api/database/generate-missing-waveforms', methods=['POST'])
def generate_missing_waveforms():
    """Genera la forma de onda para todas las canciones que aún no la tienen."""
    try:
        if db is None:
            return jsonify({'success': False, 'error': 'Base de datos no inicializada'}), 500
        limit = min(30, max(1, int(request.args.get('limit', 20))))
        songs = db.get_all_songs(limit=None)
        without_waveform = [s for s in songs if not s.get('waveform_data') or (isinstance(s.get('waveform_data'), str) and not (s.get('waveform_data') or '').strip())]
        to_process = without_waveform[:limit]
        generated = 0
        for song in to_process:
            video_id = song.get('video_id')
            file_path_raw = (song.get('file_path') or '').strip()
            if not video_id or not file_path_raw:
                continue
            path_obj = _normalize_file_path_from_db(file_path_raw)
            if not path_obj or not path_obj.exists() or not path_obj.is_file():
                continue
            waveform = generate_waveform_data(str(path_obj))
            if waveform is not None:
                db.update_song(video_id, waveform_data=json.dumps(waveform))
                generated += 1
        remaining = len(without_waveform) - generated
        return jsonify({
            'success': True,
            'generated': generated,
            'remaining': max(0, remaining)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/database/fetch-missing-albumart', methods=['POST'])
def fetch_missing_albumart():
    """Busca y rellena el album art (thumbnail_url) para canciones que no lo tienen."""
    try:
        if db is None:
            return jsonify({'success': False, 'error': 'Base de datos no inicializada'}), 500

        limit_arg = int(request.args.get('limit', 10))
        limit = None if limit_arg <= 0 else max(1, limit_arg)
        songs = db.get_all_songs(limit=None)
        without_art = [s for s in songs if not (s.get('thumbnail_url') or '').strip()]
        to_process = without_art if limit is None else without_art[:limit]

        fetched = 0
        not_found = 0
        for song in to_process:
            thumb_url = _fetch_albumart_for_song(song)
            if thumb_url:
                db.update_song(song['video_id'], thumbnail_url=thumb_url)
                fetched += 1
                # Intentar actualizar la tag APIC del archivo MP3
                try:
                    from mutagen.id3 import ID3, APIC
                    from mutagen.mp3 import MP3
                    import urllib.request as _ureq
                    file_path_raw = (song.get('file_path') or '').strip()
                    if file_path_raw:
                        path_obj = _normalize_file_path_from_db(file_path_raw)
                        if path_obj and path_obj.exists() and path_obj.is_file():
                            req = _ureq.Request(thumb_url, headers={'User-Agent': 'Mozilla/5.0'})
                            with _ureq.urlopen(req, timeout=10) as r:
                                img_data = r.read()
                            audio = MP3(str(path_obj), ID3=ID3)
                            audio['APIC'] = APIC(
                                encoding=3, mime='image/jpeg',
                                type=3, desc='Cover', data=img_data
                            )
                            audio.save()
                except Exception:
                    pass
            else:
                not_found += 1

        remaining = max(0, len(without_art) - len(to_process))
        return jsonify({
            'success': True,
            'fetched': fetched,
            'not_found': not_found,
            'remaining': remaining,
            'processed': len(to_process)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/database/song/<video_id>/cover', methods=['GET'])
def serve_song_cover(video_id):
    """Sirve la portada embebida (APIC) de un archivo MP3 directamente como imagen."""
    song = db.get_song_by_video_id(video_id)
    if not song:
        return jsonify({'success': False, 'error': 'Canción no encontrada'}), 404
    file_path_raw = (song.get('file_path') or '').strip()
    if not file_path_raw:
        return jsonify({'success': False, 'error': 'Sin ruta de archivo'}), 404
    path_obj = _normalize_file_path_from_db(file_path_raw)
    if not path_obj or not path_obj.exists():
        return jsonify({'success': False, 'error': 'Archivo no encontrado'}), 404
    try:
        import io
        from mutagen.id3 import ID3
        from mutagen.mp3 import MP3
        audio = MP3(str(path_obj), ID3=ID3)
        for key in audio.keys():
            if key.startswith('APIC'):
                apic = audio[key]
                return send_file(io.BytesIO(apic.data), mimetype=apic.mime or 'image/jpeg')
        return jsonify({'success': False, 'error': 'Sin portada embebida'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/database/song/<video_id>/albumart', methods=['POST'])
def fetch_albumart_for_song(video_id):
    """Busca y guarda el album art para una canción específica."""
    song = db.get_song_by_video_id(video_id)
    if not song:
        return jsonify({'success': False, 'error': 'Canción no encontrada'}), 404

    thumb_url = _fetch_albumart_for_song(song)
    if not thumb_url:
        return jsonify({'success': False, 'error': 'No se encontró album art'}), 404

    db.update_song(video_id, thumbnail_url=thumb_url)

    # Intentar actualizar la tag APIC del archivo MP3
    try:
        from mutagen.id3 import ID3, APIC
        from mutagen.mp3 import MP3
        import urllib.request as _ureq
        file_path_raw = (song.get('file_path') or '').strip()
        if file_path_raw:
            path_obj = _normalize_file_path_from_db(file_path_raw)
            if path_obj and path_obj.exists() and path_obj.is_file():
                req = _ureq.Request(thumb_url, headers={'User-Agent': 'Mozilla/5.0'})
                with _ureq.urlopen(req, timeout=10) as r:
                    img_data = r.read()
                audio = MP3(str(path_obj), ID3=ID3)
                audio['APIC'] = APIC(
                    encoding=3, mime='image/jpeg',
                    type=3, desc='Cover', data=img_data
                )
                audio.save()
    except Exception:
        pass

    source = 'YouTube' if 'ytimg.com' in thumb_url else 'búsqueda online'
    return jsonify({
        'success': True,
        'thumbnail_url': thumb_url,
        'source': source,
        'title': song.get('title', '')
    })


@app.route('/api/database/duplicates', methods=['GET'])
def get_database_duplicates():
    """Obtiene grupos de canciones duplicadas (mismo título + artista)."""
    try:
        if db is None:
            return jsonify({'success': False, 'error': 'Base de datos no inicializada'}), 500
        groups = db.get_duplicate_songs()
        # Serializar canciones en cada grupo (como en get_database_songs)
        serializable_groups = []
        for g in groups:
            songs = []
            for song in g['songs']:
                s = {}
                for key, value in song.items():
                    if value is None:
                        s[key] = None
                    elif isinstance(value, (int, float, str, bool)):
                        s[key] = value
                    else:
                        s[key] = str(value)
                if 'volume_lufs' not in s:
                    s['volume_lufs'] = None
                if 'volume_offset_db' not in s:
                    s['volume_offset_db'] = None
                songs.append(s)
            serializable_groups.append({
                'key': g['key'],
                'count': g['count'],
                'songs': songs
            })
        return jsonify({
            'success': True,
            'groups': serializable_groups,
            'total_duplicate_groups': len(serializable_groups),
            'total_duplicate_songs': sum(g['count'] for g in serializable_groups)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/database/statistics', methods=['GET'])
def get_database_statistics():
    """Obtiene estadísticas de la base de datos."""
    try:
        stats = db.get_statistics()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/database/delete', methods=['POST'])
def delete_song_from_db():
    """Elimina una canción de la base de datos y su archivo."""
    data = request.json
    video_id = data.get('video_id')
    
    if not video_id:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    try:
        # Obtener datos de la canción antes de eliminarla
        song = db.get_song_by_video_id(video_id)
        if not song:
            return jsonify({'success': False, 'error': 'Canción no encontrada'}), 404
        
        file_path = song.get('file_path', '')
        file_deleted = False
        
        # Eliminar archivo físico si existe
        if file_path:
            try:
                file_path_obj = Path(file_path)
                if file_path_obj.exists():
                    file_path_obj.unlink()
                    file_deleted = True
            except Exception as e:
                print(f"Error al eliminar archivo: {e}")
                # Continuar aunque falle la eliminación del archivo
        
        # Eliminar de la base de datos
        deleted_song = db.delete_song(video_id)
        if deleted_song:
            return jsonify({
                'success': True,
                'message': 'Canción eliminada correctamente',
                'file_deleted': file_deleted,
                'file_path': file_path
            })
        else:
            return jsonify({'success': False, 'error': 'No se pudo eliminar de la base de datos'}), 500
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/database/play', methods=['POST'])
def play_song():
    """Obtiene la ruta del archivo para reproducir una canción."""
    data = request.json
    video_id = data.get('video_id')
    
    if not video_id:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    try:
        song = db.get_song_by_video_id(video_id)
        if not song:
            return jsonify({'success': False, 'error': 'Canción no encontrada'}), 404
        
        file_path = song.get('file_path', '')
        if not file_path:
            return jsonify({'success': False, 'error': 'No hay ruta de archivo'}), 404
        
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            return jsonify({'success': False, 'error': 'El archivo no existe'}), 404
        
        # Devolver la ruta del archivo (el frontend se encargará de reproducirlo)
        return jsonify({
            'success': True,
            'file_path': str(file_path_obj),
            'file_url': f'/api/database/file?path={quote(str(file_path_obj))}',
            'title': song.get('title', ''),
            'artist': song.get('artist', '')
        })
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/database/song/<video_id>/volume', methods=['POST'])
def adjust_song_volume(video_id):
    """Sube o baja el volumen de una canción (modifica el archivo)."""
    data = request.json or {}
    delta_db = data.get('delta_db')
    if delta_db is None:
        return jsonify({'success': False, 'error': 'Indica delta_db en dB (ej: 2 para subir, -1.5 para bajar)'}), 400
    try:
        delta_db = float(delta_db)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'delta_db debe ser un número (ej: 2 o -1.5)'}), 400
    
    song = db.get_song_by_video_id(video_id)
    if not song:
        return jsonify({'success': False, 'error': 'Canción no encontrada'}), 404
    
    file_path_raw = song.get('file_path', '')
    path_obj = _normalize_file_path_from_db(file_path_raw)
    if not path_obj or not path_obj.exists() or not path_obj.is_file():
        return jsonify({'success': False, 'error': 'Archivo no encontrado'}), 404
    file_path = str(path_obj)
    
    ok, vol_error = apply_volume_offset(file_path, delta_db)
    if not ok:
        return jsonify({
            'success': False,
            'error': vol_error or 'No se pudo aplicar el cambio de volumen'
        }), 500
    
    volume_lufs, _ = check_audio_volume(file_path)
    db.update_song(video_id, volume_lufs=volume_lufs, volume_offset_db=0)
    return jsonify({
        'success': True,
        'message': f'Volumen {"subido" if delta_db > 0 else "bajado"} {abs(delta_db):.1f} dB',
        'volume_lufs': volume_lufs
    })


@app.route('/api/database/song/<video_id>/measure-volume', methods=['POST'])
def measure_song_volume(video_id):
    """Mide el volumen actual del archivo y actualiza la base de datos."""
    song = db.get_song_by_video_id(video_id)
    if not song:
        return jsonify({'success': False, 'error': 'Canción no encontrada'}), 404
    file_path_raw = song.get('file_path', '').strip()
    if not file_path_raw:
        return jsonify({'success': False, 'error': 'La canción no tiene ruta de archivo en la base de datos'}), 400
    path_obj = _normalize_file_path_from_db(file_path_raw)
    if not path_obj:
        return jsonify({'success': False, 'error': 'Ruta de archivo no válida'}), 400
    if not path_obj.exists():
        return jsonify({
            'success': False,
            'error': 'Archivo no encontrado en disco',
            'file_path': str(path_obj)
        }), 404
    if not path_obj.is_file():
        return jsonify({
            'success': False,
            'error': 'La ruta no es un archivo (¿es una carpeta?)',
            'file_path': str(path_obj)
        }), 400
    file_path = str(path_obj)
    if not shutil.which('ffmpeg'):
        return jsonify({
            'success': False,
            'error': 'ffmpeg no está instalado o no está en el PATH del sistema',
            'file_path': file_path
        }), 500
    volume_lufs, ffmpeg_error = check_audio_volume(file_path)
    if volume_lufs is None:
        return jsonify({
            'success': False,
            'error': ffmpeg_error or 'No se pudo medir el volumen',
            'file_path': file_path
        }), 500
    db.update_song(video_id, volume_lufs=volume_lufs)
    return jsonify({'success': True, 'volume_lufs': volume_lufs})


@app.route('/api/database/song/<video_id>/waveform', methods=['POST'])
def generate_song_waveform(video_id):
    """Genera la forma de onda de la canción y la guarda en la base de datos."""
    song = db.get_song_by_video_id(video_id)
    if not song:
        return jsonify({'success': False, 'error': 'Canción no encontrada'}), 404
    file_path_raw = song.get('file_path', '').strip()
    if not file_path_raw:
        return jsonify({'success': False, 'error': 'La canción no tiene ruta de archivo'}), 400
    path_obj = _normalize_file_path_from_db(file_path_raw)
    if not path_obj or not path_obj.exists() or not path_obj.is_file():
        return jsonify({'success': False, 'error': 'Archivo no encontrado en disco'}), 404
    waveform = generate_waveform_data(str(path_obj))
    if waveform is None:
        return jsonify({'success': False, 'error': 'No se pudo generar la forma de onda (¿ffmpeg instalado?)'}), 500
    db.update_song(video_id, waveform_data=json.dumps(waveform))
    return jsonify({'success': True, 'waveform_data': waveform})


@app.route('/api/database/song/<video_id>/reclassify', methods=['POST'])
def reclassify_song(video_id):
    """Vuelve a clasificar el género de una canción usando Essentia (análisis de audio)."""
    song = db.get_song_by_video_id(video_id)
    if not song:
        return jsonify({'success': False, 'error': 'Canción no encontrada'}), 404
    file_path_raw = song.get('file_path', '').strip()
    if not file_path_raw:
        return jsonify({'success': False, 'error': 'No hay ruta de archivo para esta canción'}), 400
    path_obj = _normalize_file_path_from_db(file_path_raw)
    if not path_obj or not path_obj.exists() or not path_obj.is_file():
        return jsonify({'success': False, 'error': f'Archivo no encontrado: {path_obj}'}), 404
    try:
        genre = get_genre_from_essentia(str(path_obj))
        new_genre = genre if genre else 'Sin Clasificar'
        db.update_song(video_id, genre=new_genre)
        return jsonify({
            'success': True,
            'genre': new_genre,
            'message': f'Género actualizado a: {new_genre}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/database/song/<video_id>/redownload', methods=['POST'])
def redownload_song(video_id):
    """Vuelve a descargar una canción desde YouTube (sustituye el archivo)."""
    song = db.get_song_by_video_id(video_id)
    if not song:
        return jsonify({'success': False, 'error': 'Canción no encontrada'}), 404
    
    url = song.get('url', '')
    if not url or 'youtube' not in url.lower():
        return jsonify({'success': False, 'error': 'No hay URL de YouTube para esta canción'}), 400
    
    file_path = song.get('file_path', '')
    if not file_path:
        return jsonify({'success': False, 'error': 'No hay ruta de archivo'}), 400
    
    path_obj = Path(file_path)
    if not path_obj.parent.exists():
        return jsonify({'success': False, 'error': 'La carpeta del archivo no existe'}), 404
    
    # Metadatos a partir de la canción
    metadata = {
        'title': song.get('title', ''),
        'artist': song.get('artist'),
        'genre': song.get('genre'),
        'year': song.get('year')
    }
    
    try:
        video_info = get_video_info(url)
    except Exception as e:
        return jsonify({'success': False, 'error': f'No se pudo obtener info del video: {e}'}), 500
    if not video_info:
        return jsonify({'success': False, 'error': 'No se pudo obtener información del video'}), 500
    
    # Descargar al mismo directorio con mismo nombre base (sobrescribe)
    output_path = path_obj.parent / path_obj.stem
    if not download_audio(url, str(output_path), metadata):
        return jsonify({'success': False, 'error': 'Error en la descarga'}), 500
    
    mp3_file = path_obj
    if not mp3_file.exists():
        mp3_files = list(path_obj.parent.glob(f"{path_obj.stem}*.mp3"))
        mp3_file = mp3_files[0] if mp3_files else path_obj
    
    mp3_file = Path(mp3_file)
    add_id3_tags(str(mp3_file), metadata, video_info)
    volume_lufs, _ = check_audio_volume(str(mp3_file))
    file_size = mp3_file.stat().st_size if mp3_file.exists() else None
    db.update_song(video_id, file_path=str(mp3_file), file_size=file_size, volume_lufs=volume_lufs, volume_offset_db=0)
    
    return jsonify({
        'success': True,
        'message': 'Canción vuelta a descargar correctamente',
        'file_path': str(mp3_file),
        'volume_lufs': volume_lufs
    })


@app.route('/api/database/redownload-full', methods=['POST'])
def api_redownload_full():
    """Vuelve a descargar una o varias canciones con todo el proceso (metadatos, género, etc.)."""
    data = request.json or {}
    video_ids = data.get('video_ids') or []
    if data.get('video_id'):
        video_ids = [data['video_id']]
    if not video_ids:
        return jsonify({'success': False, 'error': 'Faltan video_id o video_ids'}), 400

    task_id = str(uuid.uuid4())
    redownload_full_status[task_id] = {
        'status': 'running',
        'total': len(video_ids),
        'current': 0,
        'current_video_id': None,
        'current_message': '',
        'results': []
    }

    def run_redownloads():
        status = redownload_full_status[task_id]
        try:
            for i, vid in enumerate(video_ids):
                status['current'] = i
                status['current_video_id'] = vid
                status['current_message'] = f'Procesando {i + 1}/{len(video_ids)}...'

                def progress(msg):
                    status['current_message'] = msg

                success, err = redownload_full(vid, progress_callback=progress)
                status['results'].append({'video_id': vid, 'success': success, 'error': err})
            status['status'] = 'completed'
            status['current_message'] = 'Completado'
        except Exception as e:
            status['status'] = 'error'
            status['error'] = str(e)
            status['current_message'] = str(e)

    threading.Thread(target=run_redownloads, daemon=True).start()
    return jsonify({'success': True, 'task_id': task_id})


@app.route('/api/database/redownload-full/status/<task_id>', methods=['GET'])
def api_redownload_full_status(task_id):
    """Estado de la tarea de redownload completo."""
    status = redownload_full_status.get(task_id, {})
    if not status:
        return jsonify({'success': False, 'error': 'Tarea no encontrada'}), 404
    return jsonify({
        'success': True,
        'status': status.get('status'),
        'total': status.get('total', 0),
        'current': status.get('current', 0),
        'current_video_id': status.get('current_video_id'),
        'current_message': status.get('current_message', ''),
        'results': status.get('results', []),
        'error': status.get('error')
    })


@app.route('/api/database/file', methods=['GET'])
def serve_song_file():
    """Sirve un archivo de audio para reproducir."""
    file_path = request.args.get('path')
    
    if not file_path:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    try:
        file_path_obj = Path(file_path)
        
        # Verificar que el archivo existe y está dentro de la carpeta de música
        if not file_path_obj.exists():
            return jsonify({'success': False, 'error': 'El archivo no existe'}), 404
        
        # Verificar que está dentro de la carpeta de música (seguridad)
        music_folder = Path(MUSIC_FOLDER).resolve()
        file_path_resolved = file_path_obj.resolve()
        
        try:
            file_path_resolved.relative_to(music_folder)
        except ValueError:
            # El archivo no está dentro de la carpeta de música
            return jsonify({'success': False, 'error': 'Acceso denegado'}), 403
        
        # Determinar el tipo MIME
        mime_type = 'audio/mpeg'
        if file_path_obj.suffix.lower() == '.mp3':
            mime_type = 'audio/mpeg'
        elif file_path_obj.suffix.lower() == '.m4a':
            mime_type = 'audio/mp4'
        elif file_path_obj.suffix.lower() == '.ogg':
            mime_type = 'audio/ogg'
        elif file_path_obj.suffix.lower() == '.wav':
            mime_type = 'audio/wav'
        
        return send_file(
            str(file_path_obj),
            mimetype=mime_type,
            as_attachment=False
        )
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/import/folder', methods=['POST'])
def import_folder():
    """Importa una carpeta de MP3s."""
    data = request.json
    folder = data.get('folder')
    
    if not folder:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    folder_path = Path(folder)
    if not folder_path.exists() or not folder_path.is_dir():
        return jsonify({'success': False, 'error': 'La carpeta no existe'}), 400
    
    task_id = str(uuid.uuid4())
    import_status[task_id] = {'status': 'importing'}
    import_logs[task_id] = []

    def add_log(msg: str):
        """Añade un mensaje al log de la importación (visible en la consola flotante y en la terminal)."""
        import_logs[task_id].append(str(msg))
        try:
            print(f"[{time.strftime('%H:%M:%S')}] [import {task_id[:8]}] {msg}")
        except Exception:
            pass

    def import_thread():
        try:
            add_log(f"📁 Carpeta a importar: {folder_path}")
            add_log(f"🔎 Buscando archivos MP3 recursivamente (incluye subcarpetas)...")

            # rglob es recursivo: encuentra MP3s en TODOS los subdirectorios.
            # Antes se usaba glob() que solo miraba el primer nivel y devolvía 0
            # cuando la carpeta tenía toda la música organizada en subcarpetas.
            mp3_files = sorted(folder_path.rglob('*.mp3'))
            total = len(mp3_files)

            if total == 0:
                add_log("⚠️  No se encontraron archivos MP3 en la carpeta ni en sus subcarpetas")
                import_status[task_id] = {'status': 'completed', 'count': 0}
                return

            # Contar cuántas subcarpetas distintas hay para dar contexto en el log
            subfolders = {mp3.parent for mp3 in mp3_files}
            add_log(f"✅ Encontrados {total} archivos MP3 en {len(subfolders)} carpeta(s)")

            ok_count = 0
            skipped_count = 0
            error_count = 0

            for idx, mp3_file in enumerate(mp3_files, 1):
                try:
                    # Mostrar la ruta relativa para que el usuario sepa de qué subcarpeta viene
                    try:
                        rel_path = mp3_file.relative_to(folder_path)
                    except ValueError:
                        rel_path = mp3_file
                    add_log(f"[{idx}/{total}] 🎵 Procesando: {rel_path}")
                    result = process_imported_mp3(
                        mp3_file,
                        MUSIC_FOLDER,
                        log_callback=add_log
                    )
                    if result:
                        ok_count += 1
                        add_log(f"   ✅ Procesado: {mp3_file.name}")
                    else:
                        skipped_count += 1
                        add_log(f"   ⚠️ Ya existe o error: {mp3_file.name}")
                except Exception as e:
                    error_count += 1
                    add_log(f"   ❌ Error procesando {mp3_file.name}: {str(e)}")

            add_log(f"📊 Resumen: {ok_count} procesadas · {skipped_count} ya existentes · {error_count} con error · total {total}")
            import_status[task_id] = {'status': 'completed', 'count': total}
        except Exception as e:
            import_status[task_id] = {'status': 'error', 'error': str(e)}
            import traceback
            add_log(f"❌ Excepción global en la importación: {e}")
            add_log(traceback.format_exc())

    threading.Thread(target=import_thread, daemon=True).start()
    return jsonify({'success': True, 'task_id': task_id, 'message': 'Importación iniciada'})


@app.route('/api/import/status/<task_id>', methods=['GET'])
def get_import_status(task_id):
    """Obtiene el estado de una importación."""
    status = import_status.get(task_id, {'status': 'idle'})
    logs = import_logs.get(task_id, [])
    return jsonify({
        'status': status.get('status', 'idle'),
        'error': status.get('error'),
        'logs': logs
    })


@app.route('/api/testing/genre', methods=['POST'])
def test_genre():
    """Prueba la detección de género."""
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    try:
        video_info = get_video_info(url)
        if not video_info:
            return jsonify({'success': False, 'error': 'No se pudo obtener información del video'})
        
        title = video_info.get('title', '')
        description = video_info.get('description', '')
        metadata = extract_metadata_from_title(title, description, video_info)
        
        genre = detect_genre_online(
            metadata.get('artist'),
            metadata.get('title', title),
            video_info=video_info,
            title=title,
            description=description
        )
        
        return jsonify({
            'success': True,
            'genre': genre or 'Sin Clasificar',
            'metadata': metadata
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/config', methods=['GET'])
def get_config():
    """Obtiene la configuración actual."""
    try:
        config = {}
        env_path = _get_config_dir() / '.env'
        
        if env_path.exists():
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            parts = line.split('=', 1)
                            if len(parts) == 2:
                                key = parts[0].strip()
                                value = parts[1].strip()
                                # Remover comillas si las hay
                                if value.startswith('"') and value.endswith('"'):
                                    value = value[1:-1].replace('\\\\', '\\')
                                elif value.startswith("'") and value.endswith("'"):
                                    value = value[1:-1].replace('\\\\', '\\')
                                config[key] = value
            except PermissionError as pe:
                print(f"⚠️  Sin permiso para leer .env ({pe}); se devuelve config parcial")
        
        # Obtener la ruta real de la base de datos (por defecto si no está configurada)
        db_path_config = config.get('DB_PATH', '')
        if not db_path_config and db is not None:
            # Usar la ruta real de la base de datos actual
            db_path_config = str(db.db_path)
        
        return jsonify({
            'success': True,
            'config': {
                'ENV_PATH': str(env_path.resolve()),
                'MUSIC_FOLDER': config.get('MUSIC_FOLDER', ''),
                'DB_PATH': db_path_config,
                'LASTFM_API_KEY': config.get('LASTFM_API_KEY', ''),
                'ESSENTIA_CLASSIFIER': config.get('ESSENTIA_CLASSIFIER', 'auto'),
                'YOUTUBE_COOKIES_BROWSER': config.get('YOUTUBE_COOKIES_BROWSER', ''),
                'YOUTUBE_COOKIES_BROWSER_PROFILE': config.get('YOUTUBE_COOKIES_BROWSER_PROFILE', ''),
                'YOUTUBE_COOKIES_FILE': config.get('YOUTUBE_COOKIES_FILE', '')
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/config/ffmpeg-status', methods=['GET'])
def get_ffmpeg_status():
    """Devuelve si ffmpeg está disponible y, si no, instrucciones de instalación."""
    ffmpeg_path = shutil.which('ffmpeg')
    ffprobe_path = shutil.which('ffprobe')
    available = bool(ffmpeg_path)

    if available:
        return jsonify({
            'success': True,
            'available': True,
            'ffmpeg_path': ffmpeg_path,
            'ffprobe_path': ffprobe_path,
        })

    is_windows = sys.platform == 'win32'
    is_linux = sys.platform.startswith('linux')
    is_mac = sys.platform == 'darwin'

    if is_windows:
        install_method = 'winget'
        install_cmd = 'winget install --id Gyan.FFmpeg -e --source winget'
        install_note = 'Tras instalar, reinicia la aplicación para que detecte ffmpeg.'
    elif is_mac:
        install_method = 'homebrew'
        install_cmd = 'brew install ffmpeg'
        install_note = 'Tras instalar, reinicia la aplicación.'
    else:
        install_method = 'apt'
        install_cmd = 'sudo apt install ffmpeg'
        install_note = 'En otras distribuciones usa el gestor de paquetes correspondiente (dnf, pacman, etc.).'

    return jsonify({
        'success': True,
        'available': False,
        'ffmpeg_path': None,
        'ffprobe_path': None,
        'platform': sys.platform,
        'install_method': install_method,
        'install_cmd': install_cmd,
        'install_note': install_note,
        'download_url': 'https://ffmpeg.org/download.html',
        'windows_url': 'https://www.gyan.dev/ffmpeg/builds/',
    })


@app.route('/api/config/ffmpeg-install', methods=['POST'])
def install_ffmpeg_winget():
    """Intenta instalar ffmpeg mediante winget (solo Windows)."""
    if sys.platform != 'win32':
        return jsonify({'success': False, 'error': 'Instalación automática solo disponible en Windows'}), 400

    import subprocess
    try:
        result = subprocess.run(
            ['winget', 'install', '--id', 'Gyan.FFmpeg', '-e', '--source', 'winget', '--accept-package-agreements', '--accept-source-agreements'],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            ffmpeg_path = shutil.which('ffmpeg')
            return jsonify({
                'success': True,
                'message': 'ffmpeg instalado correctamente. Reinicia la aplicación para aplicar los cambios.',
                'ffmpeg_path': ffmpeg_path,
            })
        else:
            err = (result.stderr or result.stdout or '').strip() or f'Código de salida: {result.returncode}'
            return jsonify({'success': False, 'error': err, 'output': result.stdout})
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'winget no está disponible en este sistema. Instala ffmpeg manualmente desde https://www.gyan.dev/ffmpeg/builds/'})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Tiempo de espera agotado. Instala ffmpeg manualmente.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/config/cookies/status', methods=['GET'])
def get_cookies_status():
    """Devuelve la fuente de cookies que está actualmente activa para yt-dlp."""
    browser_cfg = get_cookies_browser()
    cookies_file = get_cookies_file()
    if browser_cfg:
        source = 'browser'
        details = {
            'browser': browser_cfg[0],
            'profile': browser_cfg[1] if len(browser_cfg) > 1 else None
        }
    elif cookies_file:
        source = 'file'
        details = {'file': cookies_file}
    else:
        source = None
        details = {}
    return jsonify({
        'success': True,
        'source': source,
        'details': details,
        'supported_browsers': list(SUPPORTED_COOKIE_BROWSERS)
    })


@app.route('/api/config/cookies/test', methods=['POST'])
def test_cookies_endpoint():
    """Prueba la configuración de cookies actual accediendo a la playlist 'LM' (Mi música que me gusta)."""
    if not has_cookies_configured():
        return jsonify({
            'success': False,
            'error': 'No hay cookies configuradas (ni navegador ni archivo). '
                     'Configura YOUTUBE_COOKIES_BROWSER o YOUTUBE_COOKIES_FILE.'
        })

    try:
        import yt_dlp as _yt_dlp
    except ImportError:
        return jsonify({'success': False, 'error': 'yt-dlp no está instalado'}), 500

    browser_cfg = get_cookies_browser()
    cookies_file = get_cookies_file()
    if browser_cfg:
        source_label = f"navegador {browser_cfg[0]}" + (
            f" (perfil: {browser_cfg[1]})" if len(browser_cfg) > 1 else ''
        )
    else:
        source_label = f"archivo {cookies_file}"

    test_url = (request.json or {}).get('url') or 'https://music.youtube.com/playlist?list=LM'

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'playlistend': 3,
        'ignoreerrors': True,
    }
    apply_cookies_to_opts(ydl_opts)

    import io as _io
    import sys as _sys
    old_stderr = _sys.stderr
    buf = _io.StringIO()
    _sys.stderr = buf
    try:
        with _yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(test_url, download=False)
        stderr_text = buf.getvalue()
    except Exception as e:
        stderr_text = buf.getvalue()
        return jsonify({
            'success': False,
            'source': source_label,
            'error': f'{type(e).__name__}: {e}',
            'stderr': stderr_text.strip() or None,
            'hint': _build_cookies_hint(str(e))
        })
    finally:
        _sys.stderr = old_stderr

    if not info:
        return jsonify({
            'success': False,
            'source': source_label,
            'error': 'yt-dlp no devolvió información de la playlist',
            'stderr': stderr_text.strip() or None,
            'hint': _build_cookies_hint(stderr_text)
        })

    entries = info.get('entries') or []
    if hasattr(entries, '__iter__') and not isinstance(entries, (list, tuple, str)):
        try:
            entries = list(entries)
        except Exception:
            entries = []
    entries = [e for e in entries if e is not None]

    if not entries:
        return jsonify({
            'success': False,
            'source': source_label,
            'title': info.get('title'),
            'error': 'La playlist se abrió pero no devolvió canciones (cookies posiblemente sin sesión válida)',
            'stderr': stderr_text.strip() or None,
            'hint': _build_cookies_hint(stderr_text)
        })

    sample = [
        {'title': e.get('title'), 'id': e.get('id')}
        for e in entries[:3]
    ]
    return jsonify({
        'success': True,
        'source': source_label,
        'title': info.get('title') or 'Playlist',
        'count': len(entries),
        'sample': sample
    })


def _build_cookies_hint(error_text: str) -> str:
    """Devuelve un mensaje de ayuda según el tipo de error de yt-dlp."""
    txt = (error_text or '').lower()
    if 'does not exist' in txt or 'this playlist does not exist' in txt:
        return ('YouTube responde "playlist no existe": tus cookies no están autenticadas. '
                'Si usas archivo, exporta las cookies de un perfil donde estés logueado en YouTube Music '
                'y NO sigas usando ese perfil. Si usas navegador, asegúrate de tener sesión iniciada en él.')
    if 'sign in' in txt or 'confirm you' in txt or 'bot' in txt:
        return 'YouTube ha detectado actividad sospechosa. Reinicia sesión en el navegador o exporta cookies nuevas.'
    if 'could not find' in txt and 'cookies' in txt:
        return ('No se pudieron leer las cookies del navegador. Cierra todas las ventanas del navegador '
                'antes de intentarlo (algunos navegadores bloquean el acceso al cookie store cuando están abiertos).')
    if 'permission denied' in txt or 'access' in txt and 'denied' in txt:
        return 'Permiso denegado al leer cookies. En Linux/macOS revisa permisos del archivo o keyring.'
    return ''


@app.route('/api/config/yt-dlp-version', methods=['GET'])
def get_yt_dlp_version():
    """Devuelve la versión instalada de yt-dlp."""
    try:
        import yt_dlp
        version = getattr(yt_dlp.version, '__version__', 'desconocida')
        return jsonify({'success': True, 'version': version})
    except ImportError:
        return jsonify({'success': False, 'error': 'yt-dlp no está instalado', 'version': None}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'version': None}), 200


@app.route('/api/config/yt-dlp-update', methods=['POST'])
def update_yt_dlp():
    """Fuerza la actualización de yt-dlp con pip install -U yt-dlp y devuelve la nueva versión."""
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-U', 'yt-dlp'],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or '').strip() or f'Código de salida: {result.returncode}'
            return jsonify({'success': False, 'error': err})
        # Obtener la versión actual después de actualizar (subproceso para ver el módulo actualizado)
        ver_proc = subprocess.run(
            [sys.executable, '-c', 'import yt_dlp; print(yt_dlp.version.__version__)'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        new_version = ver_proc.stdout.strip() if ver_proc.returncode == 0 else None
        return jsonify({
            'success': True,
            'message': 'yt-dlp actualizado correctamente',
            'version': new_version,
        })
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Tiempo de espera agotado al actualizar'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


def _env_value_for_file(key: str, value: str) -> str:
    """Formatea un valor para .env: rutas con backslashes se guardan entre comillas para evitar corrupción."""
    if not value:
        return value
    # Claves que pueden tener rutas Windows con \; sin comillas load_dotenv corrompe la ruta
    if key in ('DB_PATH', 'MUSIC_FOLDER', 'YOUTUBE_COOKIES_FILE') and '\\' in value:
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return value


@app.route('/api/config', methods=['POST'])
def save_config_endpoint():
    """Guarda la configuración."""
    data = request.json
    
    try:
        env_path = _get_config_dir() / '.env'
        lines = []
        
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        
        updated_keys = set()
        new_lines = []
        
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and '=' in stripped:
                key = stripped.split('=', 1)[0].strip()
                if key in data:
                    new_lines.append(f"{key}={_env_value_for_file(key, data[key])}\n")
                    updated_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        for key, value in data.items():
            if key not in updated_keys and value:
                if new_lines and not new_lines[-1].endswith('\n'):
                    new_lines.append('\n')
                new_lines.append(f"{key}={_env_value_for_file(key, value)}\n")
        
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        return jsonify({'success': True, 'message': 'Configuración guardada'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/config/reload', methods=['POST'])
def reload_config():
    """Recarga la configuración desde .env y reinicializa la base de datos."""
    global db, DB_PATH, MUSIC_FOLDER
    
    try:
        # Cerrar la base de datos actual
        if db:
            db.close()
        
        # Recargar variables de entorno desde el mismo .env (junto al .exe o a app.py)
        load_dotenv(_get_config_dir() / '.env', override=True)
        
        # Obtener nuevas rutas
        new_db_path = os.getenv('DB_PATH', None)
        new_music_folder = os.getenv('MUSIC_FOLDER', os.path.expanduser('~/Music'))
        
        # Actualizar variables globales
        DB_PATH = new_db_path
        MUSIC_FOLDER = new_music_folder
        
        # Reinicializar base de datos con la nueva ruta
        db = MusicDatabase(DB_PATH)
        
        print(f"🔄 Configuración recargada:")
        print(f"   📁 Carpeta de música: {MUSIC_FOLDER}")
        print(f"   🗄️  Base de datos: {DB_PATH or 'Por defecto'}")
        
        # Devolver la ruta real que está usando la BD (p. ej. resuelta/normalizada)
        db_path_display = str(db.db_path) if db else (DB_PATH or '')

        return jsonify({
            'success': True,
            'message': 'Configuración recargada',
            'config': {
                'MUSIC_FOLDER': MUSIC_FOLDER,
                'DB_PATH': db_path_display,
                'ESSENTIA_CLASSIFIER': os.getenv('ESSENTIA_CLASSIFIER', 'auto')
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/config/restart', methods=['POST'])
def restart_app():
    """Reinicia la aplicación completamente."""
    import subprocess
    
    def do_restart():
        time.sleep(1)  # Dar tiempo a que se envíe la respuesta
        
        # Detectar si estamos en ejecutable de PyInstaller
        is_frozen = getattr(sys, 'frozen', False)
        
        if is_frozen:
            # En ejecutable: reiniciar el proceso
            executable = sys.executable
            os.execv(executable, [executable] + sys.argv)
        else:
            # En desarrollo: simplemente salir (el auto-reload de Flask se encargará)
            os._exit(0)
    
    threading.Thread(target=do_restart, daemon=True).start()
    
    return jsonify({
        'success': True,
        'message': 'Reiniciando aplicación...'
    })


@app.route('/api/config/reset-db', methods=['POST'])
def reset_database():
    """Resetea la base de datos."""
    global db
    try:
        db.close()
        db_path = Path(db.db_path)
        
        if db_path.exists():
            db_path.unlink()
        
        # Re-inicializar
        db = MusicDatabase(str(db_path))
        
        return jsonify({'success': True, 'message': 'Base de datos reseteada'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/model/status', methods=['GET'])
def model_status():
    """Verifica el estado del modelo TensorFlow/CUDA."""
    if not TF_CLASSIFIER_AVAILABLE:
        return jsonify({
            'success': False,
            'available': False,
            'ready': False,
            'message': 'Clasificador TensorFlow no disponible'
        })
    
    ready = is_model_ready()
    return jsonify({
        'success': True,
        'available': True,
        'ready': ready,
        'message': 'Modelo listo' if ready else 'Modelo cargando en segundo plano...'
    })


@app.route('/api/browse', methods=['GET'])
def browse_filesystem():
    """Lista el contenido de un directorio para el explorador de archivos."""
    path = request.args.get('path', '')
    mode = request.args.get('mode', 'folder')  # 'folder' o 'file'
    # Extensiones a aceptar en modo 'file' (CSV, ej: ".txt,.json"). Si no se indica, defecto: .db/.sqlite
    extensions_arg = (request.args.get('extensions', '') or '').strip()
    if extensions_arg:
        allowed_extensions = [
            (e.strip().lower() if e.strip().startswith('.') else f".{e.strip().lower()}")
            for e in extensions_arg.split(',') if e.strip()
        ]
    else:
        allowed_extensions = ['.db', '.sqlite', '.sqlite3']

    try:
        # Si no hay ruta, usar el directorio home del usuario
        if not path:
            path = os.path.expanduser('~')
        
        # Normalizar la ruta
        path = os.path.normpath(path)
        
        # Verificar que el directorio existe
        if not os.path.exists(path):
            return jsonify({
                'success': False,
                'error': f'La ruta no existe: {path}'
            }), 404
        
        # Si es un archivo, usar su directorio padre
        if os.path.isfile(path):
            path = os.path.dirname(path)
        
        items = []
        
        # Listar contenido del directorio
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                is_dir = os.path.isdir(item_path)

                if mode == 'file' and not is_dir:
                    ext = os.path.splitext(item)[1].lower()
                    if ext not in allowed_extensions:
                        continue

                items.append({
                    'name': item,
                    'path': item_path,
                    'is_dir': is_dir
                })
        except PermissionError:
            return jsonify({
                'success': False,
                'error': f'Sin permisos para acceder a: {path}'
            }), 403
        
        # Ordenar: carpetas primero, luego archivos, ambos alfabéticamente
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        
        # Obtener directorio padre
        parent = os.path.dirname(path)
        if parent == path:  # Llegamos a la raíz
            parent = None
        
        # Obtener unidades en Windows
        drives = []
        if sys.platform == 'win32':
            import string
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append(drive)
        
        return jsonify({
            'success': True,
            'current_path': path,
            'parent': parent,
            'items': items,
            'drives': drives,
            'separator': os.sep
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


def _get_latest_yt_dlp_version_from_pypi():
    """Obtiene la última versión de yt-dlp publicada en PyPI. Devuelve None si falla."""
    try:
        from urllib.request import urlopen
        import json
        with urlopen('https://pypi.org/pypi/yt-dlp/json', timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get('info', {}).get('version')
    except Exception:
        return None


def _compare_versions(installed: str, latest: str) -> bool:
    """True si installed >= latest (está al día). False si installed < latest (hay que actualizar)."""
    def to_tuple(v):
        parts = []
        for x in (v or '0').replace('-', '.').split('.'):
            parts.append(int(x) if x.isdigit() else 0)
        return tuple(parts)
    try:
        return to_tuple(installed) >= to_tuple(latest)
    except (ValueError, TypeError):
        return (installed or '') >= (latest or '0')


def _ensure_yt_dlp_updated_at_startup():
    """Al arranque: comprueba la versión de yt-dlp y, si no está actualizada, la actualiza con pip (bloqueante)."""
    import subprocess
    installed = None
    try:
        import yt_dlp
        installed = getattr(yt_dlp.version, '__version__', None)
    except ImportError:
        print("🔄 yt-dlp no encontrado. Instalando yt-dlp...")
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '-U', 'yt-dlp'],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                print("✅ yt-dlp instalado correctamente")
            else:
                err = (result.stderr or result.stdout or '').strip() or f'Código: {result.returncode}'
                print(f"⚠️ No se pudo instalar yt-dlp: {err}")
        except subprocess.TimeoutExpired:
            print("⚠️ Tiempo de espera agotado al instalar yt-dlp")
        except Exception as e:
            print(f"⚠️ Error al instalar yt-dlp: {e}")
        return
    if not installed:
        return
    latest = _get_latest_yt_dlp_version_from_pypi()
    if not latest:
        print("🔄 No se pudo comprobar la versión en PyPI; omitiendo verificación de yt-dlp.")
        return
    if _compare_versions(installed, latest):
        print(f"✅ yt-dlp ya está al día (v{installed})")
        return
    print(f"🔄 yt-dlp desactualizado (v{installed} → v{latest}). Actualizando...")
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-U', 'yt-dlp'],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            print(f"✅ yt-dlp actualizado a v{latest}")
        else:
            err = (result.stderr or result.stdout or '').strip() or f'Código: {result.returncode}'
            print(f"⚠️ No se pudo actualizar yt-dlp: {err}")
    except subprocess.TimeoutExpired:
        print("⚠️ Tiempo de espera agotado al actualizar yt-dlp")
    except Exception as e:
        print(f"⚠️ Error al actualizar yt-dlp: {e}")


def _check_ffmpeg_at_startup():
    """Comprueba si ffmpeg está disponible y avisa por consola si no lo está."""
    ffmpeg_ok = bool(shutil.which('ffmpeg'))
    if ffmpeg_ok:
        print(f"✅ ffmpeg detectado: {shutil.which('ffmpeg')}")
        return
    print()
    print("=" * 65)
    print("⚠️  ADVERTENCIA: ffmpeg NO está instalado o no está en el PATH")
    print("   ffmpeg es NECESARIO para convertir el audio descargado a MP3.")
    print("   Sin él, TODAS las descargas fallarán.")
    print()
    if sys.platform == 'win32':
        print("   Instala ffmpeg con winget (abre una terminal como admin):")
        print("   > winget install --id Gyan.FFmpeg -e --source winget")
        print()
        print("   O descárgalo manualmente desde:")
        print("   https://www.gyan.dev/ffmpeg/builds/")
    elif sys.platform == 'darwin':
        print("   Instala ffmpeg con Homebrew:")
        print("   $ brew install ffmpeg")
    else:
        print("   Instala ffmpeg con tu gestor de paquetes:")
        print("   $ sudo apt install ffmpeg   (Debian/Ubuntu)")
        print("   $ sudo dnf install ffmpeg   (Fedora/RHEL)")
        print("   $ sudo pacman -S ffmpeg     (Arch)")
    print()
    print("   Después de instalar, REINICIA esta aplicación.")
    print("=" * 65)
    print()


if __name__ == '__main__':
    # Verificar y actualizar yt-dlp al arranque si no está al día
    _ensure_yt_dlp_updated_at_startup()

    # Comprobar si ffmpeg está disponible
    _check_ffmpeg_at_startup()

    # Crear directorio de templates si no existe
    templates_dir = Path(__file__).parent / 'templates'
    templates_dir.mkdir(exist_ok=True)
    
    # Precargar modelo TensorFlow/CUDA en background (no bloquea el arranque)
    if TF_CLASSIFIER_AVAILABLE:
        print("🔄 Iniciando precarga del modelo TensorFlow/CUDA en segundo plano...")
        print("   (Flask arrancará inmediatamente, el modelo se cargará en paralelo)")
        preload_model_async()
    
    # Abrir navegador automáticamente
    # - En ejecutable de PyInstaller: siempre abrir (sys.frozen está definido)
    # - En desarrollo: solo en el proceso principal (no en el recargado por Werkzeug)
    is_frozen = getattr(sys, 'frozen', False)
    is_main_process = os.environ.get('WERKZEUG_RUN_MAIN') != 'true'
    
    if is_frozen or is_main_process:
        def open_browser():
            time.sleep(1.5)
            # Intentar obtener la IP de la red (localhost/127.0.0.1 a veces falla en Windows)
            import socket
            try:
                # Conectar a un servidor externo para obtener la IP local
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                local_ip = "127.0.0.1"
            
            url = f'http://{local_ip}:5001'
            print(f"📱 Abriendo navegador en {url}")
            webbrowser.open(url)
        
        threading.Thread(target=open_browser, daemon=True).start()
    
    # Detectar si estamos ejecutando como ejecutable de PyInstaller
    is_frozen = getattr(sys, 'frozen', False)
    
    # En ejecutable, desactivar debug y auto-reload
    # En desarrollo, mantener debug activado
    debug_mode = not is_frozen
    use_reloader = not is_frozen
    
    print("🚀 Iniciando servidor Flask...")
    print("🌐 Servidor accesible desde todas las interfaces de red (0.0.0.0:5001)")
    print("💡 Presiona Ctrl+C para detener el servidor")
    if use_reloader:
        print("🔄 Auto-reload activado: el servidor se reiniciará al cambiar archivos Python")
    
    app.run(debug=debug_mode, host='0.0.0.0', port=5001, use_reloader=use_reloader)
