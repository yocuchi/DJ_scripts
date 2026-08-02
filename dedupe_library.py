"""
Limpia los duplicados que dejaron dos bugs ya corregidos en download_youtube.py:

  A) Ficheros duplicados en disco: process_imported_mp3 copiaba en vez de mover
     al reclasificar por género, dejando el original huérfano (normalmente en
     'Sin Clasificar'). DJUCED escanea el disco, así que salían dos veces.
  B) Filas duplicadas en la BD: check_file_exists descartaba una coincidencia
     válida si la ruta guardada era de otra plataforma ('C:\\...', '/mnt/c/...'),
     y el video_id de los importados venía de hash(), aleatorio por proceso.

Sin --apply sólo simula. Los ficheros no se borran: se mueven a
~/Desktop/DJ_FRAN/_DUPLICADOS_DJ_SCRIPTS_LIB (fuera de la biblioteca, para que
DJUCED no los siga viendo). Haz backup de la BD antes:

    sqlite3 <lib>/.youtube_music.db ".backup '<lib>/.youtube_music.db.bak'"
"""
import sqlite3, shutil, sys
from pathlib import Path

APPLY = "--apply" in sys.argv
LIB = Path.home() / "Desktop/DJ_FRAN/DJ_SCRIPTS_LIB"
TRASH = Path.home() / "Desktop/DJ_FRAN/_DUPLICADOS_DJ_SCRIPTS_LIB"   # FUERA de la biblioteca
DB = LIB / ".youtube_music.db"

# Decision tomada: en este par se conserva el genero real, no el de la BD
OVERRIDE_KEEP = {"Eagle - Eye Cherry - Save Tonight.mp3": "Deep House"}

con = sqlite3.connect(str(DB), timeout=30)
con.execute("PRAGMA busy_timeout=30000")
con.row_factory = sqlite3.Row
rows = con.execute("SELECT * FROM songs").fetchall()

def stored_name(r): return (r["file_path"] or "").replace("\\","/").rstrip("/").split("/")[-1]
def stored_genre(r):
    p = (r["file_path"] or "").replace("\\","/").split("/")
    return p[-3] if len(p) >= 3 else None

by_name = {}
for r in rows:
    by_name.setdefault(stored_name(r), []).append(r)

tag = "APLICANDO" if APPLY else "SIMULACION (dry-run)"
print(f"{'='*78}\n{tag}\n{'='*78}")

# ---------------- A: ficheros duplicados ----------------
dups = sorted(n for n in {p.name for p in LIB.rglob("*.mp3")} if len(list(LIB.rglob(n))) > 1)
moved = 0
path_fixes = []
print(f"\n--- A: {len(dups)} pares de ficheros ---")
for n in dups:
    copies = sorted(LIB.rglob(n))
    keep_genre = OVERRIDE_KEEP.get(n) or next((stored_genre(r) for r in by_name.get(n, [])), None)
    keep = [c for c in copies if c.relative_to(LIB).parts[0] == keep_genre]
    if len(keep) != 1:
        print(f"  ⏭️  {n}: no se puede decidir (keep_genre={keep_genre}), SE OMITE")
        continue
    keep = keep[0]
    for c in copies:
        if c == keep:
            continue
        dest = TRASH / c.relative_to(LIB)
        print(f"  {n[:52]}")
        print(f"     conservar: {keep.relative_to(LIB)}")
        print(f"     a papelera: {c.relative_to(LIB)}")
        if APPLY:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(c), str(dest))
        moved += 1
    # la fila de la BD debe apuntar al fichero conservado
    for r in by_name.get(n, []):
        if str(r["file_path"]) != str(keep):
            path_fixes.append((r["video_id"], str(keep), keep.relative_to(LIB).parts[0], r["genre"]))

# ---------------- D: filas duplicadas ----------------
groups = {}
for r in rows:
    groups.setdefault(((r["artist"] or "").lower(), (r["title"] or "").lower()), []).append(r)
dup_groups = {k: v for k, v in groups.items() if len(v) > 1}

def real_id(r):  return not (r["video_id"] or "").startswith("imported_")
def local(r):    return (r["file_path"] or "").startswith("/Users/")
def rich(r):     return sum(1 for c in ("waveform_data","bitrate_kbps","volume_lufs","duration","thumbnail_url") if r[c] not in (None,"",0))

to_delete = []
for k, v in dup_groups.items():
    reals = [r for r in v if real_id(r)]
    ordered = ([reals[0]] + [r for r in v if r is not reals[0]] if len(reals) == 1
               else sorted(v, key=lambda r: (local(r), rich(r)), reverse=True))
    to_delete += [r["id"] for r in ordered[1:]]

print(f"\n--- D: {len(dup_groups)} grupos -> eliminar {len(to_delete)} filas ---")
print(f"  filas antes: {len(rows)}  ->  despues: {len(rows)-len(to_delete)}")
print(f"\n--- Rutas de filas conservadas a corregir: {len(path_fixes)} ---")
for vid, newp, newg, oldg in path_fixes:
    extra = f"  (genero {oldg} -> {newg})" if oldg != newg else ""
    print(f"  {vid[:14]}: -> .../{newp.split('DJ_SCRIPTS_LIB/')[-1]}{extra}")

if APPLY:
    cur = con.cursor()
    cur.executemany("DELETE FROM songs WHERE id = ?", [(i,) for i in to_delete])
    for vid, newp, newg, oldg in path_fixes:
        cur.execute("UPDATE songs SET file_path = ?, genre = ? WHERE video_id = ?", (newp, newg, vid))
    con.commit()
    print(f"\n✅ {moved} ficheros movidos | {len(to_delete)} filas borradas | {len(path_fixes)} rutas corregidas")
    print(f"   filas ahora: {con.execute('SELECT COUNT(*) FROM songs').fetchone()[0]}")
else:
    print(f"\n(nada modificado — moveria {moved} ficheros)")
con.close()
