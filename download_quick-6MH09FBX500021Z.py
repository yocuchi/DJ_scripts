#!/usr/bin/env python3
"""
Script rápido para descargar canciones de YouTube a MP3.
Versión simplificada del script principal.
Usa la misma lógica robusta que la app (get_video_info + cascada de formatos).
"""

import os
import sys
import re
from pathlib import Path
import yt_dlp
from dotenv import load_dotenv

load_dotenv()

MUSIC_FOLDER = os.getenv('MUSIC_FOLDER', os.path.expanduser('~/Music'))


def sanitize_filename(filename: str) -> str:
    """Limpia el nombre de archivo para que sea válido en el sistema de archivos."""
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = re.sub(r'\s+', ' ', filename)
    if len(filename) > 100:
        filename = filename[:100]
    return filename.strip()


def progress_hook(d):
    """Hook de progreso que actualiza una sola línea."""
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        downloaded = d.get('downloaded_bytes', 0)
        if total > 0:
            percent = (downloaded / total) * 100
            speed = d.get('speed', 0)
            eta = d.get('eta', 0)
            def format_size(size):
                for unit in ['B', 'KiB', 'MiB', 'GiB']:
                    if size < 1024.0:
                        return f"{size:.2f}{unit}"
                    size /= 1024.0
                return f"{size:.2f}TiB"
            speed_str = format_size(speed) + '/s' if speed > 0 else '?'
            eta_str = f"{eta // 60:02d}:{eta % 60:02d}" if eta else "??:??"
            progress_line = f"\r📥 Descargando: {percent:.1f}% de {format_size(total)} a {speed_str} (ETA: {eta_str})"
            sys.stdout.write(progress_line)
            sys.stdout.flush()
    elif d['status'] == 'finished':
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        sys.stdout.flush()


def download_quick(url: str):
    """Descarga rápida sin metadatos avanzados. Usa get_video_info y cascada de formatos como la app."""
    music_path = Path(MUSIC_FOLDER)
    music_path.mkdir(parents=True, exist_ok=True)

    # Obtener título con la misma lógica robusta que la app (extract_flat primero, cookies, etc.)
    try:
        from download_youtube import get_video_info
        info = get_video_info(url)
        title = info.get('title', 'video') if info else 'video'
        sanitized_title = sanitize_filename(title)
    except Exception as e:
        print(f"⚠️  Advertencia: No se pudo obtener el título del video: {e}")
        sanitized_title = 'video'

    # Cascada de formatos (igual que download_audio) para vídeos con formatos limitados
    from download_youtube import get_cookies_file
    cookies_file = get_cookies_file()
    format_attempts = [
        'bestaudio/best/worst',
        'bestaudio/best',
        'best/worst',
        'best[height<=720]/best',
        'worst[ext=mp4]/worst',
    ]
    outtmpl = str(music_path / f'{sanitized_title}.%(ext)s')
    base_opts = {
        'outtmpl': outtmpl,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
        'progress_hooks': [progress_hook],
        'quiet': False,
        'no_warnings': False,
    }
    cookie_attempts = [cookies_file] if cookies_file else [None]
    if cookies_file:
        cookie_attempts.append(None)

    last_error = None
    for cookie_file in cookie_attempts:
        for i, fmt in enumerate(format_attempts):
            ydl_opts = {**base_opts, 'format': fmt}
            if cookie_file:
                ydl_opts['cookiefile'] = cookie_file
            if i > 0:
                print(f"⚠️  Intentando formato alternativo ({i + 1}/{len(format_attempts)}): {fmt}")
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    print(f"Descargando: {url}")
                    ydl.download([url])
                print("✅ Descarga completada!")
                return
            except Exception as e:
                last_error = e
                if 'Requested format is not available' in str(e) or 'Only images are available' in str(e):
                    continue
                if 'Video unavailable' in str(e) or 'Private video' in str(e):
                    break
                continue

    print(f"❌ Error: {last_error}")
    sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python download_quick.py <URL_YOUTUBE>")
        sys.exit(1)
    
    download_quick(sys.argv[1])

