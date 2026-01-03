#!/usr/bin/env python3
"""
Script rápido para descargar canciones de YouTube a MP3.
Versión simplificada del script principal.
"""

import os
import sys
from pathlib import Path
import yt_dlp
from dotenv import load_dotenv

load_dotenv()

MUSIC_FOLDER = os.getenv('MUSIC_FOLDER', os.path.expanduser('~/Music'))


def download_quick(url: str):
    """Descarga rápida sin metadatos avanzados."""
    music_path = Path(MUSIC_FOLDER)
    music_path.mkdir(parents=True, exist_ok=True)
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(music_path / '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
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

