#!/usr/bin/env python3
"""
Script de reparación de codificación: corrige títulos y artistas con doble
codificación UTF-8/Latin-1 en los tags ID3 de los MP3 y en la base de datos.

Causa: yt-dlp antiguo escribía bytes UTF-8 en frames ID3 marcados como Latin-1.
Al releer con mutagen y reescribir como UTF-8, el texto corrupto quedó preservado.

Ejecución: python fix_encoding.py [--dry-run]
"""

import sys
import re
import shutil
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
import os

# Cargar .env
load_dotenv(Path(__file__).parent / '.env')

MUSIC_FOLDER = Path(os.environ.get('MUSIC_FOLDER', ''))
DB_PATH = Path(os.environ.get('DB_PATH', Path.home() / '.youtube_music.db'))

DRY_RUN = '--dry-run' in sys.argv


# ---------------------------------------------------------------------------
# Funciones de reparación de codificación
# ---------------------------------------------------------------------------

def fix_mojibake(text: str) -> str:
    """
    Intenta reparar el clásico error UTF-8 bytes → Latin-1 → UTF-8.
    Aplica hasta 3 pasadas para casos de corrupción múltiple.
    Devuelve el texto original si no se puede reparar.
    """
    if not text:
        return text
    # macOS almacena nombres en NFD; normalizar a NFC antes de detectar
    import unicodedata
    result = unicodedata.normalize('NFC', text)
    for _ in range(3):
        try:
            candidate = result.encode('latin-1').decode('utf-8')
            if candidate != result:
                result = candidate
            else:
                break
        except (UnicodeDecodeError, UnicodeEncodeError):
            break
    return result


def needs_fix(text: str) -> bool:
    """Detecta si un string tiene el patrón de doble codificación."""
    if not text:
        return False
    import unicodedata
    nfc = unicodedata.normalize('NFC', text)
    try:
        fixed = nfc.encode('latin-1').decode('utf-8')
        return fixed != nfc
    except (UnicodeDecodeError, UnicodeEncodeError):
        return False


# ---------------------------------------------------------------------------
# Reparar ID3 tags en MP3
# ---------------------------------------------------------------------------

def fix_mp3_tags(music_folder: Path, dry_run: bool = False) -> dict:
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, TIT2, TPE1, TCON, TALB
    except ImportError:
        print("❌ mutagen no está instalado")
        return {}

    mp3_files = list(music_folder.rglob('*.mp3'))
    stats = {'total': len(mp3_files), 'fixed': 0, 'skipped': 0, 'errors': 0}

    print(f"\n🎵 Escaneando {len(mp3_files)} archivos MP3 en:")
    print(f"   {music_folder}\n")

    TAG_CLASSES = {
        'TIT2': TIT2,
        'TPE1': TPE1,
        'TCON': TCON,
        'TALB': TALB,
    }

    for mp3_path in mp3_files:
        try:
            audio = MP3(str(mp3_path), ID3=ID3)
            modified = False

            for tag_key, TagClass in TAG_CLASSES.items():
                if tag_key not in audio:
                    continue
                tag = audio.tags[tag_key]
                original = str(tag)

                if not needs_fix(original):
                    continue

                fixed_text = fix_mojibake(original)
                if fixed_text == original:
                    continue

                print(f"  📄 {mp3_path.name[:70]}")
                print(f"     {tag_key} original: {original[:70]}")
                print(f"     {tag_key} reparado:  {fixed_text[:70]}")

                modified = True
                if not dry_run:
                    audio[tag_key] = TagClass(encoding=3, text=fixed_text)

            if modified and not dry_run:
                audio.save()
                stats['fixed'] += 1
                print(f"     ✅ Guardado\n")
            elif modified and dry_run:
                stats['fixed'] += 1
                print(f"     🔍 [DRY-RUN - no se guarda]\n")
            else:
                stats['skipped'] += 1

        except Exception as e:
            stats['errors'] += 1
            print(f"  ❌ Error en {mp3_path.name}: {e}")

    return stats


# ---------------------------------------------------------------------------
# Reparar títulos en la base de datos
# ---------------------------------------------------------------------------

def fix_database(db_path: Path, dry_run: bool = False) -> dict:
    if not db_path.exists():
        print(f"\n⚠️  Base de datos no encontrada: {db_path}")
        return {}

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Detectar columnas disponibles
    cur.execute("PRAGMA table_info(songs)")
    columns = [row[1] for row in cur.fetchall()]
    text_cols = [c for c in ['title', 'artist', 'genre', 'album'] if c in columns]

    cur.execute("SELECT rowid, " + ", ".join(text_cols) + " FROM songs")
    rows = cur.fetchall()

    stats = {'total': len(rows), 'fixed': 0, 'skipped': 0}

    print(f"\n🗄️  Escaneando {len(rows)} registros en BD:")
    print(f"   {db_path}\n")

    for row in rows:
        rowid = row[0]
        values = list(row[1:])
        updated = {}

        for i, col in enumerate(text_cols):
            original = values[i]
            if not needs_fix(original):
                continue
            fixed = fix_mojibake(original)
            if fixed != original:
                updated[col] = (original, fixed)

        if not updated:
            stats['skipped'] += 1
            continue

        print(f"  🔧 rowid={rowid}")
        set_clauses = []
        params = []
        for col, (orig, fixed) in updated.items():
            print(f"     {col}: {orig[:60]!r}")
            print(f"       → {fixed[:60]!r}")
            set_clauses.append(f"{col} = ?")
            params.append(fixed)
        params.append(rowid)

        if not dry_run:
            cur.execute(
                f"UPDATE songs SET {', '.join(set_clauses)} WHERE rowid = ?",
                params
            )
            print(f"     ✅ Actualizado en BD\n")
        else:
            print(f"     🔍 [DRY-RUN - no se guarda]\n")

        stats['fixed'] += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return stats


# ---------------------------------------------------------------------------
# Reparar nombres de archivo con codificación corrupta
# ---------------------------------------------------------------------------

def fix_filenames(music_folder: Path, dry_run: bool = False) -> dict:
    mp3_files = list(music_folder.rglob('*.mp3'))
    stats = {'total': len(mp3_files), 'fixed': 0, 'skipped': 0, 'errors': 0}

    print(f"\n📁 Revisando nombres de archivo...\n")

    for mp3_path in mp3_files:
        filename = mp3_path.stem  # sin extensión
        if not needs_fix(filename):
            stats['skipped'] += 1
            continue

        fixed_stem = fix_mojibake(filename)
        new_path = mp3_path.parent / (fixed_stem + mp3_path.suffix)

        if new_path == mp3_path:
            stats['skipped'] += 1
            continue

        print(f"  📄 Nombre original: {mp3_path.name[:70]}")
        print(f"     Nombre reparado: {new_path.name[:70]}")

        if not dry_run:
            try:
                mp3_path.rename(new_path)
                stats['fixed'] += 1
                print(f"     ✅ Renombrado\n")
            except Exception as e:
                stats['errors'] += 1
                print(f"     ❌ Error al renombrar: {e}\n")
        else:
            stats['fixed'] += 1
            print(f"     🔍 [DRY-RUN - no se renombra]\n")

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 65)
    print("  🔧 Reparador de codificación UTF-8/Latin-1 - DJ Scripts")
    print("=" * 65)

    if DRY_RUN:
        print("\n⚠️  Modo DRY-RUN: solo se muestra qué se cambiaría, sin guardar.\n")

    if not MUSIC_FOLDER or not MUSIC_FOLDER.exists():
        print(f"❌ MUSIC_FOLDER no válida: {MUSIC_FOLDER}")
        sys.exit(1)

    # 1. Reparar ID3 tags
    mp3_stats = fix_mp3_tags(MUSIC_FOLDER, dry_run=DRY_RUN)

    # 2. Reparar nombres de archivo
    fn_stats = fix_filenames(MUSIC_FOLDER, dry_run=DRY_RUN)

    # 3. Reparar base de datos
    db_stats = fix_database(DB_PATH, dry_run=DRY_RUN)

    # Resumen
    print("\n" + "=" * 65)
    print("  📊 RESUMEN")
    print("=" * 65)
    print(f"  MP3 tags reparados: {mp3_stats.get('fixed', 0)} / {mp3_stats.get('total', 0)}")
    print(f"  Archivos renombrados: {fn_stats.get('fixed', 0)} / {fn_stats.get('total', 0)}")
    print(f"  Registros BD reparados: {db_stats.get('fixed', 0)} / {db_stats.get('total', 0)}")
    if DRY_RUN:
        print("\n  ℹ️  Para aplicar los cambios, ejecuta sin --dry-run")
    print()


if __name__ == '__main__':
    main()
