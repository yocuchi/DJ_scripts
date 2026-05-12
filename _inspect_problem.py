"""Mira los registros problemáticos antes de migrar."""
import os
import sqlite3
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

db_path = os.environ.get('DB_PATH', str(Path.home() / '.youtube_music.db'))
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

ids_objetivo = [41, 144, 163]
for i in ids_objetivo:
    r = c.execute("SELECT * FROM songs WHERE id = ?", (i,)).fetchone()
    if r is None:
        print(f"[id={i}] NO EXISTE")
        continue
    print(f"--- id={r['id']} video_id={r['video_id']} ---")
    for k in r.keys():
        v = r[k]
        if isinstance(v, str) and len(v) > 200:
            v = v[:200] + '... [truncado]'
        print(f"  {k}: {v}")
    print()

# También: si hay otra fila con video_id Aivzwnexylg
print("--- Filas con video_id Aivzwnexylg ---")
rows = c.execute("SELECT id, video_id, title, file_path FROM songs WHERE video_id = 'Aivzwnexylg'").fetchall()
for r in rows:
    print(f"  id={r['id']} title={r['title']!r} path={r['file_path']}")

conn.close()
