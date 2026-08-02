#!/usr/bin/env python3
"""
Convierte el artwork embebido en MP3s a JPEG para compatibilidad con DJUCED.
YouTube sirve thumbnails en WebP, que DJUCED no muestra aunque el MIME diga image/jpeg.

Con --recover, además vuelve a descargar la portada de YouTube para los MP3 que no
tengan APIC pero sí guarden su YouTube ID en el tag TXXX:YouTube ID.
"""

import io
import sys
import urllib.request
from pathlib import Path
from PIL import Image
from mutagen.id3 import ID3, APIC
from mutagen.mp3 import MP3
from dotenv import load_dotenv
import os

load_dotenv()

MUSIC_FOLDER = os.getenv('MUSIC_FOLDER', os.path.expanduser('~/Music'))


def is_jpeg(data: bytes) -> bool:
    return data[:2] == b'\xff\xd8'


THUMB_URLS = [
    'https://i.ytimg.com/vi/{id}/maxresdefault.jpg',
    'https://i.ytimg.com/vi/{id}/hqdefault.jpg',
    'https://i.ytimg.com/vi_webp/{id}/maxresdefault.webp',
]


def embed_jpeg(tags: ID3, image_data: bytes) -> None:
    """Convierte image_data a JPEG y lo escribe como portada frontal."""
    img = Image.open(io.BytesIO(image_data)).convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=90)
    tags['APIC'] = APIC(
        encoding=3,
        mime='image/jpeg',
        type=3,  # Cover (front)
        desc='Cover',
        data=buf.getvalue(),
    )


def recover_artwork(mp3_path: Path, tags: ID3) -> str:
    """
    Descarga la portada de YouTube usando el YouTube ID guardado en los tags.
    Returns: 'recovered', 'no_id', 'download_failed'
    """
    frame = tags.get('TXXX:YouTube ID')
    youtube_id = str(frame).strip() if frame else ''
    if not youtube_id:
        return 'no_id'

    for template in THUMB_URLS:
        try:
            with urllib.request.urlopen(template.format(id=youtube_id), timeout=20) as response:
                image_data = response.read()
            embed_jpeg(tags, image_data)
            tags.save(str(mp3_path))
            return 'recovered'
        except Exception:
            continue

    return 'download_failed'


def fix_artwork(mp3_path: Path, recover: bool = False) -> str:
    """
    Revisa el APIC tag del MP3 y lo convierte a JPEG si no lo es.
    Con recover=True, descarga la portada si no hay ninguna.
    Returns: 'fixed', 'ok', 'no_art', 'recovered', 'no_id', 'download_failed', 'error'
    """
    try:
        try:
            tags = ID3(str(mp3_path))
        except Exception:
            return 'no_art'

        apic_keys = [k for k in tags.keys() if k.startswith('APIC')]
        if not apic_keys:
            return recover_artwork(mp3_path, tags) if recover else 'no_art'

        changed = False
        for key in apic_keys:
            apic = tags[key]
            if is_jpeg(apic.data):
                continue
            # Convertir a JPEG
            img = Image.open(io.BytesIO(apic.data)).convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=90)
            tags[key] = APIC(
                encoding=apic.encoding,
                mime='image/jpeg',
                type=apic.type,
                desc=apic.desc,
                data=buf.getvalue(),
            )
            changed = True

        if changed:
            tags.save(str(mp3_path))
            return 'fixed'
        return 'ok'

    except Exception as e:
        return f'error: {e}'


def main():
    verbose = '--verbose' in sys.argv or '-v' in sys.argv
    recover = '--recover' in sys.argv

    folder = Path(MUSIC_FOLDER)
    mp3_files = sorted(folder.rglob('*.mp3'))
    total = len(mp3_files)
    print(f"Revisando {total} archivos MP3 en: {folder}")
    if recover:
        print("Modo --recover: se descargará la portada de los MP3 que no tengan ninguna")
    print()

    counts = {}

    for i, mp3 in enumerate(mp3_files, 1):
        result = fix_artwork(mp3, recover=recover)
        rel = mp3.relative_to(folder)
        counts[result if not result.startswith('error') else 'error'] = \
            counts.get(result if not result.startswith('error') else 'error', 0) + 1

        if result == 'fixed':
            print(f"[{i:>4}/{total}] ✅ REPARADO   {rel}")
        elif result == 'recovered':
            print(f"[{i:>4}/{total}] 🖼️  DESCARGADA {rel}")
        elif result == 'download_failed':
            print(f"[{i:>4}/{total}] ⚠️  SIN THUMB  {rel}")
        elif result == 'no_id':
            print(f"[{i:>4}/{total}] ⚠️  SIN ID     {rel}")
        elif result.startswith('error'):
            print(f"[{i:>4}/{total}] ❌ ERROR      {rel} → {result}")
        elif verbose:
            etiqueta = 'ya JPEG  ' if result == 'ok' else 'sin arte '
            print(f"[{i:>4}/{total}] ·  {etiqueta}  {rel}")

    print(f"""
Resumen
───────────────────────────────────
  Reparados (WebP→JPEG):    {counts.get('fixed', 0)}
  Portadas descargadas:     {counts.get('recovered', 0)}
  Ya eran JPEG:             {counts.get('ok', 0)}
  Sin artwork:              {counts.get('no_art', 0)}
  Sin YouTube ID:           {counts.get('no_id', 0)}
  Thumbnail no disponible:  {counts.get('download_failed', 0)}
  Errores:                  {counts.get('error', 0)}
  Total:                    {total}
""")


if __name__ == '__main__':
    main()
