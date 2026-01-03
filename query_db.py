#!/usr/bin/env python3
"""
Script de utilidad para consultar la base de datos de música.
Permite buscar canciones, ver estadísticas, etc.
"""

import sys
from database import MusicDatabase
from dotenv import load_dotenv
import os

load_dotenv()

DB_PATH = os.getenv('DB_PATH', None)
db = MusicDatabase(DB_PATH)


def show_statistics():
    """Muestra estadísticas de la base de datos."""
    stats = db.get_statistics()
    
    print("=" * 60)
    print("📊 ESTADÍSTICAS DE LA BASE DE DATOS")
    print("=" * 60)
    print(f"\n🎵 Total de canciones: {stats['total_songs']}")
    print(f"❌ Videos rechazados: {stats['rejected_count']}")
    
    # Tamaño total
    total_size_mb = stats['total_size_bytes'] / (1024 * 1024)
    print(f"💾 Tamaño total: {total_size_mb:.2f} MB")
    
    # Por género
    if stats['by_genre']:
        print("\n📈 Canciones por género:")
        for genre, count in sorted(stats['by_genre'].items(), key=lambda x: x[1], reverse=True):
            print(f"   {genre}: {count}")
    
    # Por década
    if stats['by_decade']:
        print("\n📅 Canciones por década:")
        for decade, count in sorted(stats['by_decade'].items(), reverse=True):
            print(f"   {decade}: {count}")
    
    print()


def search_songs(artist=None, title=None, genre=None, decade=None, limit=20):
    """Busca canciones en la base de datos."""
    songs = db.get_all_songs(limit=limit, genre=genre, decade=decade)
    
    if artist or title:
        # Filtrar por artista o título
        filtered = []
        for song in songs:
            if artist and artist.lower() not in (song.get('artist') or '').lower():
                continue
            if title and title.lower() not in (song.get('title') or '').lower():
                continue
            filtered.append(song)
        songs = filtered
    
    if not songs:
        print("❌ No se encontraron canciones.")
        return
    
    print(f"\n🎵 Se encontraron {len(songs)} canciones:\n")
    print("-" * 80)
    
    for i, song in enumerate(songs, 1):
        print(f"\n[{i}] {song['title']}")
        if song.get('artist'):
            print(f"    Artista: {song['artist']}")
        if song.get('genre'):
            print(f"    Género: {song['genre']}")
        if song.get('year'):
            print(f"    Año: {song['year']} ({song.get('decade', 'N/A')})")
        print(f"    Archivo: {song['file_path']}")
        print(f"    Descargado: {song['downloaded_at']}")
    
    print("\n" + "-" * 80)


def main():
    """Función principal."""
    if len(sys.argv) < 2:
        print("Uso: python query_db.py <comando> [opciones]")
        print("\nComandos disponibles:")
        print("  stats              - Muestra estadísticas de la base de datos")
        print("  search             - Busca canciones")
        print("    --artist ARTISTA - Filtrar por artista")
        print("    --title TÍTULO   - Filtrar por título")
        print("    --genre GÉNERO   - Filtrar por género")
        print("    --decade DÉCADA  - Filtrar por década (ej: 2020s)")
        print("    --limit N        - Limitar resultados (default: 20)")
        print("\nEjemplos:")
        print("  python query_db.py stats")
        print("  python query_db.py search --artist 'Deadmau5'")
        print("  python query_db.py search --genre 'House' --decade '2020s'")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'stats':
        show_statistics()
    
    elif command == 'search':
        # Parsear argumentos
        artist = None
        title = None
        genre = None
        decade = None
        limit = 20
        
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == '--artist' and i + 1 < len(sys.argv):
                artist = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--title' and i + 1 < len(sys.argv):
                title = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--genre' and i + 1 < len(sys.argv):
                genre = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--decade' and i + 1 < len(sys.argv):
                decade = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--limit' and i + 1 < len(sys.argv):
                limit = int(sys.argv[i + 1])
                i += 2
            else:
                i += 1
        
        search_songs(artist=artist, title=title, genre=genre, decade=decade, limit=limit)
    
    else:
        print(f"❌ Comando desconocido: {command}")
        sys.exit(1)
    
    db.close()


if __name__ == '__main__':
    main()

