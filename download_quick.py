#!/usr/bin/env python3
"""
Script rápido para descargar canciones de YouTube a MP3.
Versión simplificada del script principal.
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
    # Remover caracteres no permitidos
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Reemplazar espacios múltiples por uno solo
    filename = re.sub(r'\s+', ' ', filename)
    # Limitar longitud a 100 caracteres para evitar nombres demasiado largos
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
            
            # Formatear tamaño
            def format_size(size):
                for unit in ['B', 'KiB', 'MiB', 'GiB']:
                    if size < 1024.0:
                        return f"{size:.2f}{unit}"
                    size /= 1024.0
                return f"{size:.2f}TiB"
            
            # Formatear velocidad
            speed_str = format_size(speed) + '/s' if speed > 0 else '?'
            
            # Formatear ETA
            if eta:
                eta_min = eta // 60
                eta_sec = eta % 60
                eta_str = f"{eta_min:02d}:{eta_sec:02d}"
            else:
                eta_str = "??:??"
            
            # Actualizar línea (usar \r para sobrescribir)
            progress_line = f"\r📥 Descargando: {percent:.1f}% de {format_size(total)} a {speed_str} (ETA: {eta_str})"
            sys.stdout.write(progress_line)
            sys.stdout.flush()
    elif d['status'] == 'finished':
        # Limpiar la línea de progreso y mostrar mensaje final
        sys.stdout.write('\r' + ' ' * 80 + '\r')  # Limpiar línea
        sys.stdout.flush()


def download_quick(url: str):
    """Descarga rápida sin metadatos avanzados."""
    music_path = Path(MUSIC_FOLDER)
    music_path.mkdir(parents=True, exist_ok=True)
    
    # Obtener información del video primero para sanitizar el título
    try:
        info_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'video')
            sanitized_title = sanitize_filename(title)
    except Exception as e:
        print(f"⚠️  Advertencia: No se pudo obtener el título del video: {e}")
        sanitized_title = 'video'
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(music_path / f'{sanitized_title}.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
        'progress_hooks': [progress_hook],
        'quiet': False,
        'no_warnings': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"Descargando: {url}")
            ydl.download([url])
            print("✅ Descarga completada!")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python download_quick.py <URL_YOUTUBE>")
        sys.exit(1)
    
    download_quick(sys.argv[1])

