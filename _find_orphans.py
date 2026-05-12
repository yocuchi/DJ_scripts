"""Busca por disco si los archivos de los video_ids problemáticos existen."""
import os
import sys
import sqlite3
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

db_path = os.environ.get('DB_PATH', str(Path.home() / '.youtube_music.db'))
music_folder = os.environ.get('MUSIC_FOLDER', '').rstrip('.\\').rstrip('/')

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

target_ids = [144, 163]
for i in target_ids:
    r = c.execute("SELECT id, video_id, title, artist FROM songs WHERE id = ?", (i,)).fetchone()
    if r is None:
        continue
    video_id = r['video_id']
    print(f"=== id={i} video_id={video_id} ===")
    print(f"  title: {r['title'][:120]}")
    print(f"  artist: {r['artist'][:120] if r['artist'] else ''}")

    print(f"  buscando archivos que contengan '[{video_id}]' en disco bajo {music_folder}")
    found = []
    if music_folder and Path(music_folder).exists():
        for p in Path(music_folder).rglob(f'*{video_id}*'):
            if p.is_file():
                found.append(p)
    if not found:
        print("  -> NO se encontró ningún archivo con ese video_id en disco")
    else:
        for f in found:
            print(f"  -> ENCONTRADO: {f}")
    print()

conn.close()
