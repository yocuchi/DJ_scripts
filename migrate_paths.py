#!/usr/bin/env python3
"""
Migra las rutas de archivo de la BD desde formato WSL (/mnt/c/...)
al formato Windows (C:\\...).

Uso:
  python migrate_paths.py            # modo dry-run (solo muestra)
  python migrate_paths.py --apply    # aplica los cambios
"""

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# /mnt/<letra>/foo/bar -> <Letra>:\foo\bar
def wsl_to_windows(wsl_path: str) -> str | None:
    if not wsl_path.startswith('/mnt/'):
        return None
    rest = wsl_path[len('/mnt/'):]
    if len(rest) < 2 or rest[1] != '/':
        return None
    drive = rest[0].upper()
    body = rest[2:].replace('/', '\\')
    return f"{drive}:\\{body}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply', action='store_true',
        help='Aplica los cambios. Sin este flag solo se muestra qué pasaría.',
    )
    parser.add_argument(
        '--no-backup', action='store_true',
        help='No crear backup de la BD antes de aplicar (no recomendado).',
    )
    args = parser.parse_args()

    db_path = os.environ.get(
        'DB_PATH', str(Path.home() / '.youtube_music.db')
    )
    db_path = Path(db_path)

    if not db_path.exists():
        print(f"ERROR: No se encuentra la BD en: {db_path}")
        return 1

    print(f"BD: {db_path}")
    print(f"Modo: {'APLICAR CAMBIOS' if args.apply else 'DRY-RUN (solo simulacion)'}\n")

    # Backup
    if args.apply and not args.no_backup:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = db_path.with_name(db_path.name + f'.bak_{ts}')
        shutil.copy2(db_path, backup)
        print(f"Backup creado: {backup}\n")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    rows = c.execute(
        "SELECT id, video_id, file_path FROM songs WHERE file_path LIKE '/mnt/%'"
    ).fetchall()

    total = len(rows)
    print(f"Filas con rutas WSL a procesar: {total}\n")

    stats = {
        'updated': 0,
        'skipped_missing_file': 0,
        'skipped_duplicate': 0,
        'skipped_not_convertible': 0,
        'errors': 0,
    }

    missing_files: list[tuple[int, str, str]] = []
    duplicates: list[tuple[int, str, str]] = []

    for r in rows:
        row_id = r['id']
        video_id = r['video_id']
        old = r['file_path']
        new = wsl_to_windows(old)

        if new is None:
            stats['skipped_not_convertible'] += 1
            print(f"  [SKIP] [{video_id}] No convertible: {old}")
            continue

        if not Path(new).exists():
            stats['skipped_missing_file'] += 1
            missing_files.append((row_id, video_id, new))
            continue

        # ¿Hay otra fila con la nueva ruta? UNIQUE constraint
        dup = c.execute(
            "SELECT id, video_id FROM songs WHERE file_path = ? AND id != ?",
            (new, row_id),
        ).fetchone()
        if dup:
            stats['skipped_duplicate'] += 1
            duplicates.append((row_id, video_id, dup['video_id']))
            continue

        if args.apply:
            try:
                c.execute(
                    "UPDATE songs SET file_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new, row_id),
                )
                stats['updated'] += 1
            except sqlite3.IntegrityError as e:
                stats['errors'] += 1
                print(f"  [ERR ] [{video_id}] {e}")
        else:
            stats['updated'] += 1  # se actualizaria en modo apply

    if args.apply:
        conn.commit()

    conn.close()

    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  Actualizadas               : {stats['updated']}")
    print(f"  Omitidas (archivo ausente) : {stats['skipped_missing_file']}")
    print(f"  Omitidas (duplicado)       : {stats['skipped_duplicate']}")
    print(f"  Omitidas (no convertibles) : {stats['skipped_not_convertible']}")
    print(f"  Errores                    : {stats['errors']}")
    print(f"  Total procesadas           : {total}")

    if missing_files:
        print(f"\n--- {len(missing_files)} filas con archivo no encontrado en disco ---")
        for row_id, vid, new in missing_files[:20]:
            print(f"  id={row_id} video={vid} esperado: {new}")
        if len(missing_files) > 20:
            print(f"  ...y {len(missing_files) - 20} mas")

    if duplicates:
        print(
            f"\n--- {len(duplicates)} filas omitidas porque ya existe otra con esa ruta ---"
        )
        print("    (esto pasa cuando ya se descargo la version Windows en una sesion anterior)")
        for row_id, vid, dup_vid in duplicates[:20]:
            print(f"  id={row_id} video_id_antiguo={vid}  ya existe con video_id={dup_vid}")
        if len(duplicates) > 20:
            print(f"  ...y {len(duplicates) - 20} mas")

    if not args.apply:
        print("\nNo se ha modificado nada. Vuelve a ejecutar con --apply para aplicar.")
    else:
        print("\nMigracion completada.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
