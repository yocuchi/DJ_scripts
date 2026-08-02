#!/usr/bin/env python3
"""
Migración: añade el YouTube ID al campo TXXX:YouTube ID de cada MP3.

Fuentes de ID, en orden de fiabilidad:
  1. Base de datos (.youtube_music.db)  — video_id guardado al descargar
  2. Nombre del fichero / tag TIT2       — patrón [xxxxxxxxxxx] (11 chars)
  3. Búsqueda en YouTube (--search)      — solo con confirmación del usuario

Uso:
  python migrate_youtube_ids.py [--dry-run] [--search] [--folder PATH] [--db PATH]

Flags:
  --dry-run   Muestra lo que haría sin modificar ningún fichero
  --search    Busca en YouTube los ficheros que no tienen ID
  --folder    Ruta de la carpeta de música (por defecto: detecta automáticamente)
  --db        Ruta de la base de datos     (por defecto: detecta automáticamente)
"""

import argparse
import os
import re
import sys
import sqlite3
from pathlib import Path

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TXXX, error as ID3Error

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

YOUTUBE_ID_RE = re.compile(r'\[([A-Za-z0-9_-]{11})\]')

# Raíces candidatas del archivo de música / BD, en orden de preferencia
_ONEDRIVE_ROOTS = [
    Path.home() / 'Library/CloudStorage/OneDrive-AyuntamientodeMadrid',
    Path.home() / 'OneDrive - Ayuntamiento de Madrid',
]
_LIB_SUBPATH = 'Escritorio/DJ_FRAN/DJ_SCRIPTS_LIB'


def _find_lib_root() -> Path | None:
    for root in _ONEDRIVE_ROOTS:
        candidate = root / _LIB_SUBPATH
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

def build_db_index(db_path: Path) -> dict[str, str]:
    """
    Devuelve {basename_normalizado: video_id} leyendo la BD.
    También incluye la clave por sufijo relativo a DJ_SCRIPTS_LIB para
    mayor precisión cuando hay basenames duplicados.
    """
    index: dict[str, str] = {}
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute('SELECT video_id, file_path FROM songs WHERE video_id IS NOT NULL AND file_path IS NOT NULL')
        for video_id, raw_path in cursor.fetchall():
            if not video_id or video_id.startswith('imported_'):
                continue
            # Normalizar separadores
            norm = raw_path.replace('\\', '/')
            # Clave 1: basename
            basename = norm.rstrip('/').split('/')[-1]
            if basename and basename not in index:
                index[basename] = video_id
            # Clave 2: sufijo desde DJ_SCRIPTS_LIB/
            marker = 'DJ_SCRIPTS_LIB/'
            idx = norm.find(marker)
            if idx != -1:
                suffix = norm[idx + len(marker):]
                if suffix and suffix not in index:
                    index[suffix] = video_id
        conn.close()
    except Exception as e:
        print(f'  ⚠️  Error leyendo BD: {e}')
    return index


def lookup_video_id(mp3_path: Path, db_index: dict[str, str], lib_root: Path | None) -> str | None:
    """Busca el video_id en el índice de BD por basename y por sufijo."""
    basename = mp3_path.name
    if basename in db_index:
        return db_index[basename]
    if lib_root:
        try:
            suffix = str(mp3_path.relative_to(lib_root)).replace('\\', '/')
            if suffix in db_index:
                return db_index[suffix]
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Extracción de ID desde nombre / tags
# ---------------------------------------------------------------------------

def extract_id_from_string(text: str) -> str | None:
    """Devuelve el primer patrón [xxxxxxxxxxx] (11 chars) encontrado."""
    m = YOUTUBE_ID_RE.search(text)
    return m.group(1) if m else None


def read_current_youtube_id(mp3_path: Path) -> str | None:
    """Lee TXXX:YouTube ID del fichero si ya existe."""
    try:
        audio = MP3(str(mp3_path), ID3=ID3)
        frame = audio.get('TXXX:YouTube ID')
        if frame:
            return str(frame.text[0]).strip() or None
    except Exception:
        pass
    return None


def read_title_tag(mp3_path: Path) -> str | None:
    """Lee el tag TIT2 del fichero."""
    try:
        audio = MP3(str(mp3_path), ID3=ID3)
        frame = audio.get('TIT2')
        if frame:
            return str(frame.text[0]).strip() or None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Escritura de tags
# ---------------------------------------------------------------------------

def write_youtube_id_tag(mp3_path: Path, video_id: str, dry_run: bool) -> bool:
    """
    Escribe TXXX:YouTube ID en el fichero.
    Si el TIT2 contiene [video_id], lo limpia.
    Devuelve True si el fichero fue (o habría sido) modificado.
    """
    try:
        audio = MP3(str(mp3_path), ID3=ID3)
    except ID3Error:
        try:
            audio = MP3(str(mp3_path))
            audio.add_tags()
        except Exception as e:
            print(f'    ❌ No se pudo abrir {mp3_path.name}: {e}')
            return False
    except Exception as e:
        print(f'    ❌ Error abriendo {mp3_path.name}: {e}')
        return False

    changed = False

    # Escribir TXXX:YouTube ID
    existing_frame = audio.get('TXXX:YouTube ID')
    existing_id = str(existing_frame.text[0]).strip() if existing_frame else None
    if existing_id != video_id:
        if not dry_run:
            audio['TXXX:YouTube ID'] = TXXX(encoding=3, desc='YouTube ID', text=video_id)
        changed = True

    # Limpiar TIT2 si contiene [video_id]
    tit2_frame = audio.get('TIT2')
    if tit2_frame:
        original_title = str(tit2_frame.text[0])
        clean_title = re.sub(r'\s*\[' + re.escape(video_id) + r'\]\s*', ' ', original_title).strip()
        if clean_title != original_title:
            if not dry_run:
                audio['TIT2'] = TIT2(encoding=3, text=clean_title)
            changed = True

    if changed and not dry_run:
        try:
            audio.save()
        except Exception as e:
            print(f'    ❌ Error guardando {mp3_path.name}: {e}')
            return False

    return changed


# ---------------------------------------------------------------------------
# Búsqueda en YouTube (fallback)
# ---------------------------------------------------------------------------

def search_youtube_id(title: str | None, artist: str | None) -> tuple[str | None, str | None]:
    """
    Busca en YouTube usando yt-dlp y devuelve (video_id, video_title).
    Requiere que yt-dlp esté instalado.
    """
    try:
        import yt_dlp
    except ImportError:
        return None, None

    query_parts = []
    if artist:
        query_parts.append(artist)
    if title:
        # Quitar patrones [xxx] del título antes de buscar
        clean = YOUTUBE_ID_RE.sub('', title).strip()
        query_parts.append(clean)
    if not query_parts:
        return None, None

    query = ' '.join(query_parts)
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
        'default_search': 'ytsearch1',
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f'ytsearch1:{query}', download=False)
            if info and info.get('entries'):
                entry = info['entries'][0]
                return entry.get('id'), entry.get('title')
    except Exception:
        pass
    return None, None


def read_artist_tag(mp3_path: Path) -> str | None:
    try:
        audio = MP3(str(mp3_path), ID3=ID3)
        frame = audio.get('TPE1')
        if frame:
            return str(frame.text[0]).strip() or None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scan_and_migrate(folder: Path, db_index: dict[str, str], lib_root: Path | None,
                     dry_run: bool, do_search: bool) -> None:
    mp3_files = sorted(folder.rglob('*.mp3'))
    total = len(mp3_files)
    print(f'\n📂 Carpeta: {folder}')
    print(f'🎵 MP3 encontrados: {total}\n')

    stats = {'already_done': 0, 'db_match': 0, 'filename_match': 0,
             'search_match': 0, 'not_found': 0, 'errors': 0}
    not_found_files: list[Path] = []

    for i, mp3 in enumerate(mp3_files, 1):
        prefix = f'[{i:3}/{total}]'

        # ── 0. ¿Ya tiene el tag? ──────────────────────────────────────────
        existing_id = read_current_youtube_id(mp3)
        if existing_id:
            print(f'{prefix} ✅ Ya tiene ID: {mp3.name[:60]}')
            stats['already_done'] += 1
            continue

        # ── 1. Buscar en BD ───────────────────────────────────────────────
        video_id = lookup_video_id(mp3, db_index, lib_root)
        if video_id:
            tag_written = write_youtube_id_tag(mp3, video_id, dry_run)
            action = '(dry-run)' if dry_run else '→ escrito'
            marker = f'✏️  {action}' if tag_written else '✅ sin cambio'
            print(f'{prefix} 🗄️  BD      {marker}: {mp3.name[:60]}')
            stats['db_match'] += 1
            continue

        # ── 2. Extraer del nombre de fichero / TIT2 ───────────────────────
        video_id = extract_id_from_string(mp3.stem)
        if not video_id:
            title_tag = read_title_tag(mp3)
            if title_tag:
                video_id = extract_id_from_string(title_tag)

        if video_id:
            tag_written = write_youtube_id_tag(mp3, video_id, dry_run)
            action = '(dry-run)' if dry_run else '→ escrito'
            marker = f'✏️  {action}' if tag_written else '✅ sin cambio'
            print(f'{prefix} 🔍 Nombre  {marker}: {mp3.name[:60]}')
            stats['filename_match'] += 1
            continue

        # ── 3. Sin ID encontrado ──────────────────────────────────────────
        print(f'{prefix} ❓ Sin ID : {mp3.name[:70]}')
        not_found_files.append(mp3)
        stats['not_found'] += 1

    # ── Búsqueda en YouTube para los que no tienen ID ─────────────────────
    if do_search and not_found_files:
        print(f'\n🔎 Buscando en YouTube los {len(not_found_files)} ficheros sin ID...\n')
        for mp3 in not_found_files:
            title = read_title_tag(mp3) or mp3.stem
            artist = read_artist_tag(mp3)
            print(f'  🔍 {mp3.name[:65]}')
            print(f'     Buscando: {artist or ""} {title}')

            found_id, found_title = search_youtube_id(title, artist)
            if not found_id:
                print('     ⚠️  Sin resultado en YouTube\n')
                continue

            print(f'     Resultado: [{found_id}] {found_title}')
            resp = input('     ¿Escribir este ID? [s/N]: ').strip().lower()
            if resp == 's':
                write_youtube_id_tag(mp3, found_id, dry_run)
                action = '(dry-run)' if dry_run else 'escrito'
                print(f'     ✏️  ID {action}')
                stats['search_match'] += 1
                stats['not_found'] -= 1
            print()

    # ── Resumen ───────────────────────────────────────────────────────────
    print('\n' + '─' * 60)
    print('📊 RESUMEN')
    print('─' * 60)
    print(f"  ✅ Ya tenían TXXX:YouTube ID : {stats['already_done']}")
    print(f"  🗄️  ID obtenido de BD         : {stats['db_match']}")
    print(f"  🔍 ID extraído del nombre    : {stats['filename_match']}")
    if do_search:
        print(f"  🌐 ID encontrado en YouTube  : {stats['search_match']}")
    print(f"  ❓ Sin ID (pendientes)        : {stats['not_found']}")
    if dry_run:
        print('\n⚠️  Modo DRY-RUN: no se modificó ningún fichero.')
    else:
        written = stats['db_match'] + stats['filename_match'] + stats.get('search_match', 0)
        print(f'\n✅ Ficheros actualizados: {written}')
    print('─' * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description='Migra YouTube ID a tags ID3 (TXXX:YouTube ID)')
    parser.add_argument('--dry-run', action='store_true', help='Sin modificar ficheros')
    parser.add_argument('--search', action='store_true', help='Buscar en YouTube los sin ID')
    parser.add_argument('--folder', help='Carpeta de música (por defecto: auto-detecta)')
    parser.add_argument('--db', help='Ruta de la BD SQLite (por defecto: auto-detecta)')
    args = parser.parse_args()

    # ── Detectar rutas ────────────────────────────────────────────────────
    lib_root = _find_lib_root()

    if args.folder:
        music_folder = Path(args.folder)
    else:
        music_folder = lib_root
        if not music_folder:
            # Fallback: MUSIC_FOLDER del .env o ./MUSIC local
            from dotenv import load_dotenv
            load_dotenv()
            env_folder = os.getenv('MUSIC_FOLDER', '')
            music_folder = Path(env_folder) if env_folder else Path(__file__).parent / 'MUSIC'

    if not music_folder or not music_folder.exists():
        print(f'❌ No se encontró la carpeta de música: {music_folder}')
        print('   Usa --folder para especificarla manualmente.')
        sys.exit(1)

    if args.db:
        db_path = Path(args.db)
    else:
        db_path = None
        if lib_root:
            candidate = lib_root / '.youtube_music.db'
            if candidate.exists():
                db_path = candidate
        if not db_path:
            db_path = Path.home() / '.youtube_music.db'

    print('🎛️  Configuración:')
    print(f'   Carpeta : {music_folder}')
    print(f'   BD      : {db_path} {"✅" if db_path.exists() else "❌ no encontrada"}')
    print(f'   Dry-run : {args.dry_run}')
    print(f'   Búsqueda: {args.search}')

    # ── Construir índice de BD ────────────────────────────────────────────
    db_index: dict[str, str] = {}
    if db_path.exists():
        print('\n📖 Leyendo base de datos...')
        db_index = build_db_index(db_path)
        print(f'   {len(db_index)} entradas indexadas')
    else:
        print(f'\n⚠️  BD no encontrada, se usará solo extracción por nombre.')

    scan_and_migrate(music_folder, db_index, lib_root, args.dry_run, args.search)


if __name__ == '__main__':
    main()
