#!/usr/bin/env python3
"""
Script para descargar canciones de YouTube a MP3 con metadatos completos.
Incluye extracción de artista, año y estilo de música.
"""

import os
import sys
import re
import json
import urllib.parse
import urllib.request
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Tuple
from datetime import datetime
import yt_dlp
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, APIC
from dotenv import load_dotenv
from database import MusicDatabase

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("⚠️  Advertencia: 'requests' no está instalado. Algunas funciones de detección de género pueden no funcionar.")

try:
    import essentia.standard as es
    ESSENTIA_AVAILABLE = True
except ImportError:
    ESSENTIA_AVAILABLE = False
    # No mostrar advertencia aquí, se mostrará solo si se intenta usar

# Cargar variables de entorno
load_dotenv()

# Configuración
MUSIC_FOLDER = os.getenv('MUSIC_FOLDER', os.path.expanduser('~/Music'))
QUALITY = 'bestaudio/best'  # Mejor calidad disponible
DB_PATH = os.getenv('DB_PATH', None)  # None = usar ruta por defecto

# Inicializar base de datos
db = MusicDatabase(DB_PATH)


def get_genre_from_lastfm(artist: str, track: str) -> Optional[str]:
    """
    Intenta obtener el género de la canción usando Last.fm API.
    Nota: Last.fm requiere API key, pero podemos intentar sin ella primero.
    """
    if not REQUESTS_AVAILABLE:
        return None
    
    # Intentar con API key del .env si está disponible
    lastfm_api_key = os.getenv('LASTFM_API_KEY', '')
    
    try:
        url = "http://ws.audioscrobbler.com/2.0/"
        params = {
            'method': 'track.getInfo',
            'artist': artist,
            'track': track,
            'format': 'json'
        }
        
        # Solo añadir API key si está disponible
        if lastfm_api_key:
            params['api_key'] = lastfm_api_key
        
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if 'track' in data and 'toptags' in data['track']:
                tags = data['track']['toptags'].get('tag', [])
                if tags and len(tags) > 0:
                    # Devolver el tag más popular (género)
                    genre = tags[0].get('name', '').title()
                    # Filtrar tags que no son géneros musicales
                    if genre and len(genre) > 2:
                        return genre
    except Exception:
        pass  # Silenciosamente fallar y probar otros métodos
    
    return None


def get_genre_from_web_search(artist: str, track: str) -> Optional[str]:
    """
    Busca el género de la canción mediante búsqueda web.
    Usa múltiples estrategias para encontrar el género.
    """
    if not REQUESTS_AVAILABLE:
        return None
    
    # Géneros comunes a buscar (ordenados por longitud descendente)
    genres = [
        'drum and bass', 'drum & bass', 'progressive house', 'deep house', 'tech house',
        'electro house', 'big room', 'future bass', 'bass house', 'melodic house',
        'progressive trance', 'hard trance', 'uplifting trance', 'vocal trance',
        'hip hop', 'house', 'techno', 'trance', 'dubstep', 'edm', 'minimal',
        'hardstyle', 'hardcore', 'electro', 'trap', 'psytrance',
        'rap', 'r&b', 'pop', 'rock', 'metal', 'jazz', 'blues',
        'reggae', 'salsa', 'bachata', 'reggaeton', 'latin', 'funk', 'disco',
        'ambient', 'downtempo', 'chillout', 'lo-fi', 'synthwave', 'vaporwave'
    ]
    
    search_queries = [
        f"{artist} {track} genre",
        f"{artist} {track} music style",
        f"{artist} {track} music genre",
        f"{artist} genre"
    ]
    
    for query in search_queries:
        try:
            # Intentar con DuckDuckGo (sin API key necesario)
            search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(search_url, headers=headers, timeout=10)
            if response.status_code == 200:
                content = response.text.lower()
                
                # Buscar géneros en el contenido (géneros más largos primero)
                for genre in sorted(genres, key=len, reverse=True):
                    if genre.lower() in content:
                        # Verificar que no sea parte de otra palabra
                        genre_lower = genre.lower()
                        pattern = r'\b' + re.escape(genre_lower) + r'\b'
                        if re.search(pattern, content):
                            return genre.title()
        except Exception:
            continue  # Intentar siguiente query
    
    return None


def get_genre_from_database(artist: Optional[str]) -> Optional[str]:
    """
    Busca el género más común del artista en la base de datos local.
    Si el artista tiene canciones previas, usa su género más frecuente.
    """
    if not artist:
        return None
    
    try:
        # Buscar todas las canciones del artista
        songs = db.find_song(artist=artist)
        if not songs:
            return None
        
        # Contar géneros
        genre_count = {}
        for song in songs:
            genre = song.get('genre')
            if genre and genre.lower() != 'sin clasificar' and genre.lower() != 'unknown':
                genre_count[genre] = genre_count.get(genre, 0) + 1
        
        if genre_count:
            # Devolver el género más común
            most_common = max(genre_count.items(), key=lambda x: x[1])
            return most_common[0]
    except Exception:
        pass
    
    return None


def get_genre_from_video_tags(video_info: Optional[Dict]) -> Optional[str]:
    """
    Extrae el género de los tags del video de YouTube.
    """
    if not video_info:
        return None
    
    tags = video_info.get('tags', [])
    if not tags:
        return None
    
    # Géneros comunes de música electrónica/DJ
    genres = [
        'drum and bass', 'drum & bass', 'progressive house', 'deep house', 'tech house',
        'electro house', 'big room', 'future bass', 'bass house', 'melodic house',
        'progressive trance', 'hard trance', 'uplifting trance', 'vocal trance',
        'hip hop', 'house', 'techno', 'trance', 'dubstep', 'edm', 'minimal',
        'hardstyle', 'hardcore', 'electro', 'trap', 'psytrance',
        'rap', 'r&b', 'pop', 'rock', 'metal', 'jazz', 'blues',
        'reggae', 'salsa', 'bachata', 'reggaeton', 'latin', 'funk', 'disco',
        'ambient', 'downtempo', 'chillout', 'lo-fi', 'synthwave', 'vaporwave'
    ]
    
    tags_text = ' '.join(tags).lower()
    
    # Buscar géneros en los tags (géneros más largos primero)
    for genre in sorted(genres, key=len, reverse=True):
        genre_lower = genre.lower()
        pattern = r'\b' + re.escape(genre_lower) + r'\b'
        if re.search(pattern, tags_text):
            return genre.title()
    
    return None


def get_genre_from_channel_name(video_info: Optional[Dict]) -> Optional[str]:
    """
    Intenta inferir el género basándose en el nombre del canal/uploader.
    Algunos canales tienen géneros específicos en su nombre.
    """
    if not video_info:
        return None
    
    uploader = video_info.get('uploader', '').lower()
    channel = video_info.get('channel', '').lower()
    
    # Mapeo de palabras clave en nombres de canales a géneros
    channel_keywords = {
        'house': 'House',
        'techno': 'Techno',
        'trance': 'Trance',
        'dubstep': 'Dubstep',
        'drum and bass': 'Drum & Bass',
        'dnb': 'Drum & Bass',
        'hardstyle': 'Hardstyle',
        'hardcore': 'Hardcore',
        'edm': 'EDM',
        'hip hop': 'Hip Hop',
        'rap': 'Rap',
        'reggaeton': 'Reggaeton',
        'latin': 'Latin',
        'salsa': 'Salsa',
        'bachata': 'Bachata',
    }
    
    full_text = (uploader + ' ' + channel).lower()
    
    # Buscar palabras clave (más largas primero)
    for keyword, genre in sorted(channel_keywords.items(), key=lambda x: len(x[0]), reverse=True):
        if keyword in full_text:
            return genre
    
    return None


def get_genre_from_title_keywords(title: str) -> Optional[str]:
    """
    Analiza palabras clave en el título para inferir el género.
    Versión mejorada con más géneros y subgéneros.
    """
    title_lower = title.lower()
    
    # Mapeo de palabras clave a géneros (ordenado por especificidad)
    keyword_map = {
        # Subgéneros específicos primero (más largos)
        'tribal afro house': 'Afro House',
        'tribal house': 'Tribal House',
        'afro house': 'Afro House',
        'progressive house': 'Progressive House',
        'deep house': 'Deep House',
        'tech house': 'Tech House',
        'electro house': 'Electro House',
        'future bass': 'Future Bass',
        'bass house': 'Bass House',
        'melodic house': 'Melodic House',
        'big room': 'Big Room',
        'drum and bass': 'Drum & Bass',
        'drum & bass': 'Drum & Bass',
        'progressive trance': 'Progressive Trance',
        'hard trance': 'Hard Trance',
        'uplifting trance': 'Uplifting Trance',
        'vocal trance': 'Vocal Trance',
        'hip hop': 'Hip Hop',
        'trap music': 'Trap',
        'psytrance': 'Psytrance',
        'hardstyle': 'Hardstyle',
        'hardcore': 'Hardcore',
        'minimal techno': 'Minimal Techno',
        'lo-fi': 'Lo-Fi',
        'synthwave': 'Synthwave',
        'vaporwave': 'Vaporwave',
        'future house': 'Future House',
        'bassline': 'Bassline',
        'garage': 'UK Garage',
        'jungle': 'Jungle',
        'dub techno': 'Dub Techno',
        'acid house': 'Acid House',
        'french house': 'French House',
        'ghetto house': 'Ghetto House',
        'baltimore club': 'Baltimore Club',
        'ghetto tech': 'Ghetto Tech',
        'footwork': 'Footwork',
        'juke': 'Juke',
        'gqom': 'Gqom',
        'amapiano': 'Amapiano',
        'afrobeat': 'Afrobeat',
        'afro tech': 'Afro Tech',
        'afro': 'Afro House',  # Genérico para afro
        'tribal': 'Tribal House',  # Genérico para tribal
        
        # Géneros principales
        'house': 'House',
        'techno': 'Techno',
        'trance': 'Trance',
        'dubstep': 'Dubstep',
        'dnb': 'Drum & Bass',
        'edm': 'EDM',
        'rap': 'Rap',
        'reggaeton': 'Reggaeton',
        'latin': 'Latin',
        'salsa': 'Salsa',
        'bachata': 'Bachata',
        'progressive': 'Progressive House',
        'deep': 'Deep House',
        'tech': 'Tech House',
        'electro': 'Electro',
        'trap': 'Trap',
        'melodic': 'Melodic House',
        'minimal': 'Minimal',
        'ambient': 'Ambient',
        'downtempo': 'Downtempo',
        'chillout': 'Chillout',
        'funk': 'Funk',
        'disco': 'Disco',
        'r&b': 'R&B',
        'pop': 'Pop',
        'rock': 'Rock',
        'metal': 'Metal',
        'jazz': 'Jazz',
        'blues': 'Blues',
        'reggae': 'Reggae',
    }
    
    # Buscar palabras clave (más largas primero)
    for keyword, genre in sorted(keyword_map.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, title_lower):
            return genre
    
    return None


def get_genre_from_hashtags(description: str, video_info: Optional[Dict] = None) -> Optional[str]:
    """
    Extrae el género de hashtags en la descripción o tags del video.
    """
    text_to_search = description or ""
    
    # También buscar en tags del video
    if video_info:
        tags = video_info.get('tags', [])
        if tags:
            text_to_search += " " + " ".join(tags)
    
    if not text_to_search:
        return None
    
    text_lower = text_to_search.lower()
    
    # Géneros comunes en hashtags (ordenados por especificidad)
    genre_hashtags = {
        'tribalafrohouse': 'Afro House',
        'tribalhouse': 'Tribal House',
        'afrohouse': 'Afro House',
        'progressivehouse': 'Progressive House',
        'deephouse': 'Deep House',
        'techhouse': 'Tech House',
        'electrohouse': 'Electro House',
        'futurebass': 'Future Bass',
        'basshouse': 'Bass House',
        'melodichouse': 'Melodic House',
        'bigroom': 'Big Room',
        'drumandbass': 'Drum & Bass',
        'drum&bass': 'Drum & Bass',
        'dnb': 'Drum & Bass',
        'progressive': 'Progressive House',
        'hiphop': 'Hip Hop',
        'trapmusic': 'Trap',
        'psytrance': 'Psytrance',
        'hardstyle': 'Hardstyle',
        'hardcore': 'Hardcore',
        'minimaltechno': 'Minimal Techno',
        'lofi': 'Lo-Fi',
        'synthwave': 'Synthwave',
        'vaporwave': 'Vaporwave',
        'futurehouse': 'Future House',
        'ukgarage': 'UK Garage',
        'jungle': 'Jungle',
        'dubtechno': 'Dub Techno',
        'acidhouse': 'Acid House',
        'frenchhouse': 'French House',
        'ghettohouse': 'Ghetto House',
        'baltimoreclub': 'Baltimore Club',
        'ghettotech': 'Ghetto Tech',
        'footwork': 'Footwork',
        'juke': 'Juke',
        'gqom': 'Gqom',
        'amapiano': 'Amapiano',
        'afrobeat': 'Afrobeat',
        'afrotech': 'Afro Tech',
        'house': 'House',
        'techno': 'Techno',
        'trance': 'Trance',
        'dubstep': 'Dubstep',
        'edm': 'EDM',
        'rap': 'Rap',
        'reggaeton': 'Reggaeton',
        'latin': 'Latin',
        'salsa': 'Salsa',
        'bachata': 'Bachata',
        'trap': 'Trap',
        'minimal': 'Minimal',
        'ambient': 'Ambient',
        'downtempo': 'Downtempo',
        'chillout': 'Chillout',
        'funk': 'Funk',
        'disco': 'Disco',
        'r&b': 'R&B',
        'pop': 'Pop',
        'rock': 'Rock',
        'metal': 'Metal',
        'jazz': 'Jazz',
        'blues': 'Blues',
        'reggae': 'Reggae',
    }
    
    # Buscar hashtags (con y sin #)
    for hashtag, genre in sorted(genre_hashtags.items(), key=lambda x: len(x[0]), reverse=True):
        # Buscar como hashtag (#tribalhouse) o como palabra (tribal house)
        patterns = [
            r'#' + re.escape(hashtag) + r'\b',
            r'\b' + re.escape(hashtag.replace('house', ' house').replace('techno', ' techno').replace('trance', ' trance')) + r'\b',
        ]
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return genre
    
    return None


def get_genre_from_description_deep(description: str) -> Optional[str]:
    """
    Análisis más profundo de la descripción del video para encontrar el género.
    Busca patrones específicos y secciones comunes donde se menciona el género.
    """
    if not description:
        return None
    
    description_lower = description.lower()
    
    # Géneros comunes (expandido)
    genres = [
        'tribal afro house', 'tribal house', 'afro house', 'progressive house', 'deep house', 'tech house',
        'electro house', 'big room', 'future bass', 'bass house', 'melodic house',
        'progressive trance', 'hard trance', 'uplifting trance', 'vocal trance',
        'drum and bass', 'drum & bass', 'hip hop', 'house', 'techno', 'trance', 'dubstep', 'edm', 'minimal',
        'hardstyle', 'hardcore', 'electro', 'trap', 'psytrance',
        'rap', 'r&b', 'pop', 'rock', 'metal', 'jazz', 'blues',
        'reggae', 'salsa', 'bachata', 'reggaeton', 'latin', 'funk', 'disco',
        'ambient', 'downtempo', 'chillout', 'lo-fi', 'synthwave', 'vaporwave',
        'future house', 'bassline', 'uk garage', 'jungle', 'dub techno', 'acid house',
        'french house', 'ghetto house', 'baltimore club', 'ghetto tech', 'footwork',
        'juke', 'gqom', 'amapiano', 'afrobeat', 'afro tech'
    ]
    
    # Buscar patrones comunes donde se menciona el género
    genre_patterns = [
        r'genre[:\s]+([^\n,\.]+)',
        r'style[:\s]+([^\n,\.]+)',
        r'categor[yi][:\s]+([^\n,\.]+)',
        r'type[:\s]+([^\n,\.]+)',
        r'#([^\s#]+)',  # Hashtags
    ]
    
    for pattern in genre_patterns:
        matches = re.findall(pattern, description_lower, re.IGNORECASE)
        for match in matches:
            match_text = match.strip()
            # Buscar géneros en el match (géneros más largos primero)
            for genre in sorted(genres, key=len, reverse=True):
                genre_lower = genre.lower()
                if genre_lower in match_text:
                    pattern_boundary = r'\b' + re.escape(genre_lower) + r'\b'
                    if re.search(pattern_boundary, match_text):
                        return genre.title()
    
    # Si no se encontró en patrones específicos, buscar directamente en la descripción
    for genre in sorted(genres, key=len, reverse=True):
        genre_lower = genre.lower()
        pattern = r'\b' + re.escape(genre_lower) + r'\b'
        if re.search(pattern, description_lower):
            return genre.title()
    
    return None


def get_genre_from_musicbrainz(artist: str, track: str) -> Optional[str]:
    """
    Intenta obtener el género usando MusicBrainz API.
    """
    if not REQUESTS_AVAILABLE:
        return None
    
    try:
        # MusicBrainz API (sin API key necesario, pero con rate limiting)
        search_url = "https://musicbrainz.org/ws/2/recording/"
        params = {
            'query': f'artist:"{artist}" AND recording:"{track}"',
            'fmt': 'json',
            'limit': 1
        }
        
        headers = {
            'User-Agent': 'YouTubeMusicDownloader/1.0 (https://example.com)',
            'Accept': 'application/json'
        }
        
        response = requests.get(search_url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if 'recordings' in data and len(data['recordings']) > 0:
                recording = data['recordings'][0]
                # Buscar tags/genres en el recording
                if 'tags' in recording and len(recording['tags']) > 0:
                    # Devolver el tag más popular
                    tags = sorted(recording['tags'], key=lambda x: x.get('count', 0), reverse=True)
                    if tags:
                        genre = tags[0].get('name', '').title()
                        if genre and len(genre) > 2:
                            return genre
    except Exception:
        pass  # Silenciosamente fallar
    
    return None


def get_genre_from_spotify_search(artist: Optional[str], track: str) -> Optional[str]:
    """
    Busca el género en Spotify usando búsqueda web (sin API).
    """
    if not artist or not REQUESTS_AVAILABLE:
        return None
    
    try:
        # Buscar en Spotify vía web scraping
        search_url = f"https://open.spotify.com/search/{urllib.parse.quote(f'{artist} {track}')}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(search_url, headers=headers, timeout=5)
        if response.status_code == 200:
            content = response.text.lower()
            
            # Géneros a buscar
            genres = [
                'tribal afro house', 'tribal house', 'afro house', 'progressive house', 'deep house', 'tech house',
                'electro house', 'big room', 'future bass', 'bass house', 'melodic house',
                'progressive trance', 'hard trance', 'uplifting trance', 'vocal trance',
                'drum and bass', 'drum & bass', 'hip hop', 'house', 'techno', 'trance', 'dubstep', 'edm', 'minimal',
                'hardstyle', 'hardcore', 'electro', 'trap', 'psytrance',
                'rap', 'r&b', 'pop', 'rock', 'metal', 'jazz', 'blues',
                'reggae', 'salsa', 'bachata', 'reggaeton', 'latin', 'funk', 'disco',
                'ambient', 'downtempo', 'chillout', 'lo-fi', 'synthwave', 'vaporwave',
                'future house', 'bassline', 'uk garage', 'jungle', 'dub techno', 'acid house',
                'french house', 'ghetto house', 'baltimore club', 'ghetto tech', 'footwork',
                'juke', 'gqom', 'amapiano', 'afrobeat', 'afro tech'
            ]
            
            for genre in sorted(genres, key=len, reverse=True):
                pattern = r'\b' + re.escape(genre.lower()) + r'\b'
                if re.search(pattern, content):
                    return genre.title()
    except Exception:
        pass
    
    return None


def get_genre_from_essentia(file_path: str) -> Optional[str]:
    """
    Detecta el género musical analizando el archivo de audio con Essentia.
    Usa modelos preentrenados de Essentia (MusicNN) para clasificación de género.
    
    Args:
        file_path: Ruta al archivo de audio (MP3, WAV, etc.)
    
    Returns:
        Género detectado o None si no se puede determinar
    """
    if not ESSENTIA_AVAILABLE:
        return None
    
    if not Path(file_path).exists():
        return None
    
    try:
        # Cargar el archivo de audio
        loader = es.MonoLoader(filename=file_path)
        audio = loader()
        
        # Intentar usar TaggerMusicNN (modelo preentrenado para clasificación)
        # Este modelo clasifica en múltiples etiquetas incluyendo géneros
        try:
            tagger = es.TaggerMusicNN()
            predictions = tagger(audio)
            
            # Mapeo de etiquetas comunes de Essentia a géneros del proyecto
            genre_mapping = {
                # Electronic
                'electronic': 'Electronic',
                'house': 'House',
                'techno': 'Techno',
                'trance': 'Trance',
                'dubstep': 'Dubstep',
                'drum and bass': 'Drum & Bass',
                'drum & bass': 'Drum & Bass',
                'dnb': 'Drum & Bass',
                'hardstyle': 'Hardstyle',
                'hardcore': 'Hardcore',
                'progressive house': 'Progressive House',
                'deep house': 'Deep House',
                'tech house': 'Tech House',
                'electro house': 'Electro House',
                'future bass': 'Future Bass',
                'bass house': 'Bass House',
                'melodic house': 'Melodic House',
                'big room': 'Big Room',
                'progressive trance': 'Progressive Trance',
                'hard trance': 'Hard Trance',
                'uplifting trance': 'Uplifting Trance',
                'vocal trance': 'Vocal Trance',
                'psytrance': 'Psytrance',
                'minimal': 'Minimal',
                'minimal techno': 'Minimal Techno',
                'edm': 'EDM',
                'trap': 'Trap',
                'ambient': 'Ambient',
                'downtempo': 'Downtempo',
                'chillout': 'Chillout',
                'lo-fi': 'Lo-Fi',
                'synthwave': 'Synthwave',
                'vaporwave': 'Vaporwave',
                'future house': 'Future House',
                'uk garage': 'UK Garage',
                'jungle': 'Jungle',
                'dub techno': 'Dub Techno',
                'acid house': 'Acid House',
                'french house': 'French House',
                'ghetto house': 'Ghetto House',
                'baltimore club': 'Baltimore Club',
                'ghetto tech': 'Ghetto Tech',
                'footwork': 'Footwork',
                'juke': 'Juke',
                'gqom': 'Gqom',
                'amapiano': 'Amapiano',
                'afrobeat': 'Afrobeat',
                'afro tech': 'Afro Tech',
                'afro house': 'Afro House',
                'tribal house': 'Tribal House',
                
                # Other genres
                'hip hop': 'Hip Hop',
                'hip-hop': 'Hip Hop',
                'rap': 'Rap',
                'r&b': 'R&B',
                'r and b': 'R&B',
                'pop': 'Pop',
                'rock': 'Rock',
                'metal': 'Metal',
                'jazz': 'Jazz',
                'blues': 'Blues',
                'reggae': 'Reggae',
                'reggaeton': 'Reggaeton',
                'latin': 'Latin',
                'salsa': 'Salsa',
                'bachata': 'Bachata',
                'funk': 'Funk',
                'disco': 'Disco',
            }
            
            # Buscar el género con mayor probabilidad
            if isinstance(predictions, dict):
                # Si es un diccionario, buscar la etiqueta con mayor valor
                best_tag = max(predictions.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0)
                tag_name = best_tag[0].lower()
                
                # Buscar en el mapeo
                for key, genre in genre_mapping.items():
                    if key.lower() in tag_name or tag_name in key.lower():
                        return genre
                
                # Si no está en el mapeo pero parece un género, devolverlo capitalizado
                if best_tag[1] > 0.3:  # Umbral de confianza
                    return tag_name.title()
            
            elif isinstance(predictions, list):
                # Si es una lista, buscar géneros en las etiquetas
                for tag in predictions:
                    if isinstance(tag, (list, tuple)) and len(tag) >= 2:
                        tag_name = str(tag[0]).lower()
                        confidence = float(tag[1]) if len(tag) > 1 else 0.0
                        
                        if confidence > 0.3:  # Umbral de confianza
                            for key, genre in genre_mapping.items():
                                if key.lower() in tag_name or tag_name in key.lower():
                                    return genre
                    elif isinstance(tag, str):
                        tag_lower = tag.lower()
                        for key, genre in genre_mapping.items():
                            if key.lower() in tag_lower or tag_lower in key.lower():
                                return genre
            
        except (AttributeError, RuntimeError, Exception) as e:
            # Si TaggerMusicNN no está disponible, usar análisis de características básicas
            pass
        
        # Método alternativo: análisis de características de audio
        # Extraer características que pueden indicar el género
        try:
            # Extraer tempo (BPM)
            rhythm_extractor = es.RhythmExtractor2013(method="multifeature")
            bpm, beats, beats_confidence, _, beats_intervals = rhythm_extractor(audio)
            
            # Extraer key (tonalidad)
            key_extractor = es.KeyExtractor()
            key, scale, strength = key_extractor(audio)
            
            # Extraer características espectrales
            spectral_centroid = es.SpectralCentroid()
            centroid = spectral_centroid(audio)
            
            # Extraer energía
            energy = es.Energy()
            energy_value = energy(audio)
            
            # Clasificación heurística basada en características
            # Estos valores son aproximados y pueden necesitar ajuste
            avg_centroid = float(sum(centroid) / len(centroid)) if len(centroid) > 0 else 0
            avg_energy = float(sum(energy_value) / len(energy_value)) if len(energy_value) > 0 else 0
            
            # Reglas heurísticas para géneros electrónicos comunes
            if bpm >= 120 and bpm <= 130:
                if avg_energy > 0.5:
                    return 'House'
                else:
                    return 'Deep House'
            elif bpm >= 130 and bpm <= 140:
                if avg_energy > 0.6:
                    return 'Techno'
                else:
                    return 'Tech House'
            elif bpm >= 138 and bpm <= 145:
                return 'Trance'
            elif bpm >= 160 and bpm <= 180:
                return 'Drum & Bass'
            elif bpm >= 140 and bpm <= 150:
                if avg_energy > 0.7:
                    return 'Dubstep'
                else:
                    return 'Trap'
            elif bpm < 100:
                if avg_energy < 0.3:
                    return 'Ambient'
                else:
                    return 'Downtempo'
            
        except Exception as e:
            # Si falla el análisis de características, devolver None
            pass
        
        return None
        
    except Exception as e:
        # Si hay cualquier error, devolver None silenciosamente
        return None


def detect_genre_online(artist: Optional[str], track: str, video_info: Optional[Dict] = None, 
                        title: Optional[str] = None, description: Optional[str] = None) -> Optional[str]:
    """
    Detecta el género de la canción usando múltiples fuentes online y locales.
    Versión mejorada con más métodos de detección.
    """
    print("🔍 Buscando género de la canción...")
    
    # 1. Buscar en la base de datos local (género histórico del artista)
    if artist:
        genre = get_genre_from_database(artist)
        if genre:
            print(f"   ✓ Género encontrado (base de datos local): {genre}")
            return genre
    
    # 2. Buscar en hashtags (descripción + tags del video)
    if description or video_info:
        genre = get_genre_from_hashtags(description or "", video_info)
        if genre:
            print(f"   ✓ Género encontrado (hashtags): {genre}")
            return genre
    
    # 3. Buscar en tags del video de YouTube
    if video_info:
        genre = get_genre_from_video_tags(video_info)
        if genre:
            print(f"   ✓ Género encontrado (tags del video): {genre}")
            return genre
    
    # 4. Buscar en nombre del canal
    if video_info:
        genre = get_genre_from_channel_name(video_info)
        if genre:
            print(f"   ✓ Género encontrado (nombre del canal): {genre}")
            return genre
    
    # 5. Analizar palabras clave del título (mejorado)
    if title:
        genre = get_genre_from_title_keywords(title)
        if genre:
            print(f"   ✓ Género encontrado (palabras clave del título): {genre}")
            return genre
    
    # 6. Análisis profundo de la descripción
    if description:
        genre = get_genre_from_description_deep(description)
        if genre:
            print(f"   ✓ Género encontrado (análisis de descripción): {genre}")
            return genre
    
    # 7. Intentar con Last.fm
    if artist:
        genre = get_genre_from_lastfm(artist, track)
        if genre:
            print(f"   ✓ Género encontrado (Last.fm): {genre}")
            return genre
    
    # 8. Intentar con MusicBrainz
    if artist:
        genre = get_genre_from_musicbrainz(artist, track)
        if genre:
            print(f"   ✓ Género encontrado (MusicBrainz): {genre}")
            return genre
    
    # 9. Buscar en Spotify (búsqueda web)
    if artist:
        genre = get_genre_from_spotify_search(artist, track)
        if genre:
            print(f"   ✓ Género encontrado (Spotify): {genre}")
            return genre
    
    # 10. Búsqueda web como último recurso
    if artist:
        genre = get_genre_from_web_search(artist, track)
        if genre:
            print(f"   ✓ Género encontrado (búsqueda web): {genre}")
            return genre
    
    print("   ⚠️  No se pudo detectar el género automáticamente")
    return None


def detect_genre_from_audio_file(file_path: str) -> Optional[str]:
    """
    Detecta el género usando análisis de audio con Essentia.
    Esta función debe llamarse DESPUÉS de descargar el archivo.
    
    Args:
        file_path: Ruta al archivo de audio descargado
    
    Returns:
        Género detectado o None
    """
    if not ESSENTIA_AVAILABLE:
        return None
    
    if not Path(file_path).exists():
        return None
    
    print("   🎵 Analizando audio con Essentia...")
    genre = get_genre_from_essentia(file_path)
    
    if genre:
        print(f"   ✓ Género detectado (análisis de audio Essentia): {genre}")
        return genre
    else:
        print("   ⚠️  Essentia no pudo detectar el género del audio")
        return None


def get_decade_from_year(year: Optional[str]) -> str:
    """
    Obtiene la década a partir del año.
    Si no hay año, retorna 'Unknown'.
    """
    if not year:
        return 'Unknown'
    
    try:
        year_int = int(year)
        decade = (year_int // 10) * 10
        return f"{decade}s"
    except (ValueError, TypeError):
        return 'Unknown'


def get_output_folder(base_folder: str, genre: Optional[str], year: Optional[str]) -> Path:
    """
    Genera la ruta de la carpeta de salida organizada por género y década.
    Estructura: MUSIC_FOLDER/Género/Década/
    """
    base_path = Path(base_folder)
    
    # Normalizar género
    if not genre or genre.lower() == 'unknown':
        genre = 'Sin Clasificar'
    else:
        genre = sanitize_filename(genre)
    
    # Obtener década
    decade = get_decade_from_year(year)
    
    # Crear estructura de carpetas
    output_folder = base_path / genre / decade
    output_folder.mkdir(parents=True, exist_ok=True)
    
    return output_folder


def extract_metadata_from_title(title: str, description: str = "", video_info: Optional[Dict] = None) -> Dict[str, Optional[str]]:
    """
    Extrae metadatos del título y descripción del video de YouTube.
    
    Patrones comunes:
    - "Artista - Canción (Año)"
    - "Artista - Canción [Año]"
    - "Canción - Artista (Año)"
    
    También intenta extraer el año de los metadatos de YouTube si están disponibles.
    """
    metadata = {
        'artist': None,
        'title': title,
        'year': None,
        'genre': None
    }
    
    # PRIMERO: Intentar extraer el año de los metadatos de YouTube
    if video_info:
        # Intentar obtener el año de release_year (más preciso)
        if video_info.get('release_year'):
            metadata['year'] = str(video_info.get('release_year'))
        # Si no está disponible, intentar con release_date
        elif video_info.get('release_date'):
            release_date = video_info.get('release_date')
            # release_date puede estar en formato YYYYMMDD o YYYY-MM-DD
            if isinstance(release_date, str):
                year_match = re.search(r'(\d{4})', release_date)
                if year_match:
                    metadata['year'] = year_match.group(1)
            elif isinstance(release_date, (int, float)):
                # Si es un timestamp o número, extraer año
                date_str = str(int(release_date))
                if len(date_str) >= 4:
                    year_match = re.search(r'(\d{4})', date_str)
                    if year_match:
                        year = int(year_match.group(1))
                        if 1900 <= year <= 2100:
                            metadata['year'] = str(year)
        # Intentar con release_timestamp (timestamp Unix)
        elif video_info.get('release_timestamp'):
            try:
                from datetime import datetime
                timestamp = video_info.get('release_timestamp')
                if isinstance(timestamp, (int, float)):
                    dt = datetime.fromtimestamp(timestamp)
                    metadata['year'] = str(dt.year)
            except (ValueError, OSError, OverflowError):
                pass  # Si falla, continuar con otros métodos
        # Como último recurso, usar upload_date (año de subida)
        elif video_info.get('upload_date'):
            upload_date = str(video_info.get('upload_date'))
            if len(upload_date) >= 4:
                # upload_date está en formato YYYYMMDD
                year = upload_date[:4]
                if year.isdigit() and 1900 <= int(year) <= 2100:
                    metadata['year'] = year
    
    # Si no se encontró año en los metadatos, intentar extraer del título
    if not metadata['year']:
        year_match = re.search(r'\b(19|20)\d{2}\b', title)
        if year_match:
            metadata['year'] = year_match.group()
            # Remover el año del título para limpiarlo
            title = re.sub(r'\s*[\(\[\-]?\s*(19|20)\d{2}\s*[\)\]\-]?\s*', '', title)
    
    # Patrones comunes de formato: "Artista - Canción"
    # Primero intentar con guión como separador
    if ' - ' in title or ' – ' in title or ' — ' in title:
        parts = re.split(r'\s*[-–—]\s*', title, maxsplit=1)
        if len(parts) == 2:
            # Asumir que el primer parte es el artista
            metadata['artist'] = parts[0].strip()
            metadata['title'] = parts[1].strip()
    
    # Si no se encontró artista, buscar en la descripción
    if not metadata['artist'] and description:
        # Buscar patrones como "Artist:", "Artista:", "By:", etc.
        artist_patterns = [
            r'(?:Artist|Artista|By|Por|Performer|Intérprete)[:\s]+([^\n]+)',
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*[-–—]',  # Nombre propio al inicio
        ]
        for pattern in artist_patterns:
            match = re.search(pattern, description, re.IGNORECASE | re.MULTILINE)
            if match:
                metadata['artist'] = match.group(1).strip()
                break
    
    # Intentar extraer género de la descripción o título
    # Géneros comunes de música electrónica/DJ
    genres = [
        'House', 'Techno', 'Trance', 'Dubstep', 'Drum & Bass', 'Drum and Bass',
        'EDM', 'Progressive House', 'Deep House', 'Tech House', 'Minimal',
        'Hardstyle', 'Hardcore', 'Electro', 'Electro House', 'Big Room',
        'Trap', 'Future Bass', 'Bass House', 'Melodic House', 'Progressive Trance',
        'Psytrance', 'Hard Trance', 'Uplifting Trance', 'Vocal Trance',
        'Hip Hop', 'Rap', 'R&B', 'Pop', 'Rock', 'Metal', 'Jazz', 'Blues',
        'Reggae', 'Salsa', 'Bachata', 'Reggaeton', 'Latin', 'Funk', 'Disco'
    ]
    
    full_text = (title + ' ' + description).lower()
    for genre in genres:
        if genre.lower() in full_text:
            metadata['genre'] = genre
            break
    
    return metadata


def get_video_info(url: str) -> Dict:
    """Obtiene información del video sin descargarlo."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    # Añadir cookies si están disponibles
    cookies_file = get_cookies_file()
    if cookies_file:
        ydl_opts['cookiefile'] = cookies_file
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return info
        except Exception as e:
            error_str = str(e)
            if 'Video unavailable' in error_str or 'not available' in error_str:
                print(f"⚠️  Video no disponible: {url}")
                print("   Posibles causas:")
                print("   - El video fue eliminado o es privado")
                print("   - El video requiere autenticación (verifica tus cookies)")
                print("   - El video está bloqueado geográficamente")
            else:
                print(f"Error al obtener información del video: {e}")
            return {}


def sanitize_filename(filename: str) -> str:
    """Limpia el nombre de archivo para que sea válido en el sistema de archivos."""
    # Remover caracteres no permitidos
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Reemplazar espacios múltiples por uno solo
    filename = re.sub(r'\s+', ' ', filename)
    # Limitar longitud
    if len(filename) > 200:
        filename = filename[:200]
    return filename.strip()


def clean_youtube_url(url: str) -> str:
    """
    Limpia una URL de YouTube eliminando parámetros adicionales después de &.
    
    Args:
        url: URL de YouTube (puede tener parámetros como &list=, &t=, etc.)
    
    Returns:
        URL limpia con solo el parámetro v= (video_id)
    """
    if not url:
        return url
    
    # Parsear la URL
    parsed = urllib.parse.urlparse(url)
    
    # Si es una URL corta de youtu.be
    if 'youtu.be' in parsed.netloc:
        # Extraer el video_id
        video_id = parsed.path.lstrip('/')
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
        return url
    
    # Si es una URL normal de youtube.com
    if 'youtube.com' in parsed.netloc or 'youtu.be' in parsed.netloc:
        # Parsear los parámetros de la query
        query_params = urllib.parse.parse_qs(parsed.query)
        
        # Obtener solo el video_id (parámetro 'v')
        if 'v' in query_params:
            video_id = query_params['v'][0]
            # Construir URL limpia con solo el video_id
            return f"https://www.youtube.com/watch?v={video_id}"
    
    # Si no es una URL de YouTube reconocida, devolverla tal cual
    return url


def check_file_exists(video_id: Optional[str] = None, artist: Optional[str] = None, 
                     title: Optional[str] = None, base_folder: str = None) -> Optional[Dict]:
    """
    Verifica si una canción ya existe en la base de datos.
    
    Args:
        video_id: ID del video de YouTube (más preciso)
        artist: Nombre del artista
        title: Título de la canción
        base_folder: (deprecated, se mantiene por compatibilidad)
    
    Returns:
        Diccionario con los datos de la canción si existe, None si no existe.
    """
    if video_id:
        song = db.get_song_by_video_id(video_id)
        if song:
            # Verificar que el archivo realmente existe
            file_path = Path(song['file_path'])
            if file_path.exists():
                return song
            else:
                # El archivo fue eliminado, actualizar BD
                print(f"⚠️  Archivo en BD no existe: {song['file_path']}")
                # Opcional: eliminar de BD o marcar como eliminado
    
    if artist and title:
        songs = db.find_song(artist=artist, title=title)
        for song in songs:
            file_path = Path(song['file_path'])
            if file_path.exists():
                return song
    
    return None


def download_audio(url: str, output_path: str, metadata: Dict) -> bool:
    """
    Descarga el audio de YouTube y lo convierte a MP3.
    """
    ydl_opts = {
        'format': QUALITY,
        'outtmpl': output_path,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',  # Mejor calidad MP3
        }],
        'quiet': False,
        'progress_hooks': [],
    }
    
    # Añadir cookies si están disponibles
    cookies_file = get_cookies_file()
    if cookies_file:
        ydl_opts['cookiefile'] = cookies_file
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except Exception as e:
        error_str = str(e)
        if 'Video unavailable' in error_str or 'not available' in error_str:
            print(f"❌ Error: Video no disponible: {url}")
            print("   Posibles causas:")
            print("   - El video fue eliminado o es privado")
            print("   - El video requiere autenticación (verifica tus cookies)")
            print("   - El video está bloqueado geográficamente")
            if not cookies_file:
                print("   - No se encontraron cookies (algunos videos requieren autenticación)")
        else:
            print(f"Error al descargar: {e}")
        return False


def check_audio_volume(file_path: str) -> Optional[float]:
    """
    Verifica el volumen promedio del archivo de audio usando ffmpeg.
    
    Returns:
        Volumen promedio en dB (LUFS) o None si hay error.
        Valores típicos: -23.0 LUFS (estándar EBU R128), más bajo = más silencioso
    """
    if not shutil.which('ffmpeg'):
        return None
    
    try:
        # Usar ffmpeg para analizar el volumen (EBU R128 loudness)
        cmd = [
            'ffmpeg',
            '-i', file_path,
            '-af', 'loudnorm=I=-23.0:TP=-2.0:LRA=7.0:print_format=json',
            '-f', 'null',
            '-'
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=60
        )
        
        # Buscar el JSON en la salida
        output = result.stdout + result.stderr
        json_start = output.find('{')
        if json_start != -1:
            json_str = output[json_start:]
            json_end = json_str.rfind('}') + 1
            if json_end > 0:
                data = json.loads(json_str[:json_end])
                # Obtener el input_i (volumen promedio en LUFS)
                input_i = data.get('input_i')
                if input_i is not None:
                    return float(input_i)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, KeyError) as e:
        # Si falla, intentar método alternativo más simple
        pass
    
    # Método alternativo: usar volumedetect
    try:
        cmd = [
            'ffmpeg',
            '-i', file_path,
            '-af', 'volumedetect',
            '-f', 'null',
            '-'
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=60
        )
        
        output = result.stdout + result.stderr
        # Buscar mean_volume en la salida
        match = re.search(r'mean_volume:\s*([-\d.]+)\s*dB', output)
        if match:
            return float(match.group(1))
    except (subprocess.TimeoutExpired, ValueError) as e:
        pass
    
    return None


def normalize_audio_volume(file_path: str, target_lufs: float = -23.0) -> bool:
    """
    Normaliza el volumen del archivo de audio usando ffmpeg loudnorm.
    
    Args:
        file_path: Ruta al archivo MP3
        target_lufs: Nivel objetivo en LUFS (estándar EBU R128: -23.0)
    
    Returns:
        True si se normalizó correctamente, False en caso contrario
    """
    if not shutil.which('ffmpeg'):
        print("   ⚠️  ffmpeg no está disponible, no se puede normalizar el volumen")
        return False
    
    if not Path(file_path).exists():
        return False
    
    try:
        # Crear archivo temporal
        temp_file = str(Path(file_path).with_suffix('.tmp.mp3'))
        
        # Normalizar usando loudnorm (EBU R128)
        cmd = [
            'ffmpeg',
            '-i', file_path,
            '-af', f'loudnorm=I={target_lufs}:TP=-2.0:LRA=7.0',
            '-ar', '44100',  # Mantener sample rate
            '-b:a', '320k',  # Mantener bitrate
            '-y',  # Sobrescribir si existe
            temp_file
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutos máximo
        )
        
        if result.returncode == 0 and Path(temp_file).exists():
            # Reemplazar el archivo original
            Path(file_path).unlink()
            Path(temp_file).rename(file_path)
            return True
        else:
            # Si falla, eliminar el archivo temporal
            if Path(temp_file).exists():
                Path(temp_file).unlink()
            return False
            
    except subprocess.TimeoutExpired:
        print("   ⚠️  Timeout al normalizar el volumen")
        return False
    except Exception as e:
        print(f"   ⚠️  Error al normalizar el volumen: {e}")
        return False


def check_and_normalize_audio(file_path: str, threshold_lufs: float = -26.0) -> bool:
    """
    Verifica el volumen del archivo y lo normaliza si está por debajo del umbral.
    
    Args:
        file_path: Ruta al archivo MP3
        threshold_lufs: Umbral en LUFS. Si el volumen está por debajo de este valor,
                       se normalizará. Por defecto -26.0 (más silencioso que el estándar -23.0)
    
    Returns:
        True si se normalizó o no era necesario, False si hubo error
    """
    print("   🔊 Verificando volumen del audio...")
    
    volume = check_audio_volume(file_path)
    
    if volume is None:
        print("   ⚠️  No se pudo verificar el volumen, normalizando de todas formas...")
        return normalize_audio_volume(file_path)
    
    # Convertir LUFS a dB aproximado para mostrar
    # (LUFS y dB son similares pero no idénticos)
    print(f"   📊 Volumen actual: {volume:.1f} LUFS", end="")
    
    # Si el volumen está por debajo del umbral, normalizar
    if volume < threshold_lufs:
        print(f" (por debajo del umbral de {threshold_lufs} LUFS)")
        print("   🔧 Normalizando volumen...")
        if normalize_audio_volume(file_path):
            print("   ✅ Volumen normalizado correctamente")
            return True
        else:
            print("   ⚠️  No se pudo normalizar el volumen")
            return False
    else:
        print(" (volumen adecuado)")
        return True


def is_rejected_video(video_id: str) -> bool:
    """
    Verifica si un video está en la lista de rechazados.
    """
    return db.is_rejected(video_id)


def save_rejected_video(video_id: str, url: Optional[str] = None, 
                       title: Optional[str] = None, reason: Optional[str] = None):
    """
    Guarda un video ID en la lista de videos rechazados en la base de datos.
    """
    db.add_rejected_video(video_id, url=url, title=title, reason=reason)


def get_cookies_file() -> Optional[str]:
    """
    Busca y retorna la ruta al archivo de cookies de YouTube.
    """
    cookies_file = os.getenv('YOUTUBE_COOKIES_FILE', '')
    if cookies_file and Path(cookies_file).exists():
        return cookies_file
    
    # Buscar en ubicaciones comunes
    possible_cookies = [
        Path.home() / 'youtube_cookies.txt',
        Path.cwd() / 'youtube_cookies.txt',
    ]
    for cookie_path in possible_cookies:
        if cookie_path.exists():
            return str(cookie_path)
    
    return None


def test_cookies() -> bool:
    """
    Prueba si las cookies funcionan correctamente accediendo a YouTube.
    
    Returns:
        True si las cookies funcionan, False en caso contrario.
    """
    cookies_file = get_cookies_file()
    
    if not cookies_file:
        print("❌ No se encontró archivo de cookies.")
        print("   Buscado en:")
        print(f"   - {Path.home() / 'youtube_cookies.txt'}")
        print(f"   - {Path.cwd() / 'youtube_cookies.txt'}")
        print("   - Variable de entorno YOUTUBE_COOKIES_FILE")
        return False
    
    print(f"📋 Archivo de cookies encontrado: {cookies_file}")
    
    # Verificar que el archivo existe y tiene contenido
    cookie_path = Path(cookies_file)
    if not cookie_path.exists():
        print(f"❌ El archivo de cookies no existe: {cookies_file}")
        return False
    
    file_size = cookie_path.stat().st_size
    if file_size == 0:
        print(f"⚠️  El archivo de cookies está vacío: {cookies_file}")
        return False
    
    print(f"   ✓ Tamaño del archivo: {file_size} bytes")
    
    # Probar acceso a YouTube con las cookies
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': cookies_file,
    }
    
    print("\n🔍 Probando acceso a YouTube...")
    
    # Probar diferentes URLs para verificar autenticación
    test_urls = [
        ("Página principal", "https://www.youtube.com/"),
        ("YouTube Music - Lista de me gusta", "https://music.youtube.com/playlist?list=LM"),
        ("Feed de videos que me gustan", "https://www.youtube.com/feed/liked"),
    ]
    
    success_count = 0
    total_tests = len(test_urls)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for name, url in test_urls:
                try:
                    print(f"   Probando: {name}...", end=" ")
                    info = ydl.extract_info(url, download=False)
                    
                    if info:
                        # Verificar si obtuvimos información útil
                        if info.get('entries') or info.get('_type') == 'playlist' or info.get('title'):
                            print("✓ Funciona")
                            success_count += 1
                            
                            # Mostrar información adicional si está disponible
                            if info.get('title'):
                                print(f"      Título: {info.get('title')}")
                            if info.get('entries'):
                                print(f"      Elementos encontrados: {len(info.get('entries', []))}")
                        else:
                            print("⚠️  Acceso pero sin datos")
                    else:
                        print("⚠️  Sin información")
                except Exception as e:
                    error_str = str(e)
                    if '400' in error_str or 'Bad Request' in error_str:
                        print("✗ Error 400 (posiblemente requiere autenticación)")
                    elif 'does not exist' in error_str or '404' in error_str:
                        print("✗ No encontrado")
                    elif '403' in error_str or 'Forbidden' in error_str:
                        print("✗ Prohibido (cookies pueden estar expiradas)")
                    else:
                        print(f"✗ Error: {str(e)[:50]}")
    
    except Exception as e:
        print(f"\n❌ Error general al probar cookies: {e}")
        return False
    
    print(f"\n{'='*60}")
    print(f"📊 Resultados: {success_count}/{total_tests} pruebas exitosas")
    
    if success_count == 0:
        print("\n❌ Las cookies no funcionan correctamente.")
        print("\n💡 Posibles soluciones:")
        print("   1. Las cookies pueden estar expiradas - exporta nuevas cookies")
        print("   2. Asegúrate de estar autenticado en YouTube en tu navegador")
        print("   3. Verifica que el archivo de cookies tenga el formato correcto (Netscape)")
        print("   4. Prueba exportar las cookies nuevamente con una extensión como:")
        print("      - 'Get cookies.txt LOCALLY' (Chrome/Edge)")
        print("      - 'cookies.txt' (Firefox)")
        return False
    elif success_count < total_tests:
        print("\n⚠️  Algunas pruebas fallaron, pero hay acceso parcial.")
        print("   Esto puede ser normal si algunas URLs requieren permisos especiales.")
        return True
    else:
        print("\n✅ ¡Las cookies funcionan correctamente!")
        return True


def get_user_playlists() -> list:
    """
    Obtiene todas las playlists del usuario autenticado.
    
    Returns:
        Lista de diccionarios con información de cada playlist.
    """
    cookies_file = get_cookies_file()
    
    if not cookies_file:
        print("⚠️  No se encontró archivo de cookies.")
        return []
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': cookies_file,
    }
    
    # Intentar obtener el canal del usuario desde las cookies
    # Primero intentamos obtener el canal desde la página de inicio
    urls_to_try = [
        "https://www.youtube.com/feed/library",  # Biblioteca del usuario
        "https://www.youtube.com/feed/history",  # Historial
    ]
    
    playlists = []
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Intentar obtener información del usuario
            for url in urls_to_try:
                try:
                    info = ydl.extract_info(url, download=False)
                    # Buscar playlists en la información
                    if info:
                        # Intentar extraer playlists de diferentes formas
                        if 'entries' in info:
                            for entry in info.get('entries', []):
                                if entry and entry.get('_type') == 'playlist':
                                    playlists.append({
                                        'id': entry.get('id', ''),
                                        'title': entry.get('title', ''),
                                        'url': entry.get('url', ''),
                                    })
                except Exception:
                    continue
    except Exception as e:
        print(f"⚠️  Error al obtener playlists: {e}")
    
    return playlists


def find_liked_playlist_url() -> Optional[str]:
    """
    Busca la URL de la playlist de "me gusta" del usuario.
    
    Returns:
        URL de la playlist de "me gusta" o None si no se encuentra.
    """
    cookies_file = get_cookies_file()
    
    if not cookies_file:
        return None
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': cookies_file,
    }
    
    # URLs comunes para la lista de "me gusta"
    # La lista de "me gusta" puede tener diferentes IDs dependiendo del usuario
    urls_to_try = [
        "https://music.youtube.com/playlist?list=LM",  # YouTube Music (más común)
        "https://www.youtube.com/playlist?list=LL",  # Formato común
        "https://www.youtube.com/feed/liked",  # Feed de videos que te gustan
    ]
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for url in urls_to_try:
                try:
                    info = ydl.extract_info(url, download=False)
                    if info and (info.get('entries') or info.get('_type') == 'playlist'):
                        # Si tiene entries o es una playlist, es válida
                        return url
                except Exception as e:
                    # Si el error es que no existe, continuar con la siguiente
                    if 'does not exist' in str(e) or '400' in str(e):
                        continue
                    # Si es otro error, intentar de todas formas
                    pass
    except Exception:
        pass
    
    # Si no funciona con URLs directas, intentar buscar en el canal del usuario
    # Esto requiere obtener el ID del canal primero
    return None


def list_user_playlists():
    """
    Lista todas las playlists del usuario y muestra información útil.
    """
    cookies_file = get_cookies_file()
    
    if not cookies_file:
        print("❌ No se encontró archivo de cookies.")
        print("   Para acceder a tus playlists, necesitas exportar tus cookies de YouTube.")
        print("   Puedes usar una extensión del navegador como 'Get cookies.txt LOCALLY'")
        print("   y guardar el archivo como 'youtube_cookies.txt' en tu directorio home o actual.")
        return
    
    print(f"📋 Usando cookies desde: {cookies_file}")
    print("🔍 Buscando playlists...\n")
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': cookies_file,
    }
    
    playlists_found = []
    
    # URLs a probar para encontrar playlists
    test_urls = [
        ("Biblioteca", "https://www.youtube.com/feed/library"),
        ("Historial", "https://www.youtube.com/feed/history"),
    ]
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for name, url in test_urls:
                try:
                    print(f"🔍 Probando: {name}...")
                    info = ydl.extract_info(url, download=False)
                    if info:
                        print(f"   ✓ Acceso a {name} disponible")
                        # Intentar extraer playlists si están disponibles
                        if 'entries' in info:
                            entries = info.get('entries', [])
                            print(f"   📋 Se encontraron {len(entries)} elementos")
                except Exception as e:
                    error_str = str(e)
                    if '400' in error_str or 'does not exist' in error_str:
                        print(f"   ⚠️  {name} no accesible con esta URL")
                    else:
                        print(f"   ⚠️  Error: {e}")
            
            # Intentar obtener información del canal del usuario
            print("\n🔍 Intentando obtener información del canal...")
            try:
                # Intentar con la página de inicio que puede tener información del usuario
                channel_info = ydl.extract_info("https://www.youtube.com/", download=False)
                if channel_info:
                    print("   ✓ Se puede acceder a YouTube")
            except Exception as e:
                print(f"   ⚠️  Error: {e}")
            
            # Probar URLs específicas de playlists conocidas
            print("\n🔍 Probando URLs específicas de 'me gusta'...")
            liked_urls = [
                "https://music.youtube.com/playlist?list=LM",  # YouTube Music
                "https://www.youtube.com/feed/liked",  # Feed de videos que te gustan
                "https://www.youtube.com/playlist?list=LL",  # Lista de "me gusta" (formato común)
            ]
            
            for url in liked_urls:
                try:
                    info = ydl.extract_info(url, download=False)
                    if info and (info.get('entries') or info.get('_type') == 'playlist'):
                        print(f"   ✓ URL funciona: {url}")
                        if info.get('title'):
                            print(f"      Título: {info.get('title')}")
                        if info.get('entries'):
                            print(f"      Videos: {len(info.get('entries', []))}")
                        playlists_found.append({
                            'url': url,
                            'title': info.get('title', 'Lista de me gusta'),
                            'count': len(info.get('entries', []))
                        })
                except Exception as e:
                    error_str = str(e)
                    if 'does not exist' in error_str or '400' in error_str:
                        print(f"   ✗ No funciona: {url}")
                    else:
                        print(f"   ⚠️  Error con {url}: {e}")
    
    except Exception as e:
        print(f"❌ Error general: {e}")
    
    # Mostrar resumen
    print("\n" + "=" * 60)
    if playlists_found:
        print("✅ Playlists encontradas:")
        for i, pl in enumerate(playlists_found, 1):
            print(f"   {i}. {pl['title']}")
            print(f"      URL: {pl['url']}")
            print(f"      Videos: {pl['count']}")
    else:
        print("⚠️  No se encontraron playlists accesibles automáticamente.")
        print("\n💡 Sugerencias:")
        print("   1. Asegúrate de que tus cookies estén actualizadas")
        print("   2. Verifica que estés autenticado en YouTube")
        print("   3. Puedes probar manualmente accediendo a:")
        print("      - https://www.youtube.com/feed/liked")
        print("      - https://www.youtube.com/playlist?list=LL")
        print("   4. Si conoces el ID de tu playlist de 'me gusta', puedes usarlo directamente")


def get_liked_videos_from_url(playlist_url: str, limit: int = 20) -> list:
    """
    Obtiene videos de una playlist específica usando su URL.
    
    Args:
        playlist_url: URL de la playlist
        limit: Número máximo de videos a obtener
    """
    cookies_file = get_cookies_file()
    
    if not cookies_file:
        print("⚠️  No se encontró archivo de cookies.")
        return []
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'playlistend': limit,
        'cookiefile': cookies_file,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"🔍 Obteniendo videos de: {playlist_url}")
            info = ydl.extract_info(playlist_url, download=False)
            
            if not info or not info.get('entries'):
                print(f"❌ No se pudieron obtener videos de la playlist")
                return []
            
            entries = info.get('entries', [])
            videos = []
            
            for entry in entries[:limit]:
                if entry:
                    video_id = entry.get('id', '')
                    if not video_id:
                        continue
                    
                    title = entry.get('title', 'Unknown')
                    url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    videos.append({
                        'id': video_id,
                        'title': title,
                        'url': url
                    })
            
            return videos
    except Exception as e:
        print(f"❌ Error al obtener videos: {e}")
        return []


def get_liked_videos(limit: int = 20) -> list:
    """
    Obtiene las últimas canciones de la lista de 'me gusta' de YouTube.
    
    Nota: Requiere cookies de sesión de YouTube. El usuario debe exportar sus cookies
    desde el navegador y guardarlas en un archivo (formato Netscape).
    """
    cookies_file = get_cookies_file()
    
    if not cookies_file:
        print("⚠️  Advertencia: No se encontró archivo de cookies.")
        print("   Para acceder a tu lista de 'me gusta', necesitas exportar tus cookies de YouTube.")
        print("   Puedes usar una extensión del navegador como 'Get cookies.txt LOCALLY'")
        print("   y guardar el archivo como 'youtube_cookies.txt' en tu directorio home o actual.")
        print("   O establecer la variable de entorno YOUTUBE_COOKIES_FILE con la ruta al archivo.")
        return []
    
    print(f"📋 Usando cookies desde: {cookies_file}")
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'playlistend': limit,
        'cookiefile': cookies_file,
    }
    
    # Primero intentar encontrar la URL correcta de la playlist de "me gusta"
    liked_url = find_liked_playlist_url()
    
    # URLs a intentar (en orden de preferencia)
    urls_to_try = []
    if liked_url:
        urls_to_try.append(liked_url)
    
    # Añadir URLs alternativas (incluyendo YouTube Music)
    urls_to_try.extend([
        "https://music.youtube.com/playlist?list=LM",  # Lista de "me gusta" de YouTube Music
        "https://www.youtube.com/feed/liked",  # Feed de videos que te gustan
        "https://www.youtube.com/playlist?list=LL",  # Lista de "me gusta" (formato común)
    ])
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = None
            last_error = None
            
            # Intentar con cada URL
            for url in urls_to_try:
                try:
                    print(f"🔍 Intentando con: {url}")
                    info = ydl.extract_info(url, download=False)
                    if info and info.get('entries'):
                        print(f"✓ Playlist encontrada!")
                        break
                except Exception as e:
                    last_error = e
                    error_str = str(e)
                    # Si es un error de "no existe" o "400", continuar
                    if 'does not exist' in error_str or '400' in error_str:
                        print(f"   ⚠️  Esta URL no funciona")
                        continue
                    print(f"   ⚠️  Error: {e}")
                    continue
            
            if not info or not info.get('entries'):
                print(f"\n❌ No se pudo obtener la lista de 'me gusta'")
                print(f"   Último error: {last_error}")
                print("\n💡 Opciones:")
                print("   1. Verifica que tus cookies estén actualizadas (exporta nuevas cookies)")
                print("   2. Intenta acceder manualmente a tu lista de 'me gusta' en YouTube")
                print("   3. Usa --list-playlists para ver tus playlists disponibles")
                return []
            
            entries = info.get('entries', [])
            videos = []
            
            for entry in entries[:limit]:
                if entry:
                    video_id = entry.get('id', '')
                    if not video_id:
                        continue
                    
                    title = entry.get('title', 'Unknown')
                    # Construir URL completa
                    url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    videos.append({
                        'id': video_id,
                        'title': title,
                        'url': url
                    })
            
            return videos
    except Exception as e:
        print(f"❌ Error al obtener videos de 'me gusta': {e}")
        return []


def monitor_liked_videos(playlist_url: Optional[str] = None):
    """
    Monitorea la lista de 'me gusta' de YouTube y verifica si las últimas 20
    canciones están descargadas. Pregunta al usuario si quiere descargar las que faltan.
    
    Args:
        playlist_url: URL opcional de la playlist de "me gusta" si se conoce.
    """
    print("🎵 Monitoreando lista de 'me gusta' de YouTube...")
    print("=" * 60)
    
    # Si se proporciona una URL, usarla directamente
    if playlist_url:
        print(f"📋 Usando URL proporcionada: {playlist_url}")
        liked_videos = get_liked_videos_from_url(playlist_url, limit=20)
    else:
        # Obtener las últimas 20 canciones
        liked_videos = get_liked_videos(limit=20)
    
    if not liked_videos:
        print("❌ No se pudieron obtener las canciones de 'me gusta'.")
        return
    
    print(f"✓ Se encontraron {len(liked_videos)} canciones en tu lista de 'me gusta'\n")
    
    # Verificar cada canción
    videos_to_download = []
    
    for i, video in enumerate(liked_videos, 1):
        video_id = video['id']
        title = video['title']
        url = video['url']
        
        print(f"[{i}/{len(liked_videos)}] {title}")
        
        # Verificar si está rechazado
        if is_rejected_video(video_id):
            print(f"   ⊘ Rechazada anteriormente (se omite)")
            print()
            continue
        
        # Verificar si ya está descargada (usando BD)
        existing_song = check_file_exists(video_id=video_id)
        if existing_song:
            print(f"   ✓ Ya está descargada: {existing_song['file_path']}")
            print()
            continue
        
        # Obtener información del video para extraer metadatos
        video_info = get_video_info(url)
        if not video_info:
            print(f"   ⚠️  No se pudo obtener información del video")
            print()
            continue
        
        title_from_info = video_info.get('title', title)
        description = video_info.get('description', '')
        metadata = extract_metadata_from_title(title_from_info, description, video_info)
        
        # Verificar también por artista y título (por si el video_id cambió)
        if metadata.get('artist') and metadata.get('title'):
            existing_song = check_file_exists(
                artist=metadata.get('artist'),
                title=metadata.get('title', title_from_info)
            )
            if existing_song:
                print(f"   ✓ Ya está descargada (por título): {existing_song['file_path']}")
                print()
                continue
        
        print(f"   ✗ No está descargada")
        videos_to_download.append({
            'video': video,
            'video_info': video_info,
            'metadata': metadata
        })
        print()
    
    # Si hay videos para descargar, preguntar al usuario
    if not videos_to_download:
        print("✅ Todas las canciones están descargadas o han sido rechazadas anteriormente.")
        return
    
    print(f"\n📥 Se encontraron {len(videos_to_download)} canciones no descargadas.\n")
    
    for item in videos_to_download:
        video = item['video']
        video_info = item['video_info']
        metadata = item['metadata']
        
        title = video_info.get('title', video['title'])
        artist = metadata.get('artist', 'Desconocido')
        
        # Mostrar portada al principio si está disponible
        thumbnail_url = video_info.get('thumbnail')
        if thumbnail_url:
            print(f"\n🖼️  Portada disponible: {thumbnail_url}")
            # Intentar mostrar la imagen si hay soporte en el terminal
            try:
                # Verificar si hay herramientas para mostrar imágenes
                import subprocess
                import shutil
                
                # Intentar con imgcat (iTerm2) o similar
                if shutil.which('imgcat'):
                    try:
                        import urllib.request
                        import tempfile
                        with urllib.request.urlopen(thumbnail_url) as response:
                            img_data = response.read()
                            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                                tmp.write(img_data)
                                tmp_path = tmp.name
                            subprocess.run(['imgcat', tmp_path], check=False, capture_output=True)
                            import os
                            os.unlink(tmp_path)
                    except:
                        pass
                # Intentar con w3mimgdisplay (si está disponible)
                elif shutil.which('w3mimgdisplay'):
                    try:
                        import urllib.request
                        import tempfile
                        with urllib.request.urlopen(thumbnail_url) as response:
                            img_data = response.read()
                            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                                tmp.write(img_data)
                                tmp_path = tmp.name
                            subprocess.run(['w3mimgdisplay', tmp_path], check=False, capture_output=True)
                            import os
                            os.unlink(tmp_path)
                    except:
                        pass
            except:
                pass  # Si no se puede mostrar, continuar sin error
        
        print(f"\n🎵 {title}")
        if artist != 'Desconocido':
            print(f"   Artista: {artist}")
        
        while True:
            response = input("   ¿Quieres descargarla? (s/n/skip): ").strip().lower()
            
            if response == 's' or response == 'si' or response == 'sí':
                # Descargar la canción
                print(f"\n📥 Descargando: {title}")
                url = video['url']
                
                # Verificar si el archivo ya existe (por si acaso)
                existing_song = check_file_exists(
                    video_id=video['id'],
                    artist=metadata.get('artist'),
                    title=metadata.get('title', title)
                )
                
                if existing_song:
                    print(f"⚠️  El archivo ya existe: {existing_song['file_path']}")
                    continue
                
                # Si no hay género, intentar detectarlo online
                if not metadata.get('genre') and metadata.get('artist'):
                    detected_genre = detect_genre_online(
                        metadata.get('artist'), 
                        metadata.get('title', title),
                        video_info=video_info,
                        title=title,
                        description=video_info.get('description', '')
                    )
                    if detected_genre:
                        metadata['genre'] = detected_genre
                    else:
                        user_genre = input("   ¿Qué género es esta canción? (deja vacío para 'Sin Clasificar'): ").strip()
                        metadata['genre'] = user_genre if user_genre else 'Sin Clasificar'
                
                # Si no hay año, preguntar o usar año actual
                if not metadata.get('year'):
                    print("   ⚠️  No se pudo detectar el año desde los metadatos de YouTube.")
                    user_year = input("   ¿En qué año se publicó? (deja vacío para usar año actual): ").strip()
                    if user_year:
                        metadata['year'] = user_year
                    else:
                        metadata['year'] = str(datetime.now().year)
                else:
                    print(f"   📅 Año detectado desde metadatos de YouTube: {metadata.get('year')}")
                
                # Obtener carpeta de salida
                output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))
                
                # Crear nombre de archivo
                if metadata.get('artist'):
                    filename = f"{metadata['artist']} - {metadata['title']}"
                else:
                    filename = metadata['title']
                
                filename = sanitize_filename(filename)
                output_path = output_folder / filename
                
                # Descargar
                if download_audio(url, str(output_path), metadata):
                    mp3_file = Path(str(output_path) + '.mp3')
                    if not mp3_file.exists():
                        mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
                        if mp3_files:
                            mp3_file = mp3_files[0]
                        else:
                            print("   ❌ Error: No se encontró el archivo descargado.")
                            break
                    
                    # Verificar y normalizar volumen si es necesario
                    check_and_normalize_audio(str(mp3_file))
                    
                    # Si no se detectó género, intentar con Essentia (análisis de audio)
                    if not metadata.get('genre') or metadata.get('genre', '').lower() in ['sin clasificar', 'unknown', '']:
                        detected_genre = detect_genre_from_audio_file(str(mp3_file))
                        if detected_genre:
                            metadata['genre'] = detected_genre
                    
                    print("   🏷️  Añadiendo metadatos...")
                    add_id3_tags(str(mp3_file), metadata, video_info)
                    
                    # Registrar en base de datos
                    print("   💾 Registrando en base de datos...")
                    register_song_in_db(video['id'], url, mp3_file, metadata, video_info, download_source='playlist')
                    
                    print(f"   ✅ Descarga completada: {mp3_file}")
                else:
                    print("   ❌ Error en la descarga.")
                break
                
            elif response == 'n' or response == 'no':
                # Guardar como rechazada
                save_rejected_video(video['id'], url=video['url'], title=title)
                print(f"   ⊘ Guardada como rechazada (no se volverá a preguntar)")
                break
                
            elif response == 'skip' or response == '':
                # Saltar esta canción (no guardar como rechazada)
                print(f"   ⏭️  Saltada (se preguntará de nuevo la próxima vez)")
                break
                
            else:
                print("   Por favor, responde 's' (sí), 'n' (no) o 'skip' (saltar)")
    
    print("\n✅ Monitoreo completado.")


def register_song_in_db(video_id: str, url: str, file_path: Path, metadata: Dict, video_info: Dict, download_source: Optional[str] = None):
    """
    Registra una canción descargada en la base de datos.
    
    Args:
        video_id: ID del video de YouTube
        url: URL del video
        file_path: Ruta al archivo descargado
        metadata: Diccionario con metadatos (title, artist, year, genre)
        video_info: Información del video de YouTube
        download_source: Origen de la descarga ('playlist' o 'puntual')
    """
    # Limpiar URL (quitar parámetros adicionales después de &)
    clean_url = clean_youtube_url(url)
    
    # Obtener información del archivo
    file_size = None
    file_type = None
    if file_path.exists():
        file_size = file_path.stat().st_size
        # Obtener extensión del archivo (tipo)
        file_type = file_path.suffix.lstrip('.').upper() if file_path.suffix else None
    
    # Obtener duración del video si está disponible
    duration = video_info.get('duration')
    
    # Obtener thumbnail
    thumbnail_url = video_info.get('thumbnail')
    
    # Obtener descripción
    description = video_info.get('description', '')
    if len(description) > 1000:  # Limitar tamaño
        description = description[:1000]
    
    # Obtener década
    decade = get_decade_from_year(metadata.get('year'))
    
    # Registrar en BD
    success = db.add_song(
        video_id=video_id,
        url=clean_url,
        title=metadata.get('title', video_info.get('title', 'Unknown')),
        file_path=str(file_path),
        artist=metadata.get('artist'),
        year=metadata.get('year'),
        genre=metadata.get('genre'),
        decade=decade,
        file_size=file_size,
        file_type=file_type,
        duration=duration,
        thumbnail_url=thumbnail_url,
        description=description,
        download_source=download_source
    )
    
    if not success:
        print(f"⚠️  Advertencia: La canción ya existe en la base de datos o hubo un error al registrarla.")


def add_id3_tags(file_path: str, metadata: Dict, video_info: Dict):
    """
    Añade tags ID3 al archivo MP3.
    """
    try:
        audio = MP3(file_path, ID3=ID3)
    except:
        audio = MP3(file_path)
        audio.add_tags()
    
    # Añadir tags básicos
    if metadata.get('title'):
        audio['TIT2'] = TIT2(encoding=3, text=metadata['title'])
    
    if metadata.get('artist'):
        audio['TPE1'] = TPE1(encoding=3, text=metadata['artist'])
    
    if metadata.get('year'):
        audio['TDRC'] = TDRC(encoding=3, text=metadata['year'])
    
    if metadata.get('genre'):
        audio['TCON'] = TCON(encoding=3, text=metadata['genre'])
    
    # Añadir álbum si está disponible
    if video_info.get('uploader'):
        audio['TALB'] = TALB(encoding=3, text=f"YouTube - {video_info.get('uploader', 'Unknown')}")
    
    # Intentar añadir thumbnail como portada
    if video_info.get('thumbnail'):
        try:
            import urllib.request
            with urllib.request.urlopen(video_info['thumbnail']) as response:
                image_data = response.read()
                audio['APIC'] = APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,  # Cover (front)
                    desc='Cover',
                    data=image_data
                )
        except:
            pass  # Si falla, continuar sin portada
    
    audio.save()


def read_id3_tags(file_path: str) -> Dict[str, Optional[str]]:
    """
    Lee las etiquetas ID3 de un archivo MP3.
    
    Returns:
        Diccionario con los metadatos encontrados: title, artist, year, genre
    """
    metadata = {
        'title': None,
        'artist': None,
        'year': None,
        'genre': None
    }
    
    try:
        audio = MP3(file_path, ID3=ID3)
        
        # Leer título (TIT2)
        if 'TIT2' in audio:
            metadata['title'] = str(audio['TIT2'][0])
        
        # Leer artista (TPE1)
        if 'TPE1' in audio:
            metadata['artist'] = str(audio['TPE1'][0])
        
        # Leer año (TDRC)
        if 'TDRC' in audio:
            year_str = str(audio['TDRC'][0])
            # Extraer año si es una fecha completa
            year_match = re.search(r'(\d{4})', year_str)
            if year_match:
                metadata['year'] = year_match.group(1)
        
        # Leer género (TCON)
        if 'TCON' in audio:
            metadata['genre'] = str(audio['TCON'][0])
    
    except Exception:
        # Si no hay tags ID3 o hay error, devolver diccionario vacío
        pass
    
    return metadata


def search_youtube_music_url(artist: str, title: str) -> Optional[str]:
    """
    Busca la URL de YouTube Music para una canción usando DuckDuckGo.
    
    Args:
        artist: Nombre del artista
        title: Título de la canción
    
    Returns:
        URL de YouTube Music si se encuentra, None en caso contrario
    """
    if not REQUESTS_AVAILABLE:
        return None
    
    search_query = f"{artist} {title} site:music.youtube.com"
    
    try:
        # Buscar en DuckDuckGo
        search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(search_query)}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(search_url, headers=headers, timeout=10)
        if response.status_code == 200:
            content = response.text
            
            # Buscar URLs de YouTube Music en el contenido
            # Patrón para encontrar URLs de music.youtube.com
            pattern = r'https://music\.youtube\.com/watch\?v=[a-zA-Z0-9_-]+'
            matches = re.findall(pattern, content)
            
            if matches:
                # Devolver la primera URL encontrada
                return matches[0]
            
            # También buscar enlaces que puedan contener la URL
            # Buscar enlaces con href que apunten a music.youtube.com
            href_pattern = r'href=["\'](https://music\.youtube\.com/[^"\']+)["\']'
            href_matches = re.findall(href_pattern, content)
            
            if href_matches:
                return href_matches[0]
    
    except Exception:
        pass
    
    return None


def process_imported_mp3(file_path: Path, base_folder: str, 
                         existing_metadata: Optional[Dict] = None,
                         video_info: Optional[Dict] = None) -> Optional[bool]:
    """
    Procesa un archivo MP3 importado: lo copia a la carpeta correcta,
    actualiza metadatos si es necesario y lo registra en la base de datos.
    
    Args:
        file_path: Ruta al archivo MP3
        base_folder: Carpeta base de música
        existing_metadata: Metadatos existentes del archivo (si ya tiene ID3 tags)
        video_info: Información del video de YouTube (si se obtuvo)
    
    Returns:
        True si se procesó correctamente, None si el archivo ya existe, False en caso de error
    """
    try:
        # Leer metadatos existentes si no se proporcionaron
        if not existing_metadata:
            existing_metadata = read_id3_tags(str(file_path))
        
        # Si no hay metadatos suficientes, intentar obtenerlos
        metadata = existing_metadata.copy()
        
        # Si falta información, intentar obtenerla
        if not metadata.get('artist') or not metadata.get('title'):
            # Intentar extraer del nombre del archivo
            filename = file_path.stem
            if ' - ' in filename:
                parts = filename.split(' - ', 1)
                if not metadata.get('artist'):
                    metadata['artist'] = parts[0].strip()
                if not metadata.get('title'):
                    metadata['title'] = parts[1].strip()
            else:
                if not metadata.get('title'):
                    metadata['title'] = filename
        
        # Verificar si el género ya fue detectado y es válido (viene en existing_metadata)
        # Si existing_metadata tiene un género válido (no genérico), usarlo
        existing_genre = existing_metadata.get('genre', '').strip() if existing_metadata else ''
        genre_is_valid = (existing_genre and 
                          existing_genre.lower() not in ['unknown', 'desconocido', 'sin clasificar', ''] and
                          len(existing_genre) >= 2)
        
        # Si no hay género válido o el género es genérico/vacío, intentar detectarlo
        current_genre = metadata.get('genre', '').strip()
        if not genre_is_valid and (not current_genre or 
            current_genre.lower() in ['unknown', 'desconocido', 'sin clasificar', ''] or
            len(current_genre) < 2) and metadata.get('artist'):
            detected_genre = detect_genre_online(
                metadata.get('artist'),
                metadata.get('title', ''),
                video_info=video_info,
                title=metadata.get('title', ''),
                description=""
            )
            if detected_genre:
                metadata['genre'] = detected_genre
            else:
                metadata['genre'] = 'Sin Clasificar'
        elif not current_genre and not genre_is_valid:
            # Si no hay artista, usar 'Sin Clasificar'
            metadata['genre'] = 'Sin Clasificar'
        elif genre_is_valid:
            # Si el género ya detectado es válido, asegurarse de que se use
            metadata['genre'] = existing_genre
        
        # Si no hay año, usar año actual
        if not metadata.get('year'):
            metadata['year'] = str(datetime.now().year)
        
        # Obtener carpeta de destino
        output_folder = get_output_folder(base_folder, metadata.get('genre'), metadata.get('year'))
        
        # Crear nombre de archivo
        if metadata.get('artist'):
            filename = f"{metadata['artist']} - {metadata['title']}"
        else:
            filename = metadata['title']
        
        filename = sanitize_filename(filename)
        new_file_path = output_folder / f"{filename}.mp3"
        
        # Si el archivo ya está en la ubicación correcta, no copiarlo
        if file_path == new_file_path:
            # Si no se detectó género o es genérico, intentar con Essentia
            if (not metadata.get('genre') or 
                metadata.get('genre', '').lower() in ['sin clasificar', 'unknown', 'desconocido', '']):
                detected_genre = detect_genre_from_audio_file(str(file_path))
                if detected_genre:
                    metadata['genre'] = detected_genre
            
            # Solo actualizar metadatos si es necesario
            if video_info:
                add_id3_tags(str(file_path), metadata, video_info or {})
            final_file_path = file_path
        else:
            # Verificar si el archivo ya existe exactamente (sin variaciones)
            if new_file_path.exists():
                # El archivo ya existe, omitirlo
                return None
            
            # Copiar el archivo a la nueva ubicación
            # Si ya existe un archivo con ese nombre, añadir número
            counter = 1
            original_new_path = new_file_path
            while new_file_path.exists():
                new_file_path = output_folder / f"{filename} ({counter}).mp3"
                counter += 1
            
            shutil.copy2(str(file_path), str(new_file_path))
            
            # Si no se detectó género o es genérico, intentar con Essentia
            if (not metadata.get('genre') or 
                metadata.get('genre', '').lower() in ['sin clasificar', 'unknown', 'desconocido', '']):
                detected_genre = detect_genre_from_audio_file(str(new_file_path))
                if detected_genre:
                    metadata['genre'] = detected_genre
                    # Si cambió el género, actualizar la carpeta de destino
                    output_folder = get_output_folder(base_folder, metadata.get('genre'), metadata.get('year'))
                    if new_file_path.parent != output_folder:
                        # Copiar a la carpeta correcta según el nuevo género
                        new_filename = output_folder / new_file_path.name
                        if not new_filename.exists():
                            output_folder.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(new_file_path), str(new_filename))
                            # Eliminar el archivo de la ubicación anterior
                            new_file_path.unlink()
                            new_file_path = new_filename
                        else:
                            # Si ya existe en la nueva ubicación, eliminar la copia temporal
                            new_file_path.unlink()
                            return None
            
            # Actualizar metadatos si hay video_info
            if video_info:
                add_id3_tags(str(new_file_path), metadata, video_info)
            elif not existing_metadata.get('title') or not existing_metadata.get('artist'):
                # Si faltaban metadatos, actualizarlos
                add_id3_tags(str(new_file_path), metadata, {})
            
            final_file_path = new_file_path
        
        # Verificar si ya existe en la BD
        video_id = None
        if video_info:
            video_id = video_info.get('id', '')
        
        existing_song = check_file_exists(
            video_id=video_id,
            artist=metadata.get('artist'),
            title=metadata.get('title')
        )
        
        if not existing_song:
            # Registrar en base de datos
            # Si no hay video_id, generar uno temporal o usar None
            if not video_id:
                # Usar hash absoluto para evitar números negativos
                file_hash = abs(hash(str(final_file_path)))
                video_id = f"imported_{file_hash}"
            
            # Crear video_info mínimo si no existe
            if not video_info:
                video_info = {
                    'title': metadata.get('title', ''),
                    'description': '',
                    'thumbnail': None
                }
            
            # Obtener URL si está disponible
            url = video_info.get('url', '') if video_info else ''
            if not url and video_id and not video_id.startswith('imported_'):
                url = f"https://www.youtube.com/watch?v={video_id}"
            
            register_song_in_db(
                video_id,
                url,
                final_file_path,
                metadata,
                video_info,
                download_source='import'
            )
        
        return True
    
    except Exception as e:
        print(f"Error al procesar {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Función principal."""
    # Verificar si se quiere probar las cookies
    if len(sys.argv) >= 2 and sys.argv[1] == '--test-cookies':
        test_cookies()
        return
    
    # Verificar si se quiere listar playlists
    if len(sys.argv) >= 2 and sys.argv[1] == '--list-playlists':
        list_user_playlists()
        return
    
    # Verificar si se quiere monitorear la lista de "me gusta"
    if len(sys.argv) >= 2 and sys.argv[1] == '--monitor-liked':
        # Verificar si se proporciona una URL de playlist
        playlist_url = None
        if '--playlist-url' in sys.argv:
            idx = sys.argv.index('--playlist-url')
            if idx + 1 < len(sys.argv):
                playlist_url = sys.argv[idx + 1]
        
        monitor_liked_videos(playlist_url=playlist_url)
        return
    
    if len(sys.argv) < 2:
        print("Uso: python download_youtube.py <URL_YOUTUBE> [--genre GÉNERO] [--artist ARTISTA] [--year AÑO]")
        print("   o: python download_youtube.py --monitor-liked [--playlist-url URL]")
        print("   o: python download_youtube.py --list-playlists")
        print("   o: python download_youtube.py --test-cookies")
        print("\nEjemplo:")
        print("  python download_youtube.py https://www.youtube.com/watch?v=VIDEO_ID")
        print("  python download_youtube.py https://www.youtube.com/watch?v=VIDEO_ID --genre House --artist 'Artista' --year 2023")
        print("  python download_youtube.py --monitor-liked  # Monitorea tu lista de 'me gusta'")
        print("  python download_youtube.py --monitor-liked --playlist-url 'https://music.youtube.com/playlist?list=LM'")
        print("  python download_youtube.py --list-playlists  # Lista tus playlists de YouTube")
        print("  python download_youtube.py --test-cookies  # Prueba si las cookies funcionan")
        sys.exit(1)
    
    url = sys.argv[1]
    
    # Verificar que la carpeta de música existe
    music_folder = Path(MUSIC_FOLDER)
    if not music_folder.exists():
        print(f"Creando carpeta de música: {MUSIC_FOLDER}")
        music_folder.mkdir(parents=True, exist_ok=True)
    
    # Obtener información del video
    print("Obteniendo información del video...")
    video_info = get_video_info(url)
    
    if not video_info:
        print("Error: No se pudo obtener información del video.")
        sys.exit(1)
    
    title = video_info.get('title', 'Unknown')
    description = video_info.get('description', '')
    
    print(f"Título: {title}")
    
    # Extraer metadatos básicos (incluyendo año de los metadatos de YouTube)
    metadata = extract_metadata_from_title(title, description, video_info)
    
    # Permitir sobrescribir metadatos con argumentos de línea de comandos
    if '--genre' in sys.argv:
        idx = sys.argv.index('--genre')
        if idx + 1 < len(sys.argv):
            metadata['genre'] = sys.argv[idx + 1]
    
    if '--artist' in sys.argv:
        idx = sys.argv.index('--artist')
        if idx + 1 < len(sys.argv):
            metadata['artist'] = sys.argv[idx + 1]
    
    if '--year' in sys.argv:
        idx = sys.argv.index('--year')
        if idx + 1 < len(sys.argv):
            metadata['year'] = sys.argv[idx + 1]
    
    # Si no hay género, intentar detectarlo online
    if not metadata.get('genre') and metadata.get('artist'):
        detected_genre = detect_genre_online(
            metadata.get('artist'), 
            metadata.get('title', title),
            video_info=video_info,
            title=title,
            description=description
        )
        if detected_genre:
            metadata['genre'] = detected_genre
        else:
            # Preguntar al usuario si no se puede detectar
            print("\n⚠️  No se pudo detectar el género automáticamente.")
            user_genre = input("¿Qué género es esta canción? (deja vacío para 'Sin Clasificar'): ").strip()
            metadata['genre'] = user_genre if user_genre else 'Sin Clasificar'
    
    # Si no hay año, intentar preguntar o usar año actual
    if not metadata.get('year'):
        print("\n⚠️  No se pudo detectar el año desde los metadatos de YouTube.")
        user_year = input("¿En qué año se publicó? (deja vacío para usar año actual): ").strip()
        if user_year:
            metadata['year'] = user_year
        else:
            metadata['year'] = str(datetime.now().year)
    else:
        print(f"📅 Año detectado desde metadatos de YouTube: {metadata.get('year')}")
    
    # Extraer video_id de la URL
    video_id = video_info.get('id', '')
    if not video_id:
        # Intentar extraer de la URL
        import re
        match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
        if match:
            video_id = match.group(1)
    
    # Verificar si el archivo ya existe en la BD
    existing_song = check_file_exists(
        video_id=video_id,
        artist=metadata.get('artist'),
        title=metadata.get('title', title)
    )
    if existing_song:
        print(f"⚠️  El archivo ya existe: {existing_song['file_path']}")
        response = input("¿Deseas descargarlo de todas formas? (s/n): ")
        if response.lower() != 's':
            print("Descarga cancelada.")
            sys.exit(0)
    
    # Obtener carpeta de salida organizada por género y década
    output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))
    
    # Crear nombre de archivo
    if metadata.get('artist'):
        filename = f"{metadata['artist']} - {metadata['title']}"
    else:
        filename = metadata['title']
    
    filename = sanitize_filename(filename)
    output_path = output_folder / filename
    
    print(f"\n📁 Carpeta de destino: {output_folder}")
    print(f"📥 Descargando a: {output_path}")
    print(f"🎤 Artista: {metadata.get('artist', 'No especificado')}")
    print(f"📅 Año: {metadata.get('year', 'No especificado')} ({get_decade_from_year(metadata.get('year'))})")
    print(f"🎵 Género: {metadata.get('genre', 'No especificado')}")
    
    # Descargar
    if download_audio(url, str(output_path), metadata):
        # El archivo se descarga como .mp3, pero yt-dlp añade la extensión
        mp3_file = Path(str(output_path) + '.mp3')
        if not mp3_file.exists():
            # Buscar el archivo descargado (puede tener un nombre ligeramente diferente)
            mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
            if mp3_files:
                mp3_file = mp3_files[0]
            else:
                print("Error: No se encontró el archivo descargado.")
                sys.exit(1)
        
        # Verificar y normalizar volumen si es necesario
        check_and_normalize_audio(str(mp3_file))
        
        # Si no se detectó género, intentar con Essentia (análisis de audio)
        if not metadata.get('genre') or metadata.get('genre', '').lower() in ['sin clasificar', 'unknown', '']:
            detected_genre = detect_genre_from_audio_file(str(mp3_file))
            if detected_genre:
                metadata['genre'] = detected_genre
        
        print("🏷️  Añadiendo metadatos...")
        add_id3_tags(str(mp3_file), metadata, video_info)
        
        # Registrar en base de datos
        print("💾 Registrando en base de datos...")
        if video_id:
            register_song_in_db(video_id, url, mp3_file, metadata, video_info, download_source='puntual')
        else:
            print("⚠️  No se pudo obtener video_id, la canción no se registró en la BD")
        
        print(f"✅ Descarga completada: {mp3_file}")
    else:
        print("❌ Error en la descarga.")
        sys.exit(1)


if __name__ == '__main__':
    main()

