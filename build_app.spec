# -*- mode: python ; coding: utf-8 -*-
"""
Archivo de configuración de PyInstaller para crear ejecutable de la aplicación web Flask.
"""

import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

# Directorio del proyecto (PyInstaller inyecta SPECPATH; no usa __file__ aquí)
spec_dir = SPECPATH

# Forzar inclusión de python-dotenv (en Windows a veces no se detecta)
_hidden_dotenv = collect_submodules('dotenv')

# Añadir SPECPATH al sys.path para que PyInstaller encuentre los módulos locales
# (necesario en Windows con rutas con espacios)
if spec_dir not in sys.path:
    sys.path.insert(0, spec_dir)

a = Analysis(
    # Incluir todos los scripts locales en el análisis
    ['app.py', 'database.py', 'download_youtube.py', 'download_quick.py', 'query_db.py', 'genre_classifier_tf.py'],
    pathex=[spec_dir],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('youtube_cookies.txt', '.'),
        ('env_example.txt', '.'),
        ('essentia', 'essentia'),
        ('helpers', 'helpers'),
    ],
    hiddenimports=[
        'dotenv',
        'dotenv.load_dotenv',
    ] + _hidden_dotenv + [
        'yt_dlp',
        'mutagen',
        'mutagen.mp3',
        'mutagen.id3',
        'requests',
        'database',
        'download_youtube',
        'download_quick',
        'query_db',
        'sqlite3',
        'urllib',
        'urllib.parse',
        'urllib.request',
        'flask',
        'flask_cors',
        'werkzeug',
        'jinja2',
        'genre_classifier_tf',
        'numpy',
        'helpers.extract_genre_tf',
        'webbrowser',
        'threading',
        'uuid',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DJ_CUCHI_app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Con consola para poder lanzar desde línea de comandos
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
