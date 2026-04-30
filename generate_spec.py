"""
Genera el archivo .spec de PyInstaller para el script y plataforma indicados.
Uso: python generate_spec.py <script_name> <os_name>
"""
import sys

script_name = sys.argv[1]
os_name = sys.argv[2]

script_file = f"{script_name}.py"

datas_list = [('env_example.txt', '.')]

if script_name in ['download_youtube', 'download_quick', 'app']:
    datas_list.append(('youtube_cookies.txt', '.'))

if script_name == 'app':
    datas_list.append(('templates', 'templates'))
    datas_list.append(('essentia', 'essentia'))

hiddenimports = [
    'yt_dlp', 'mutagen', 'mutagen.mp3', 'mutagen.id3',
    'dotenv', 'requests', 'database', 'sqlite3',
    'urllib', 'urllib.parse', 'urllib.request',
    'flask', 'flask_cors', 'werkzeug', 'jinja2'
]

if script_name == 'ide':
    hiddenimports.extend(['tkinter', 'PIL', 'PIL.Image', 'PIL.ImageTk'])

use_console = script_name not in ['app', 'ide']

datas_str = ',\n        '.join([repr(d) for d in datas_list])
hiddenimports_str = repr(hiddenimports)

spec_content = f"""# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['{script_file}'],
    pathex=[],
    binaries=[],
    datas=[
        {datas_str}
    ],
    hiddenimports={hiddenimports_str},
    hookspath=[],
    hooksconfig={{}},
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
    name='DJ_CUCHI_{script_name}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console={use_console},
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
"""

with open('build_temp.spec', 'w', encoding='utf-8') as f:
    f.write(spec_content)

print(f"Archivo .spec creado para {script_file} en {os_name}")
