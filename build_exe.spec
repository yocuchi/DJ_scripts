# -*- mode: python ; coding: utf-8 -*-
"""
Archivo de configuración de PyInstaller para crear ejecutable de Windows.
"""

block_cipher = None

a = Analysis(
    ['download_youtube.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('youtube_cookies.txt', '.'),  # Incluir cookies si existen
        ('env_example.txt', '.'),  # Incluir ejemplo de .env
    ],
    hiddenimports=[
        'yt_dlp',
        'mutagen',
        'mutagen.mp3',
        'mutagen.id3',
        'dotenv',
        'requests',
        'database',
        'sqlite3',
        'urllib',
        'urllib.parse',
        'urllib.request',
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
    name='DJ_CUCHIDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Mantener consola para ver mensajes
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Puedes añadir un icono .ico aquí si lo deseas
)

