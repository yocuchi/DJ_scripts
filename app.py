#!/usr/bin/env python3
"""
Aplicación web Flask para el gestor de descarga de música.
Interfaz web moderna con soporte completo para videos embebidos de YouTube.
"""

import os
import sys
import re
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
    check_and_normalize_audio,
    get_liked_videos_from_url, process_imported_mp3
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
        return True

# Aplicar filtro al logger de Werkzeug
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.addFilter(StatusPollingFilter())

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
    
    try:
        videos_data = []
        batch_size = limit * 5  # Tamaño de cada lote a obtener
        start_index = 1  # Índice inicial (1-based)
        max_batches = 10  # Máximo de lotes a intentar (para evitar bucles infinitos)
        batch_count = 0
        skipped_count = 0  # Contador de canciones omitidas
        
        print(f"[{time.strftime('%H:%M:%S')}] 🔄 Procesando playlist en lotes hasta encontrar {limit} videos válidos...")
        
        # Si hide_ignored está activado, obtener videos en lotes hasta tener suficientes válidos
        # Si no está activado, solo obtener un lote
        while len(videos_data) < limit and batch_count < max_batches:
            batch_count += 1
            current_batch_size = batch_size if hide_ignored else limit
            
            print(f"[{time.strftime('%H:%M:%S')}] 🔍 Lote {batch_count}: Obteniendo videos desde índice {start_index} (hasta {start_index + current_batch_size - 1})...")
            liked_videos = get_liked_videos_from_url(playlist_url, limit=current_batch_size, start_index=start_index)
            
            if not liked_videos:
                print(f"    ⚠️  No se obtuvieron más videos de la playlist")
                break
            
            print(f"    ✅ Obtenidos {len(liked_videos)} videos en este lote")
            
            # Procesar los videos del lote actual
            for idx, video in enumerate(liked_videos, 1):
                # Si ya tenemos suficientes videos y hide_ignored está activado, parar
                if hide_ignored and len(videos_data) >= limit:
                    print(f"    ✅ Ya se encontraron {limit} videos válidos, deteniendo procesamiento")
                    break
                
                video_id = video['id']
                url = video['url']
                title = video['title']
                
                # PRIMERO: Verificar si está rechazada o descargada (verificación rápida)
                is_rejected = is_rejected_video(video_id)
                existing_song = check_file_exists(video_id=video_id)
                
                if hide_ignored and (is_rejected or existing_song):
                    skipped_count += 1
                    reason = "ya descargada" if existing_song else "ignorada"
                    print(f"[{time.strftime('%H:%M:%S')}] ⏭️  [{skipped_count}] Omitida ({reason}): {title[:70]}")
                    continue
                
                print(f"[{time.strftime('%H:%M:%S')}]   [{idx}/{len(liked_videos)}] Procesando: {title[:70]}")
                
                # Obtener información del video desde caché o API
                video_info_start = time.time()
                video_info = db.get_cached_video_info(video_id)
                if not video_info:
                    try:
                        video_info = get_video_info(url)
                        video_info_elapsed = time.time() - video_info_start
                        if video_info:
                            db.set_cached_video_info(video_id, video_info)
                            print(f"      → ✅ Info obtenida desde API ({video_info_elapsed:.2f}s)")
                        else:
                            print(f"      → ⚠️  No se obtuvo información del video")
                    except Exception as e:
                        print(f"      → ⚠️  Error obteniendo info: {e}")
                        video_info = {}
                else:
                    print(f"      → ✅ Info desde caché")
                
                # Obtener metadatos desde caché o extraer
                metadata = db.get_cached_metadata(video_id)
                if not metadata and video_info:
                    try:
                        title_from_info = video_info.get('title', title)
                        description = video_info.get('description', '')
                        metadata = extract_metadata_from_title(title_from_info, description, video_info)
                        if metadata:
                            db.set_cached_metadata(video_id, metadata)
                    except Exception as e:
                        print(f"      → ⚠️  Error extrayendo metadatos: {e}")
                        metadata = {}
                
                # Asegurar que metadata nunca sea None
                if metadata is None:
                    metadata = {}
                
                # Obtener género desde caché o detectar
                genre = db.get_cached_genre(video_id)
                if not genre:
                    genre = metadata.get('genre', 'Sin Clasificar') if metadata else 'Sin Clasificar'
                
                # Obtener información de progreso si está descargando
                is_downloading = video_id in download_status and download_status[video_id].get('status') == 'downloading'
                progress = 0
                if is_downloading:
                    progress = download_status[video_id].get('progress', 0)
                
                videos_data.append({
                    'id': video_id,
                    'title': title,
                    'url': url,
                    'thumbnail': video_info.get('thumbnail', '') if video_info else '',
                    'genre': genre,
                    'artist': metadata.get('artist', 'Desconocido') if metadata else 'Desconocido',
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
        return jsonify({
            'success': True,
            'videos': videos_data,
            'count': len(videos_data)
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
            
            # Callback para actualizar el progreso
            def update_progress(d):
                status = d.get('status', '')
                if status == 'downloading':
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    if total and total > 0:
                        # Calcular progreso entre 20% y 80% (la descarga real)
                        # 20% es el inicio de la descarga, 80% es cuando termina
                        download_progress = int((downloaded / total) * 60)  # 0-60% de la descarga
                        progress = 20 + download_progress  # 20% a 80%
                        download_status[video_id].update({
                            'status': 'downloading',
                            'progress': min(progress, 80),  # Máximo 80% durante la descarga
                            'downloaded_bytes': downloaded,
                            'total_bytes': total,
                            'speed': d.get('speed', 0),
                            'eta': d.get('eta', 0)
                        })
                    else:
                        download_status[video_id].update({
                            'status': 'downloading',
                            'downloaded_bytes': downloaded,
                            'total_bytes': 0
                        })
                elif status == 'finished':
                    # Cuando termina la descarga, ya estamos en 80%
                    download_status[video_id]['progress'] = 80
            
            # Obtener información del video
            download_status[video_id]['progress'] = 5  # 5% - Obteniendo info
            video_info = get_video_info(video_url)
            if not video_info:
                download_status[video_id] = {'status': 'error', 'error': 'No se pudo obtener información del video'}
                return
            
            title = video_info.get('title', '')
            description = video_info.get('description', '')
            
            # Extraer metadatos
            download_status[video_id]['progress'] = 10  # 10% - Extrayendo metadatos
            metadata = extract_metadata_from_title(title, description, video_info)
            
            # Detectar género si no está
            if not metadata.get('genre'):
                download_status[video_id]['progress'] = 15  # 15% - Detectando género
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
            
            # Obtener carpeta de salida
            output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))
            
            # Crear nombre de archivo
            if metadata.get('artist'):
                filename = f"{metadata['artist']} - {metadata['title']}"
            else:
                filename = metadata.get('title', title)
            
            filename = sanitize_filename(filename)
            output_path = output_folder / filename
            
            # Descargar (el progreso se actualizará automáticamente con el callback)
            download_status[video_id]['progress'] = 20  # 20% - Iniciando descarga
            if download_audio(video_url, str(output_path), metadata, progress_callback=update_progress):
                download_status[video_id]['progress'] = 80  # 80% - Descarga completada, procesando
                mp3_file = Path(str(output_path) + '.mp3')
                if not mp3_file.exists():
                    mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
                    if mp3_files:
                        mp3_file = mp3_files[0]
                
                # Verificar y normalizar volumen
                download_status[video_id]['progress'] = 85  # 85% - Normalizando audio
                check_and_normalize_audio(str(mp3_file))
                
                # Añadir metadatos ID3
                download_status[video_id]['progress'] = 90  # 90% - Añadiendo metadatos
                add_id3_tags(str(mp3_file), metadata, video_info)
                
                # Registrar en base de datos
                download_status[video_id]['progress'] = 95  # 95% - Registrando en BD
                register_song_in_db(video_id, video_url, mp3_file, metadata, video_info, download_source='playlist')
                
                download_status[video_id] = {'status': 'completed', 'progress': 100, 'file': str(mp3_file)}
            else:
                download_status[video_id] = {'status': 'error', 'error': 'Error en la descarga'}
                
        except Exception as e:
            download_status[video_id] = {'status': 'error', 'error': str(e)}
            import traceback
            download_logs[video_id].append(traceback.format_exc())
    
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
                
                check_and_normalize_audio(str(mp3_file))
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


@app.route('/api/database/songs', methods=['GET'])
def get_database_songs():
    """Obtiene canciones de la base de datos."""
    try:
        search = request.args.get('search', '')
        show_ignored = request.args.get('show_ignored', 'false').lower() == 'true'
        try:
            limit = int(request.args.get('limit', 100))
        except (ValueError, TypeError):
            limit = 100
        
        # Verificar que la base de datos esté inicializada
        if db is None:
            return jsonify({'success': False, 'error': 'Base de datos no inicializada'}), 500
        
        # Obtener todas las canciones
        songs = db.get_all_songs(limit=limit)
        
        # Convertir a formato serializable (asegurar que todos los valores sean JSON-serializables)
        serializable_songs = []
        for song in songs:
            serializable_song = {}
            for key, value in song.items():
                # Convertir valores None, datetime, etc. a strings
                if value is None:
                    serializable_song[key] = None
                elif isinstance(value, (int, float, str, bool)):
                    serializable_song[key] = value
                else:
                    # Convertir cualquier otro tipo a string
                    serializable_song[key] = str(value)
            serializable_songs.append(serializable_song)
        
        # Filtrar por búsqueda
        if search:
            search_lower = search.lower()
            serializable_songs = [s for s in serializable_songs if 
                    search_lower in (s.get('title') or '').lower() or
                    search_lower in (s.get('artist') or '').lower() or
                    search_lower in (s.get('genre') or '').lower()]
        
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
    
    def import_thread():
        try:
            mp3_files = list(folder_path.glob('*.mp3'))
            import_logs[task_id].append(f"Encontrados {len(mp3_files)} archivos MP3")
            
            for mp3_file in mp3_files:
                try:
                    import_logs[task_id].append(f"Procesando: {mp3_file.name}")
                    result = process_imported_mp3(
                        mp3_file,
                        MUSIC_FOLDER,
                        log_callback=lambda msg: import_logs[task_id].append(msg)
                    )
                    if result:
                        import_logs[task_id].append(f"✅ Procesado: {mp3_file.name}")
                    else:
                        import_logs[task_id].append(f"⚠️ Ya existe o error: {mp3_file.name}")
                except Exception as e:
                    import_logs[task_id].append(f"❌ Error procesando {mp3_file.name}: {str(e)}")
            
            import_status[task_id] = {'status': 'completed', 'count': len(mp3_files)}
        except Exception as e:
            import_status[task_id] = {'status': 'error', 'error': str(e)}
            import traceback
            import_logs[task_id].append(traceback.format_exc())
    
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
                'LASTFM_API_KEY': config.get('LASTFM_API_KEY', '')
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


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
    # DB_PATH y MUSIC_FOLDER pueden tener rutas Windows con \; sin comillas load_dotenv corrompe la ruta
    if key in ('DB_PATH', 'MUSIC_FOLDER') and '\\' in value:
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
                'DB_PATH': db_path_display
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
                
                # En modo 'file', mostrar archivos .db o .sqlite también
                if mode == 'file' and not is_dir:
                    ext = os.path.splitext(item)[1].lower()
                    if ext not in ['.db', '.sqlite', '.sqlite3']:
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


def _update_yt_dlp_in_background():
    """Intenta actualizar yt-dlp a la última versión en segundo plano (no bloquea el arranque)."""
    import subprocess
    try:
        print("🔄 Comprobando actualización de yt-dlp...")
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-U', 'yt-dlp'],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            if 'Successfully installed' in (result.stdout or '') or 'already up-to-date' in (result.stdout or ''):
                print("✅ yt-dlp actualizado o ya está al día")
            else:
                print("✅ yt-dlp: comprobación completada")
        else:
            # No mostrar error al usuario: puede ser red, permisos, etc.
            pass
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass


if __name__ == '__main__':
    # Crear directorio de templates si no existe
    templates_dir = Path(__file__).parent / 'templates'
    templates_dir.mkdir(exist_ok=True)
    
    # Actualizar yt-dlp en segundo plano para estar siempre al día con YouTube
    threading.Thread(target=_update_yt_dlp_in_background, daemon=True).start()
    
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
