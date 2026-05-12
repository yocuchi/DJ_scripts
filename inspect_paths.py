#!/usr/bin/env python3
"""Inspecciona la BD para ver rutas de archivo desactualizadas (/mnt/c/...)."""

import os
import sqlite3
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

db_path = os.environ.get(
    'DB_PATH',
    str(Path.home() / '.youtube_music.db'),
)

if not Path(db_path).exists():
    print(f"ERROR: No se encuentra la BD en: {db_path}")
    sys.exit(1)

print(f"BD: {db_path}\n")

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

total = c.execute('SELECT COUNT(*) FROM songs').fetchone()[0]
mnt_c = c.execute(
    "SELECT COUNT(*) FROM songs WHERE file_path LIKE '/mnt/c/%'"
).fetchone()[0]
mnt_other = c.execute(
    "SELECT COUNT(*) FROM songs WHERE file_path LIKE '/mnt/%' AND file_path NOT LIKE '/mnt/c/%'"
).fetchone()[0]
win = c.execute(
    "SELECT COUNT(*) FROM songs WHERE file_path LIKE '_:\\%' OR file_path LIKE '_:/%'"
).fetchone()[0]
otras = total - mnt_c - mnt_other - win

print(f"Total canciones en BD : {total}")
print(f"Con ruta /mnt/c/...   : {mnt_c}")
print(f"Con ruta /mnt/<otra>/ : {mnt_other}")
print(f"Con ruta Windows (X:) : {win}")
print(f"Otras                 : {otras}\n")

if mnt_c > 0:
    print("=== Muestra de 5 rutas /mnt/c/ ===")
    rows = c.execute(
        "SELECT video_id, file_path FROM songs WHERE file_path LIKE '/mnt/c/%' LIMIT 5"
    ).fetchall()
    for r in rows:
        print(f"  [{r['video_id']}] {r['file_path']}")
    print()

    print("=== Verificacion de existencia (primeras 10 filas /mnt/c/) ===")
    rows = c.execute(
        "SELECT video_id, file_path FROM songs WHERE file_path LIKE '/mnt/c/%' LIMIT 10"
    ).fetchall()
    found_existing = 0
    found_missing = 0
    for r in rows:
        old = r['file_path']
        # Convertir /mnt/c/foo/bar -> C:\foo\bar
        rest = old[len('/mnt/c/'):]
        new = 'C:\\' + rest.replace('/', '\\')
        exists = Path(new).exists()
        if exists:
            found_existing += 1
        else:
            found_missing += 1
        marker = 'OK ' if exists else 'NO '
        print(f"  {marker} -> {new}")
    print(f"\n  De la muestra: {found_existing} encontradas, {found_missing} no encontradas")

conn.close()
