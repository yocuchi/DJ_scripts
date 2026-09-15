#!/usr/bin/env python3
"""
Sube la biblioteca a MEGA en una sola dirección: servidor -> MEGA.

Nunca borra nada, ni en local ni en remoto. Si un fichero desaparece del
servidor, su copia en MEGA se queda: esto es una copia de seguridad, no un
espejo.

Por qué no `mega-sync` ni un `mega-put` a pelo:

  * `mega-sync` es bidireccional. Lo que se borre o se mueva en MEGA se
    borraría también en la biblioteca del servidor.
  * `mega-put` no sabe saltarse lo que ya está subido, así que ejecutarlo en
    bucle crea duplicados y versiones. Con la cuenta al 91% eso la llena.

Así que se listan los dos lados, se sube solo la diferencia, y se comprueba
antes que quepa.

La comparación se hace normalizando a NFC: los ficheros llegaron por rsync
desde el Mac, que guarda los nombres en NFD (la tilde va como carácter
aparte). Sin normalizar, "Ya No Más.mp3" parecería un fichero distinto en cada
lado y se subiría una y otra vez.

La base de datos SQLite queda excluida siempre. Un sincronizador no puede
fusionar una BD, y subir versiones enteras del fichero desde varias máquinas
solo produce corrupción.
"""

import fcntl
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

LOCAL_ROOT = Path(os.getenv('MEGA_LOCAL_ROOT', '/srv/dj-music/DJ_SCRIPTS_LIB'))
REMOTE_ROOT = os.getenv('MEGA_REMOTE_ROOT', '/DJ_SCRIPTS_LIB')

EXCLUDED_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}
# Descargas a medias de yt-dlp, mas la BD y sus ficheros WAL
EXCLUDED_SUFFIXES = ('.db', '.db-wal', '.db-shm', '.db-journal', '.part', '.ytdl')

# Solo para avisar: lo que no sea audio conocido se sube igual (esto es una
# copia de seguridad, no debe descartar datos en silencio) pero se menciona.
AUDIO_SUFFIXES = ('.mp3', '.m4a', '.ogg', '.wav', '.flac', '.aac', '.opus')

# Margen que se deja libre en MEGA. Las versiones de ficheros que genera al
# reescribirse las etiquetas ID3 también consumen cuota.
SAFETY_MARGIN_BYTES = 300 * 1024 * 1024


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def nfc(text):
    return unicodedata.normalize('NFC', text)


def check_session():
    result = run(['mega-whoami'])
    if result.returncode != 0 or 'e-mail' not in result.stdout:
        sys.exit('No hay sesión de MEGA. Abre una con: ssh -t orac mega-cmd  ->  login <correo>')
    print(result.stdout.strip().splitlines()[0])


def local_files():
    """
    Clave normalizada a NFC -> (ruta real en disco, tamaño).

    La clave se normaliza solo para poder comparar con lo que hay en MEGA; la
    ruta real se guarda tal cual porque en Linux el nombre en NFD y el mismo
    nombre en NFC son ficheros distintos, y abrir la forma equivocada falla.
    """
    found = {}
    for path in LOCAL_ROOT.rglob('*'):
        if not path.is_file():
            continue
        if path.name in EXCLUDED_NAMES or path.name.startswith('._'):
            continue
        if path.name.endswith(EXCLUDED_SUFFIXES):
            continue
        clave = nfc(str(path.relative_to(LOCAL_ROOT)))
        found[clave] = (path, path.stat().st_size)
    return found


def remote_files():
    """Rutas relativas ya presentes en MEGA."""
    result = run(['mega-find', REMOTE_ROOT, '--type=f'])
    if result.returncode != 0:
        sys.exit(f'mega-find falló: {result.stderr.strip() or result.stdout.strip()}')
    prefix = REMOTE_ROOT.rstrip('/') + '/'
    found = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            found.add(nfc(line[len(prefix):]))
    return found


def free_space():
    """Bytes libres en la cuenta, o None si no se puede determinar."""
    result = run(['mega-df'])
    for line in result.stdout.splitlines():
        if 'USED STORAGE' in line and '% of' in line:
            try:
                usado = int(line.split(':')[1].split()[0])
                total = int(line.rsplit('of', 1)[1].strip())
                return total - usado
            except (IndexError, ValueError):
                return None
    return None


def acquire_lock():
    """
    Un solo subidor a la vez. El timer podria dispararse mientras una subida
    larga sigue en curso, y las dos verian la misma lista de pendientes: cada
    fichero se subiria dos veces y MEGA se quedaria con duplicados.
    """
    lock_path = Path('/tmp/dj-mega-upload.lock')
    handle = open(lock_path, 'w')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit('Ya hay una subida en curso. Se sale sin hacer nada.')
    return handle  # se mantiene abierto mientras dure el proceso


def main():
    lock = acquire_lock()  # noqa: F841 - el cerrojo dura lo que el proceso
    if not LOCAL_ROOT.is_dir():
        sys.exit(f'No existe la biblioteca local: {LOCAL_ROOT}')
    check_session()

    locales = local_files()
    remotos = remote_files()
    pendientes = sorted(set(locales) - remotos)

    total = sum(locales[rel][1] for rel in pendientes)
    print(f'local: {len(locales)} ficheros | en MEGA: {len(remotos)} | por subir: {len(pendientes)}')

    raros = [rel for rel in pendientes if not rel.lower().endswith(AUDIO_SUFFIXES)]
    if raros:
        print(f'aviso: {len(raros)} ficheros sin extension de audio conocida (se suben igual):')
        for rel in raros[:5]:
            print(f'   {rel}')
    if not pendientes:
        print('Nada que hacer.')
        return 0
    print(f'a subir: {total / 1048576:.0f} MB')

    libre = free_space()
    if libre is not None:
        print(f'libre en MEGA: {libre / 1048576:.0f} MB')
        if total + SAFETY_MARGIN_BYTES > libre:
            sys.exit(
                'No hay espacio suficiente en MEGA (dejando %.0f MB de margen).\n'
                'Vacía la papelera o libera espacio y vuelve a lanzarlo.'
                % (SAFETY_MARGIN_BYTES / 1048576)
            )

    if '--dry-run' in sys.argv:
        for rel in pendientes[:10]:
            print(f'  subiria: {rel}')
        if len(pendientes) > 10:
            print(f'  ... y {len(pendientes) - 10} mas')
        return 0

    # --limit N: subir solo los N primeros (para probar sin mover toda la biblioteca)
    if '--limit' in sys.argv:
        n = int(sys.argv[sys.argv.index('--limit') + 1])
        pendientes = pendientes[:n]
        print(f'--limit {n}: se suben solo {len(pendientes)}')

    subidos = fallos = 0
    for rel in pendientes:
        origen, _ = locales[rel]
        # mega-put necesita la carpeta destino, no la ruta del fichero
        destino = REMOTE_ROOT.rstrip('/') + '/' + str(Path(rel).parent).replace(os.sep, '/')
        destino = destino.rstrip('/.') or REMOTE_ROOT
        result = run(['mega-put', '-c', str(origen), destino + '/'])
        if result.returncode == 0:
            subidos += 1
        else:
            fallos += 1
            print(f'  FALLO {rel}: {(result.stderr or result.stdout).strip()[:160]}')

    print(f'subidos: {subidos} | fallos: {fallos}')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
