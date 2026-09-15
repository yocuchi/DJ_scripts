#!/usr/bin/env python3
"""
Baja la biblioteca desde MEGA en una sola dirección: MEGA -> esta máquina.

Es el reverso de mega_upload.py y está pensado para el Mac (o para cualquier
equipo con DJUCED). El servidor es quien descarga música y quien sube a MEGA;
aquí solo se recoge lo que falte.

Nunca borra nada. Si una pista desaparece de MEGA, la copia local se queda.
Tampoco sube nada: lo que edites en local no sale de esta máquina, así que no
puede pisar la biblioteca del servidor.

Esto importa especialmente en el Mac, donde la biblioteca vive dentro del
OneDrive corporativo: un sincronizador bidireccional ahí serían dos motores
peleándose por la misma carpeta, y cada reescritura del ID3 que hace DJUCED
dispararía subidas en las dos nubes.

Uso:
    export MEGA_LOCAL_ROOT="/ruta/a/DJ_SCRIPTS_LIB"
    python3 mega_download.py --dry-run
    python3 mega_download.py
"""

import os
import subprocess
import sys
import unicodedata
from pathlib import Path

LOCAL_ROOT = Path(os.getenv('MEGA_LOCAL_ROOT', '')).expanduser()
REMOTE_ROOT = os.getenv('MEGA_REMOTE_ROOT', '/DJ_SCRIPTS_LIB')

EXCLUDED_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}
EXCLUDED_SUFFIXES = ('.db', '.db-wal', '.db-shm', '.db-journal', '.part', '.ytdl')


def run(args):
    return subprocess.run(args, capture_output=True, text=True)


def nfc(text):
    return unicodedata.normalize('NFC', text)


def check_session():
    result = run(['mega-whoami'])
    if result.returncode != 0 or 'e-mail' not in result.stdout:
        sys.exit('No hay sesión de MEGA en esta máquina. Ábrela con: mega-cmd  ->  login <correo>')
    print(result.stdout.strip().splitlines()[0])


def local_keys():
    """Claves (ruta relativa en NFC) de lo que ya está aquí."""
    if not LOCAL_ROOT.is_dir():
        return set()
    found = set()
    for path in LOCAL_ROOT.rglob('*'):
        if path.is_file():
            found.add(nfc(str(path.relative_to(LOCAL_ROOT))))
    return found


def remote_files():
    """Rutas relativas presentes en MEGA, sin los ficheros que no tocan."""
    result = run(['mega-find', REMOTE_ROOT, '--type=f'])
    if result.returncode != 0:
        sys.exit(f'mega-find falló: {result.stderr.strip() or result.stdout.strip()}')
    prefix = REMOTE_ROOT.rstrip('/') + '/'
    found = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith(prefix):
            continue
        rel = line[len(prefix):]
        nombre = rel.rsplit('/', 1)[-1]
        if nombre in EXCLUDED_NAMES or nombre.startswith('._'):
            continue
        if nombre.endswith(EXCLUDED_SUFFIXES):
            continue
        found[nfc(rel)] = line
    return found


def main():
    if not str(LOCAL_ROOT):
        sys.exit('Define MEGA_LOCAL_ROOT con la ruta de tu carpeta DJ_SCRIPTS_LIB')
    check_session()

    remotos = remote_files()
    locales = local_keys()
    pendientes = sorted(set(remotos) - locales)

    print(f'en MEGA: {len(remotos)} | ya aquí: {len(locales)} | por bajar: {len(pendientes)}')
    if not pendientes:
        print('Nada que hacer.')
        return 0

    if '--dry-run' in sys.argv:
        for rel in pendientes[:15]:
            print(f'  bajaría: {rel}')
        if len(pendientes) > 15:
            print(f'  ... y {len(pendientes) - 15} más')
        return 0

    bajados = fallos = 0
    for rel in pendientes:
        destino = LOCAL_ROOT / Path(rel).parent
        destino.mkdir(parents=True, exist_ok=True)
        # mega-get quiere la ruta remota completa y una carpeta local de destino
        result = run(['mega-get', remotos[rel], str(destino) + os.sep])
        if result.returncode == 0:
            bajados += 1
        else:
            fallos += 1
            print(f'  FALLO {rel}: {(result.stderr or result.stdout).strip()[:160]}')

    print(f'bajados: {bajados} | fallos: {fallos}')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
