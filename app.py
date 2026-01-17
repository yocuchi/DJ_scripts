#!/usr/bin/env python3
"""
Aplicación web Flask para el gestor de descarga de música.
Interfaz web moderna con soporte completo para videos embebidos de YouTube.
"""

import os
import re
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote
from dotenv import load_dotenv

# Importar Flask
try:
    from flask import Flask, render_template, request, jsonify, send_file
    from flask_cors import CORS
except ImportError:
    print("❌ Flask no está instalado. Instala con: pip install flask flask-cors")
    exit(1)

# Importar módulos del proyecto
from database import MusicDatabase
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

# Cargar variables de entorno
load_dotenv()

# Inicializar base de datos
DB_PATH = os.getenv('DB_PATH', None)
db = MusicDatabase(DB_PATH)
MUSIC_FOLDER = os.getenv('MUSIC_FOLDER', os.path.expanduser('~/Music'))

# Crear aplicación Flask
app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.urandom(24)

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
    print(f"[{time.strftime('%H:%M:%S')}] 📄 Petición GET / - Sirviendo página principal")
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
        print(f"[{time.strftime('%H:%M:%S')}] 🔍 Llamando a get_liked_videos_from_url...")
        liked_videos = get_liked_videos_from_url(playlist_url, limit=limit)
        print(f"[{time.strftime('%H:%M:%S')}] ✅ get_liked_videos_from_url completado: {len(liked_videos)} videos obtenidos")
        
        videos_data = []
        print(f"[{time.strftime('%H:%M:%S')}] 🔄 Procesando {len(liked_videos)} videos...")
        for idx, video in enumerate(liked_videos, 1):
            print(f"[{time.strftime('%H:%M:%S')}]   [{idx}/{len(liked_videos)}] Procesando video: {video.get('id', 'unknown')} - {video.get('title', 'Unknown')[:50]}")
            video_id = video['id']
            url = video['url']
            title = video['title']
            
            # Verificar si está rechazada o descargada
            print(f"      → Verificando si está rechazada o descargada...")
            is_rejected = is_rejected_video(video_id)
            existing_song = check_file_exists(video_id=video_id)
            
            if hide_ignored and (is_rejected or existing_song):
                print(f"      → ⏭️  Omitido (rechazado o descargado)")
                continue
            
            # Obtener información del video desde caché o API
            print(f"      → Obteniendo información del video...")
            video_info_start = time.time()
            video_info = db.get_cached_video_info(video_id)
            if not video_info:
                print(f"      → No hay caché, obteniendo desde API...")
                try:
                    video_info = get_video_info(url)
                    video_info_elapsed = time.time() - video_info_start
                    if video_info:
                        db.set_cached_video_info(video_id, video_info)
                        print(f"      → ✅ Información obtenida y guardada en caché ({video_info_elapsed:.2f}s)")
                    else:
                        print(f"      → ⚠️  No se obtuvo información del video ({video_info_elapsed:.2f}s)")
                except Exception as e:
                    video_info_elapsed = time.time() - video_info_start
                    print(f"      → ⚠️  Error obteniendo info después de {video_info_elapsed:.2f}s: {e}")
                    video_info = {}
            else:
                video_info_elapsed = time.time() - video_info_start
                print(f"      → ✅ Usando información de caché ({video_info_elapsed:.3f}s)")
            
            # Obtener metadatos desde caché o extraer
            print(f"      → Obteniendo metadatos...")
            metadata = db.get_cached_metadata(video_id)
            if not metadata and video_info:
                print(f"      → No hay caché de metadatos, extrayendo...")
                try:
                    title_from_info = video_info.get('title', title)
                    description = video_info.get('description', '')
                    metadata = extract_metadata_from_title(title_from_info, description, video_info)
                    if metadata:
                        db.set_cached_metadata(video_id, metadata)
                        print(f"      → ✅ Metadatos extraídos y guardados")
                except Exception as e:
                    print(f"      → ⚠️  Error extrayendo metadatos: {e}")
                    metadata = {}
            else:
                print(f"      → ✅ Usando metadatos de caché")
            
            # Obtener género desde caché o detectar
            genre = db.get_cached_genre(video_id)
            if not genre:
                genre = metadata.get('genre', 'Sin Clasificar')
            
            videos_data.append({
                'id': video_id,
                'title': title,
                'url': url,
                'thumbnail': video_info.get('thumbnail', '') if video_info else '',
                'genre': genre,
                'artist': metadata.get('artist', 'Desconocido') if metadata else 'Desconocido',
                'is_rejected': is_rejected,
                'is_downloaded': existing_song is not None,
                'is_downloading': video_id in download_status and download_status[video_id].get('status') == 'downloading'
            })
            print(f"      → ✅ Video agregado a la lista")
        
        elapsed = time.time() - start_time
        print(f"[{time.strftime('%H:%M:%S')}] ✅ GET /api/playlist - Completado en {elapsed:.2f}s")
        print(f"    Videos procesados: {len(videos_data)} de {len(liked_videos)} obtenidos")
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
            download_status[video_id] = {'status': 'downloading', 'progress': 0}
            download_logs[video_id] = []
            
            # Obtener información del video
            video_info = get_video_info(video_url)
            if not video_info:
                download_status[video_id] = {'status': 'error', 'error': 'No se pudo obtener información del video'}
                return
            
            title = video_info.get('title', '')
            description = video_info.get('description', '')
            
            # Extraer metadatos
            metadata = extract_metadata_from_title(title, description, video_info)
            
            # Detectar género si no está
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
            
            # Obtener carpeta de salida
            output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))
            
            # Crear nombre de archivo
            if metadata.get('artist'):
                filename = f"{metadata['artist']} - {metadata['title']}"
            else:
                filename = metadata.get('title', title)
            
            filename = sanitize_filename(filename)
            output_path = output_folder / filename
            
            # Descargar
            if download_audio(video_url, str(output_path), metadata):
                mp3_file = Path(str(output_path) + '.mp3')
                if not mp3_file.exists():
                    mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
                    if mp3_files:
                        mp3_file = mp3_files[0]
                
                # Verificar y normalizar volumen
                check_and_normalize_audio(str(mp3_file))
                
                # Añadir metadatos ID3
                add_id3_tags(str(mp3_file), metadata, video_info)
                
                # Registrar en base de datos
                register_song_in_db(video_id, video_url, mp3_file, metadata, video_info, download_source='playlist')
                
                download_status[video_id] = {'status': 'completed', 'file': str(mp3_file)}
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
        logs = download_logs.get(task_id, [])
        return jsonify({
            'status': status,
            'logs': logs
        })
    
    # Si no, intentar como task_id de descarga directa
    task_status = direct_download_tasks.get(task_id, {})
    if task_status:
        return jsonify({
            'status': task_status.get('status', 'idle'),
            'error': task_status.get('error'),
            'file': task_status.get('file')
        })
    
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
            
            video_info = get_video_info(url)
            if not video_info:
                direct_download_tasks[task_id] = {'status': 'error', 'error': 'No se pudo obtener información del video'}
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
                direct_download_tasks[task_id] = {'status': 'error', 'error': 'Error en la descarga'}
                
        except Exception as e:
            direct_download_tasks[task_id] = {'status': 'error', 'error': str(e)}
            import traceback
            if video_id:
                download_logs[video_id].append(traceback.format_exc())
    
    threading.Thread(target=download_thread, daemon=True).start()
    return jsonify({'success': True, 'task_id': task_id, 'message': 'Descarga iniciada'})


@app.route('/api/download/quick', methods=['POST'])
def download_quick_endpoint():
    """Descarga rápida sin metadatos avanzados."""
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'success': False, 'error': 'Faltan parámetros'}), 400
    
    def quick_download_thread():
        try:
            download_quick(url)
        except Exception as e:
            print(f"Error en descarga rápida: {e}")
    
    threading.Thread(target=quick_download_thread, daemon=True).start()
    return jsonify({'success': True, 'message': 'Descarga rápida iniciada'})


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
        # Usar la ruta absoluta del directorio del script
        script_dir = Path(__file__).parent
        env_path = script_dir / '.env'
        
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
                                value = value[1:-1]
                            elif value.startswith("'") and value.endswith("'"):
                                value = value[1:-1]
                            config[key] = value
        
        return jsonify({
            'success': True,
            'config': {
                'MUSIC_FOLDER': config.get('MUSIC_FOLDER', ''),
                'DB_PATH': config.get('DB_PATH', ''),
                'LASTFM_API_KEY': config.get('LASTFM_API_KEY', '')
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/config', methods=['POST'])
def save_config_endpoint():
    """Guarda la configuración."""
    data = request.json
    
    try:
        # Usar la ruta absoluta del directorio del script
        script_dir = Path(__file__).parent
        env_path = script_dir / '.env'
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
                    new_lines.append(f"{key}={data[key]}\n")
                    updated_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        for key, value in data.items():
            if key not in updated_keys and value:
                if new_lines and not new_lines[-1].endswith('\n'):
                    new_lines.append('\n')
                new_lines.append(f"{key}={value}\n")
        
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        return jsonify({'success': True, 'message': 'Configuración guardada'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


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


if __name__ == '__main__':
    # Crear directorio de templates si no existe
    templates_dir = Path(__file__).parent / 'templates'
    templates_dir.mkdir(exist_ok=True)
    
    # Precargar modelo TensorFlow/CUDA en background (no bloquea el arranque)
    if TF_CLASSIFIER_AVAILABLE:
        print("🔄 Iniciando precarga del modelo TensorFlow/CUDA en segundo plano...")
        print("   (Flask arrancará inmediatamente, el modelo se cargará en paralelo)")
        preload_model_async()
    
    # Abrir navegador automáticamente solo en el proceso principal
    # (no en el proceso recargado por Werkzeug)
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        def open_browser():
            time.sleep(1.5)
            webbrowser.open('http://127.0.0.1:5000')
        
        threading.Thread(target=open_browser, daemon=True).start()
    
    print("🚀 Iniciando servidor Flask...")
    print("📱 Abriendo navegador en http://127.0.0.1:5000")
    print("🌐 Servidor accesible desde todas las interfaces de red (0.0.0.0:5000)")
    print("💡 Presiona Ctrl+C para detener el servidor")
    print("🔄 Auto-reload activado: el servidor se reiniciará al cambiar archivos Python")
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=True)
