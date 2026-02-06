#!/usr/bin/env python3
"""
Script de prueba para depurar la descarga de un video de YouTube.
Uso: python test_download_video.py [URL]
Ejemplo: python test_download_video.py https://youtu.be/O7NyOtAJPb4
"""

import sys
import os

# Asegurar que el proyecto está en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Cargar .env para cookies y rutas
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

def log(msg):
    print(msg)

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else 'https://youtu.be/O7NyOtAJPb4'
    log(f"URL de prueba: {url}")
    log("")

    import yt_dlp
    version = getattr(yt_dlp.version, '__version__', '?')
    log(f"yt-dlp versión: {version}")
    log("")

    # Cookies (opcional)
    cookies_file = os.getenv('YOUTUBE_COOKIES') or None
    if not cookies_file:
        default_cookies = Path(__file__).parent / 'youtube_cookies.txt'
        if default_cookies.exists():
            cookies_file = str(default_cookies)
    if cookies_file:
        log(f"Cookies: {cookies_file}")
    else:
        log("Cookies: no configuradas")
    log("")

    # --- 1) Listar formatos disponibles (diagnóstico) ---
    log("=== 1) Listando formatos disponibles (yt-dlp --list-formats) ===")
    import subprocess
    cmd = [sys.executable, '-m', 'yt_dlp', '--list-formats', '--no-warnings', url]
    if cookies_file:
        cmd.extend(['--cookies', cookies_file])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            log(result.stdout[:2000] if len(result.stdout) > 2000 else result.stdout)
        else:
            log(f"Error (code {result.returncode}):")
            log(result.stderr or result.stdout or "(vacío)")
    except Exception as e:
        log(f"Excepción: {e}")
    log("")

    # --- 2) Extracción plana (extract_flat) SIN formato ---
    log("=== 2) extract_info con extract_flat=True (sin selector de formato) ===")
    opts_flat = {
        'quiet': False,
        'no_warnings': False,
        'extract_flat': True,
        'skip_download': True,
        'ignoreerrors': True,
    }
    if cookies_file:
        opts_flat['cookiefile'] = cookies_file
    try:
        with yt_dlp.YoutubeDL(opts_flat) as ydl:
            info = ydl.extract_info(url, download=False)
        if info and info.get('id') and info.get('title'):
            log(f"  OK - id: {info.get('id')}, title: {info.get('title')}")
        else:
            log(f"  Resultado: {info}")
    except Exception as e:
        log(f"  Excepción: {type(e).__name__}: {e}")
    log("")

    # --- 3) Extracción completa con formato bestaudio/best/worst ---
    log("=== 3) extract_info con format='bestaudio/best/worst' ===")
    opts_full = {
        'quiet': False,
        'no_warnings': False,
        'extract_flat': False,
        'skip_download': True,
        'ignoreerrors': True,
        'format': 'bestaudio/best/worst',
    }
    if cookies_file:
        opts_full['cookiefile'] = cookies_file
    try:
        with yt_dlp.YoutubeDL(opts_full) as ydl:
            info = ydl.extract_info(url, download=False)
        if info:
            log(f"  OK - id: {info.get('id')}, title: {info.get('title')}, duration: {info.get('duration')}")
        else:
            log("  Resultado: None")
    except Exception as e:
        log(f"  Excepción: {type(e).__name__}: {e}")
    log("")

    # --- 4) get_video_info del proyecto ---
    log("=== 4) get_video_info() del proyecto ===")
    try:
        from download_youtube import get_video_info
        info = get_video_info(url)
        if info and info.get('id'):
            log(f"  OK - id: {info.get('id')}, title: {info.get('title')}")
        else:
            log(f"  Resultado: {info}")
    except Exception as e:
        log(f"  Excepción: {type(e).__name__}: {e}")
    log("")

    # --- 5) Descarga real (opcional, solo si --download) ---
    if '--download' in sys.argv:
        log("=== 5) download_audio() (descarga real a /tmp) ===")
        try:
            from download_youtube import get_video_info, download_audio
            info = get_video_info(url)
            if not info:
                log("  No se pudo obtener info, abortando descarga")
            else:
                out = f"/tmp/test_ytdlp_{info.get('id', 'x')}"
                ok = download_audio(url, out, info or {})
                log(f"  download_audio: {'OK' if ok else 'FALLO'}")
        except Exception as e:
            log(f"  Excepción: {type(e).__name__}: {e}")
    else:
        log("(Omitiendo descarga real. Usa: python test_download_video.py <URL> --download)")

if __name__ == '__main__':
    main()
