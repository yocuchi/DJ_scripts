#!/usr/bin/env python3
"""
Script para descargar canciones de YouTube a MP3 con metadatos completos.
Incluye extracción de artista, año y estilo de música.
"""

import os
import sys
import re
import json
import struct
import hashlib
import urllib.parse
import urllib.request
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Tuple
from datetime import datetime
import yt_dlp
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, APIC, TXXX
from dotenv import load_dotenv
from database import MusicDatabase

# Configurar TensorFlow para reducir verbosidad de logs
# Solo mostrar errores críticos, una línea por ejecución
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # 0=all, 1=info, 2=warnings, 3=errors only
os.environ['TF_CPP_MIN_VLOG_LEVEL'] = '3'  # Desactivar logs verbosos

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

# Importar clasificador TF
try:
    from genre_classifier_tf import get_best_genre
    TF_CLASSIFIER_AVAILABLE = True
except ImportError:
    TF_CLASSIFIER_AVAILABLE = False

# No normalizar volumen al descargar: el audio se guarda tal cual; solo se mide el volumen (LUFS) para la BD.
NORMALIZE_VOLUME_ON_DOWNLOAD = False

# Escala de volumen para DJ (no broadcast). El grueso de la biblioteca vive entre -7 y -9 LUFS;
# un track a -14 se dibuja pequeño en DJUCED y obliga a subir +5 dB de gain en la deck.
DJ_TARGET_LUFS = -9.0      # objetivo al normalizar (-9 y no -8: los remixes Afro House pegan fuerte de kick)
DJ_TARGET_TRUE_PEAK = -1.0  # dBTP: headroom suficiente para subir gain sin clipear
DJ_LOW_VOLUME_LUFS = -11.0  # por debajo de esto conviene normalizar


def test_essentia_installation():
    """
    Prueba rápida para verificar si Essentia está instalado y funciona.
    
    Returns:
        Tuple[bool, str]: (éxito, mensaje)
    """
    if not ESSENTIA_AVAILABLE:
        return False, "Essentia no está instalado. Instala con: pip install essentia"
    
    try:
        # Probar funciones básicas
        loader = es.MonoLoader
        rhythm_extractor = es.RhythmExtractor2013
        key_extractor = es.KeyExtractor
        
        # SpectralCentroid puede no estar disponible en todas las versiones (opcional)
        try:
            spectral_centroid = es.SpectralCentroid
        except AttributeError:
            pass  # Es opcional, no crítico
        
        # Verificar si TaggerMusicNN está disponible
        tagger_available = False
        try:
            tagger = es.TaggerMusicNN
            tagger_available = True
        except AttributeError:
            pass
        
        msg = "✅ Essentia está instalado y funcionando correctamente"
        if tagger_available:
            msg += " (incluye modelos preentrenados)"
        else:
            msg += " (modelos preentrenados no disponibles, pero análisis básico funcionará)"
        
        return True, msg
    except Exception as e:
        return False, f"Essentia está instalado pero hay un error: {e}"

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
    Usa modelos TensorFlow preentrenados (Discogs-EffNet) si están disponibles.
    Comportamiento según ESSENTIA_CLASSIFIER en .env:
    - auto (por defecto): intenta TensorFlow primero, luego Legacy MusicNN.
    - tf: solo TensorFlow/Discogs (más preciso, requiere modelos descargados).
    - legacy: solo TaggerMusicNN (Legacy).
    
    Args:
        file_path: Ruta al archivo de audio (MP3, WAV, etc.)
    
    Returns:
        Género detectado o None si no se puede determinar
    """
    if not ESSENTIA_AVAILABLE:
        return None
    
    if not Path(file_path).exists():
        return None
    
    mode = (os.environ.get('ESSENTIA_CLASSIFIER') or 'auto').strip().lower()
    use_tf = mode != 'legacy' and TF_CLASSIFIER_AVAILABLE
    use_legacy = mode != 'tf'
    
    # 1. Intentar usar el clasificador TensorFlow (más preciso)
    if use_tf:
        try:
            print("   ⏳ Analizando audio con Essentia (TensorFlow/Discogs)...")
            genre = get_best_genre(file_path)
            if genre:
                return genre
        except Exception as e:
            print(f"   ⚠️ Error en clasificador TF: {e}")
        if mode == 'tf':
            return None  # Solo TF configurado y no dio resultado

    if use_legacy:
        try:
            # Fallback: Implementación original con TaggerMusicNN (si TF falla o no da resultado)
            print("   ⏳ Analizando audio con Essentia (Legacy MusicNN)...")
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
                
                # Extraer características espectrales (opcional, puede no estar disponible)
                avg_centroid = 0
                try:
                    spectral_centroid = es.SpectralCentroid()
                    centroid = spectral_centroid(audio)
                    avg_centroid = float(sum(centroid) / len(centroid)) if len(centroid) > 0 else 0
                except (AttributeError, Exception):
                    # SpectralCentroid no está disponible, usar valor por defecto
                    pass
                
                # Extraer energía
                energy = es.Energy()
                energy_value = energy(audio)
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


def detect_genre_from_audio_file(file_path: str, log_callback=None) -> Optional[str]:
    """
    Detecta el género usando análisis de audio con Essentia.
    Esta función debe llamarse DESPUÉS de descargar el archivo.
    
    Args:
        file_path: Ruta al archivo de audio descargado
        log_callback: Función opcional para logging (recibe un string). Si es None, usa print()
    
    Returns:
        Género detectado o None
    """
    if not ESSENTIA_AVAILABLE:
        if log_callback:
            log_callback("   ⚠️  Essentia no está instalado")
        return None
    
    if not Path(file_path).exists():
        return None
    
    log_msg = "   🎵 Analizando audio con Essentia..."
    if log_callback:
        log_callback(log_msg)
    else:
        print(log_msg)
    
    genre = get_genre_from_essentia(file_path)
    
    if genre:
        log_msg = f"   ✓ Género detectado (análisis de audio Essentia): {genre}"
        if log_callback:
            log_callback(log_msg)
        else:
            print(log_msg)
        return genre
    else:
        log_msg = "   ⚠️  Essentia no pudo detectar el género del audio"
        if log_callback:
            log_callback(log_msg)
        else:
            print(log_msg)
        return None


YEAR_MIN = 1900


def parse_year(value: Optional[object]) -> Optional[str]:
    """
    Normaliza un año a 'YYYY' descartando valores no plausibles.

    Acepta int o str en formato 'YYYY', 'YYYY-MM-DD' o 'YYYYMMDD'. Devuelve None si
    el año cae fuera de YEAR_MIN..(año actual + 1), para que un dato corrupto no
    termine creando carpetas de década absurdas como '1060s' o '5250s'.
    """
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    year_max = datetime.now().year + 1

    # Los 4 primeros dígitos cubren 'YYYY', 'YYYY-MM-DD' y 'YYYYMMDD'
    match = re.match(r'(\d{4})', text)
    if match and YEAR_MIN <= int(match.group(1)) <= year_max:
        return match.group(1)

    # Si no, buscar un año plausible en cualquier parte del texto
    for found in re.findall(r'\b(?:19|20)\d{2}\b', text):
        if YEAR_MIN <= int(found) <= year_max:
            return found

    return None


def get_decade_from_year(year: Optional[str]) -> str:
    """
    Obtiene la década a partir del año.
    Si no hay año o no es plausible, retorna 'Unknown'.
    """
    normalized = parse_year(year)
    if not normalized:
        return 'Unknown'

    decade = (int(normalized) // 10) * 10
    return f"{decade}s"


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
    
    # PRIMERO: Intentar extraer el año de los metadatos de YouTube.
    # Las fuentes se prueban por orden de fiabilidad y se descarta la que no dé un
    # año plausible, de forma que un release_year corrupto no impida caer en
    # release_date o upload_date (antes se aceptaba a ciegas y generaba décadas
    # imposibles como 1060s o 5250s).
    if video_info:
        timestamp_year = None
        release_timestamp = video_info.get('release_timestamp')
        if isinstance(release_timestamp, (int, float)):
            try:
                timestamp_year = datetime.fromtimestamp(release_timestamp).year
            except (ValueError, OSError, OverflowError):
                timestamp_year = None

        for candidate in (
            video_info.get('release_year'),
            video_info.get('release_date'),
            timestamp_year,
            video_info.get('upload_date'),  # año de subida: último recurso
        ):
            metadata['year'] = parse_year(candidate)
            if metadata['year']:
                break

    # Si no se encontró año en los metadatos, intentar extraer del título
    if not metadata['year']:
        year_match = re.search(r'\b(19|20)\d{2}\b', title)
        if year_match:
            metadata['year'] = parse_year(year_match.group())
            if metadata['year']:
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


def get_video_info(url: str, log_callback=None) -> Dict:
    """
    Obtiene información del video sin descargarlo.
    
    Args:
        url: URL del video de YouTube
        log_callback: Función opcional para logging (recibe un string). Si es None, usa print()
    
    Returns:
        Diccionario con información del video o {} si hay error
    """
    import time
    
    def log(msg):
        timestamp = time.strftime('%H:%M:%S')
        formatted_msg = f"[{timestamp}] {msg}"
        if log_callback:
            log_callback(formatted_msg)
        else:
            print(formatted_msg)
    
    start_time = time.time()
    log(f"🔍 Obteniendo información de YouTube...")
    log(f"   URL: {url}")
    
    has_cookies = has_cookies_configured()

    # Función auxiliar: extrae información y captura stderr para poder loguearlo
    def extract_with_captured_stderr(ydl_instance, url):
        """Extrae información y devuelve (info, error, stderr_text)."""
        import sys
        import io
        old_stderr = sys.stderr
        buf = io.StringIO()
        sys.stderr = buf
        try:
            info = ydl_instance.extract_info(url, download=False)
            return info, None, buf.getvalue()
        except Exception as e:
            return None, e, buf.getvalue()
        finally:
            sys.stderr = old_stderr

    # 1) Intentar primero con extract_flat (sin selector de formato) para evitar "Requested format is not available"
    #    en lyric videos, Music, etc. Solo obtenemos id, title, url; el resto se rellena por defecto.
    # Cliente Android a veces evita 403 de YouTube (issue yt-dlp #12482, #14680)
    youtube_extractor_args = {'youtube': {'player_client': ['android']}}
    opts_flat = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
        'ignoreerrors': True,
        'extractor_args': youtube_extractor_args,
    }
    if not apply_cookies_to_opts(opts_flat, log_callback=log):
        log(f"   ⚠️  No se encontraron cookies")
    
    log(f"   🔄 Intentando primero modo básico (extract_flat, sin formato)...")
    with yt_dlp.YoutubeDL(opts_flat) as ydl_flat:
        info_flat, err_flat, _ = extract_with_captured_stderr(ydl_flat, url)
        if info_flat and info_flat.get('id') and info_flat.get('title'):
            elapsed = time.time() - start_time
            log(f"   ✅ Información básica obtenida en {elapsed:.2f}s (modo plano)")
            log(f"      Video ID: {info_flat.get('id')}")
            log(f"      Título: {info_flat.get('title')}")
            # Rellenar campos que extract_flat puede no devolver (el resto del código usa .get() con defaults)
            if not info_flat.get('description'):
                info_flat['description'] = ''
            return info_flat
    
    if err_flat:
        log(f"   📋 Modo básico falló: {err_flat}")
    
    # 2) Intentar extracción completa con formato (más metadatos: descripción, duración, thumbnail, etc.)
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'skip_download': True,
        'ignoreerrors': True,
        'no_check_certificate': False,
        'format': 'bestaudio/best/worst',
        'extractor_args': youtube_extractor_args,
    }
    apply_cookies_to_opts(ydl_opts)

    log(f"   🔄 Extrayendo información completa (formato: bestaudio/best/worst)...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info, error, stderr_capture = extract_with_captured_stderr(ydl, url)
            
            # Si obtuvimos información, retornarla
            if info:
                elapsed = time.time() - start_time
                log(f"   ✅ Información obtenida correctamente en {elapsed:.2f}s")
                log(f"      Video ID: {info.get('id', 'N/A')}")
                log(f"      Título: {info.get('title', 'N/A')}")
                log(f"      Duración: {info.get('duration', 'N/A')} segundos")
                return info
            
            # Si hubo un error, loguear stderr de yt-dlp y lanzar
            if error:
                if stderr_capture and stderr_capture.strip():
                    log(f"   📋 stderr de yt-dlp:")
                    for line in stderr_capture.strip().split('\n'):
                        log(f"      {line}")
                log(f"   📋 Excepción: {type(error).__name__}: {error}")
                raise error
            
            # Si no hay info ni error, intentar métodos alternativos (extract_flat)
            elapsed = time.time() - start_time
            log(f"   ⚠️  No se obtuvo información del video después de {elapsed:.2f}s")
            if stderr_capture and stderr_capture.strip():
                log(f"   📋 stderr de yt-dlp:")
                for line in stderr_capture.strip().split('\n'):
                    log(f"      {line}")
            log(f"   🔄 Intentando métodos alternativos...")
            # Ejecutar los mismos reintentos que en el except (extract_flat con/sin cookies)
            try:
                ydl_opts_retry = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': True,
                    'skip_download': True,
                    'ignoreerrors': True,
                    'extractor_args': youtube_extractor_args,
                }
                apply_cookies_to_opts(ydl_opts_retry)
                log(f"   🔄 Reintento 1/2: extract_flat=True...")
                with yt_dlp.YoutubeDL(ydl_opts_retry) as ydl_retry:
                    info, err_retry, stderr_retry = extract_with_captured_stderr(ydl_retry, url)
                    if info and info.get('id') and info.get('title'):
                        if not info.get('description'):
                            info['description'] = ''
                        log(f"   ✅ Información básica obtenida (modo plano)")
                        return info
                log(f"   🔄 Reintento 2/2: SIN cookies...")
                ydl_opts_retry_2 = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': True,
                    'skip_download': True,
                    'ignoreerrors': True,
                    'extractor_args': youtube_extractor_args,
                }
                with yt_dlp.YoutubeDL(ydl_opts_retry_2) as ydl_retry_2:
                    info, _, _ = extract_with_captured_stderr(ydl_retry_2, url)
                    if info and info.get('id') and info.get('title'):
                        if not info.get('description'):
                            info['description'] = ''
                        log(f"   ✅ Información básica obtenida (sin cookies)")
                        return info
            except Exception:
                pass
            return {}
            
        except yt_dlp.utils.DownloadError as e:
            error_str = str(e)
            log(f"   📋 Error capturado: {error_str}")
            
            if 'Requested format is not available' in error_str:
                log(f"   ℹ️  Formato preferido no disponible, intentando métodos alternativos...")
                log(f"      URL: {url}")
                
                # Intentar con opciones más permisivas (extract_flat, sin elegir formato)
                try:
                    ydl_opts_retry = {
                        'quiet': True,
                        'no_warnings': True,
                        'extract_flat': True,  # Modo plano, no requiere formato
                        'skip_download': True,
                        'ignoreerrors': True,
                    }
                    apply_cookies_to_opts(ydl_opts_retry)

                    log(f"   🔄 Reintento 1/2: extract_flat=True (sin selector de formato)...")
                    with yt_dlp.YoutubeDL(ydl_opts_retry) as ydl_retry:
                        info, err_retry, stderr_retry = extract_with_captured_stderr(ydl_retry, url)
                        if info:
                            log(f"   ✅ Información básica obtenida (modo plano)")
                            return info
                        if err_retry:
                            log(f"   ❌ Reintento 1 falló: {err_retry}")
                        if stderr_retry and stderr_retry.strip():
                            for line in stderr_retry.strip().split('\n'):
                                log(f"      [yt-dlp] {line}")
                except Exception as e2:
                    log(f"   ❌ Reintento 1 excepción: {type(e2).__name__}: {e2}")

                # Segundo reintento: SIN COOKIES
                try:
                    ydl_opts_retry_2 = {
                        'quiet': True,
                        'no_warnings': True,
                        'extract_flat': True,
                        'skip_download': True,
                        'ignoreerrors': True,
                    }
                    log(f"   🔄 Reintento 2/2: SIN cookies...")
                    with yt_dlp.YoutubeDL(ydl_opts_retry_2) as ydl_retry_2:
                        info, err_retry2, stderr_retry2 = extract_with_captured_stderr(ydl_retry_2, url)
                        if info:
                            log(f"   ✅ Información básica obtenida (sin cookies)")
                            return info
                        if err_retry2:
                            log(f"   ❌ Reintento 2 falló: {err_retry2}")
                        if stderr_retry2 and stderr_retry2.strip():
                            for line in stderr_retry2.strip().split('\n'):
                                log(f"      [yt-dlp] {line}")
                except Exception as e3:
                    log(f"   ❌ Reintento 2 excepción: {type(e3).__name__}: {e3}")
            
            elif 'Video unavailable' in error_str or 'not available' in error_str:
                log(f"   ⚠️  Video no disponible: {url}")
                log(f"   Posibles causas:")
                log(f"   - El video fue eliminado o es privado")
                log(f"   - El video requiere autenticación (verifica tus cookies)")
                log(f"   - El video está bloqueado geográficamente")
            else:
                log(f"   📋 Error completo: {error_str}")
                import traceback
                log(f"   📋 Traceback:")
                for line in traceback.format_exc().split('\n'):
                    if line.strip():
                        log(f"      {line}")
            
            return {}
            
        except Exception as e:
            error_str = str(e)
            log(f"   ❌ Error inesperado: {error_str}")
            log(f"   📋 Tipo de error: {type(e).__name__}")
            import traceback
            log(f"   📋 Traceback completo:")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    log(f"      {line}")
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


def is_inside_library(file_path: Path, base_folder: Optional[str]) -> bool:
    """
    Indica si file_path ya vive dentro de la biblioteca base_folder.

    Se usa para decidir entre mover y copiar al reorganizar por género: un
    archivo que ya está en la biblioteca debe MOVERSE, porque copiarlo deja el
    original huérfano en su carpeta anterior y la canción aparece duplicada en
    DJUCED (que escanea el disco, no la BD). Un archivo importado desde fuera
    sí se copia, para no vaciar la carpeta de origen del usuario.
    """
    if not base_folder:
        return False
    try:
        return Path(file_path).resolve().is_relative_to(Path(base_folder).resolve())
    except (OSError, ValueError):
        return False


def resolve_library_path(stored_path: str, base_folder: Optional[str] = None) -> Optional[Path]:
    """
    Traduce una ruta guardada en la BD a una ruta válida en la plataforma actual.

    Esta biblioteca se ha usado desde WSL ('/mnt/c/...'), Windows ('C:\\...') y
    macOS, así que las rutas antiguas no resuelven aquí. Sin esta traducción
    check_file_exists las interpreta como "archivo borrado" y vuelve a insertar
    la canción, que es el origen de los duplicados en la BD.

    Devuelve la ruta encontrada, o None si el archivo no aparece.
    """
    if not stored_path:
        return None

    # 1) La ruta tal cual (caso normal: se guardó en esta misma plataforma).
    try:
        direct = Path(stored_path)
        if direct.exists():
            return direct
    except OSError:
        pass

    if not base_folder:
        return None

    base = Path(base_folder)
    # El nombre de archivo es lo único estable entre plataformas. Se normalizan
    # las barras porque una ruta de Windows no se parsea con Path en macOS.
    filename = stored_path.replace('\\', '/').rstrip('/').split('/')[-1]
    if not filename:
        return None

    # 2) Misma estructura <genero>/<decada>/<archivo> dentro de la biblioteca local.
    parts = [p for p in stored_path.replace('\\', '/').split('/') if p]
    if len(parts) >= 3:
        candidate = base / parts[-3] / parts[-2] / filename
        try:
            if candidate.exists():
                return candidate
        except OSError:
            pass

    # 3) Mismo nombre en cualquier <genero>/<decada>: cubre los archivos
    #    reclasificados a otro género sin que se actualizara la BD.
    #    Se recorre a mano en vez de con glob() porque muchos nombres contienen
    #    corchetes ('... [videoId].mp3') y glob los trataría como comodines.
    try:
        for genre_dir in base.iterdir():
            if not genre_dir.is_dir():
                continue
            for decade_dir in genre_dir.iterdir():
                if not decade_dir.is_dir():
                    continue
                candidate = decade_dir / filename
                if candidate.exists():
                    return candidate
    except OSError:
        pass

    return None


def stable_imported_video_id(file_path: Path, base_folder: Optional[str] = None) -> str:
    """
    Genera un video_id determinista para archivos importados sin ID de YouTube.

    Antes se usaba abs(hash(ruta)), pero el hash de strings en Python está
    aleatorizado por proceso: el mismo archivo obtenía un video_id distinto en
    cada ejecución, así que el UNIQUE de video_id nunca frenaba la reinserción.
    Se usa la ruta relativa a la biblioteca para que el id no cambie al mover la
    biblioteca de sitio ni entre plataformas.
    """
    key = str(file_path)
    if base_folder:
        try:
            key = str(Path(file_path).resolve().relative_to(Path(base_folder).resolve()))
        except (OSError, ValueError):
            pass
    key = key.replace('\\', '/')
    return f"imported_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}"


def check_file_exists(video_id: Optional[str] = None, artist: Optional[str] = None,
                     title: Optional[str] = None, base_folder: str = None) -> Optional[Dict]:
    """
    Verifica si una canción ya existe en la base de datos.
    
    Args:
        video_id: ID del video de YouTube (más preciso)
        artist: Nombre del artista
        title: Título de la canción
        base_folder: Carpeta de la biblioteca, para localizar archivos cuya ruta
                     en la BD se guardó en otra plataforma. Por defecto MUSIC_FOLDER.

    Returns:
        Diccionario con los datos de la canción si existe, None si no existe.
        Si la ruta guardada estaba obsoleta, se corrige en la BD al detectarla.
    """
    # La mayoría de las llamadas no pasan base_folder; sin él no se pueden
    # traducir las rutas guardadas en otra plataforma y se reinsertarían.
    if not base_folder:
        base_folder = MUSIC_FOLDER

    def _match(song: Dict) -> Optional[Dict]:
        """Devuelve la canción si su archivo sigue en disco, reparando la ruta si cambió."""
        resolved = resolve_library_path(song.get('file_path'), base_folder)
        if not resolved:
            return None
        # Si la ruta guardada no coincide con la real (biblioteca migrada de
        # plataforma o archivo reclasificado), se corrige aquí. Sin esto la
        # próxima ejecución volvería a no encontrarla y crearía un duplicado.
        if str(resolved) != str(song.get('file_path')):
            try:
                db.update_song(song['video_id'], file_path=str(resolved))
                song = dict(song, file_path=str(resolved))
            except Exception as e:
                print(f"⚠️  No se pudo actualizar la ruta de '{song.get('title')}': {e}")
        return song

    if video_id:
        song = db.get_song_by_video_id(video_id)
        if song:
            matched = _match(song)
            if matched:
                return matched
            # El archivo fue eliminado de verdad (no es una ruta de otra plataforma)
            print(f"⚠️  Archivo en BD no existe: {song['file_path']}")

    if artist and title:
        for song in db.find_song(artist=artist, title=title):
            matched = _match(song)
            if matched:
                return matched

    return None


def download_audio(url: str, output_path: str, metadata: Dict, progress_callback=None) -> bool:
    """
    Descarga el audio de YouTube y lo convierte a MP3.
    Intenta múltiples formatos en cascada si el formato preferido falla.
    
    Args:
        url: URL del video de YouTube
        output_path: Ruta donde guardar el archivo
        metadata: Metadatos del video
        progress_callback: Función opcional que se llama con el progreso (recibe un dict con 'status', 'downloaded_bytes', 'total_bytes', etc.)
    """
    has_cookies = has_cookies_configured()

    # Lista de formatos a intentar en orden de preferencia
    # Empezamos con cadenas que ya incluyen fallbacks para vídeos con formatos limitados (lyric videos, Music, etc.)
    format_attempts = [
        'bestaudio/best/worst',  # Máximo fallback en un solo intento
        'bestaudio/best',
        'best/worst',
        'best[height<=720]/best',
        'worst[ext=mp4]/worst',
    ]
    
    # Crear hook de progreso si se proporciona un callback
    progress_hooks = []
    if progress_callback:
        def progress_hook(d):
            if d['status'] == 'downloading':
                progress_callback(d)
            elif d['status'] == 'finished':
                # Cuando termina, reportar 100%
                d['downloaded_bytes'] = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                d['total_bytes'] = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                progress_callback(d)
        progress_hooks = [progress_hook]
    
    # Cliente Android puede evitar HTTP 403 con YouTube
    youtube_extractor_args = {'youtube': {'player_client': ['android']}}
    base_opts = {
        'outtmpl': output_path,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',  # Mejor calidad MP3
        }],
        'quiet': True,  # Silenciar para evitar warnings innecesarios
        'no_warnings': False,  # Permitir warnings importantes pero silenciar spam
        'progress_hooks': progress_hooks,
        'extractor_args': youtube_extractor_args,
    }
    
    # Intentar primero con cookies (si están disponibles), luego sin cookies
    # use_cookies indica si en este intento se aplican las cookies configuradas
    cookie_attempts = [True] if has_cookies else [False]
    if has_cookies:
        cookie_attempts.append(False)

    # Intentar con cada formato hasta que uno funcione
    last_error = None
    format_failed = False

    for use_cookies in cookie_attempts:
        if format_failed and use_cookies:
            # Si todos los formatos fallaron con cookies, intentar sin cookies
            print(f"⚠️  Todos los formatos fallaron con cookies, intentando sin cookies...")

        for i, fmt in enumerate(format_attempts):
            ydl_opts = base_opts.copy()
            ydl_opts['format'] = fmt

            if use_cookies:
                apply_cookies_to_opts(ydl_opts)

            cookies_label = "con cookies" if use_cookies else "sin cookies"
            print(f"   📥 Intentando formato ({i+1}/{len(format_attempts)}): {fmt} [{cookies_label}]")
            
            # Suprimir stderr durante la descarga pero capturarlo para logs si falla
            import sys
            import io
            old_stderr = sys.stderr
            stderr_buf = io.StringIO()
            sys.stderr = stderr_buf
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                sys.stderr = old_stderr
                return True
            except Exception as download_error:
                stderr_output = stderr_buf.getvalue()
                sys.stderr = old_stderr
                
                last_error = download_error
                error_str = str(download_error)
                print(f"   ❌ Formato '{fmt}' falló: {error_str}")
                if stderr_output and stderr_output.strip():
                    for line in stderr_output.strip().split('\n'):
                        print(f"      [yt-dlp] {line}")
                
                # Si es un error de formato, continuar con el siguiente formato
                if 'Requested format is not available' in error_str or 'Only images are available' in error_str:
                    continue
                # Si es un error de video no disponible, puede ser por cookies, intentar sin cookies
                elif 'Video unavailable' in error_str or 'Private video' in error_str:
                    if use_cookies and len(cookie_attempts) > 1:
                        # Si estamos usando cookies y hay más intentos, marcar para intentar sin cookies
                        format_failed = True
                        break  # Salir del bucle de formatos para intentar sin cookies
                    else:
                        # Ya intentamos sin cookies o no hay más opciones
                        break  # Error definitivo
                # Otros errores, continuar con siguiente formato
                else:
                    continue
    
    # Si llegamos aquí, todos los formatos fallaron
    error_str = str(last_error) if last_error else "Error desconocido"
    
    if 'Video unavailable' in error_str or 'not available' in error_str or 'Private video' in error_str:
        print(f"❌ Error: Video no disponible: {url}")
        print("   Posibles causas:")
        print("   - El video fue eliminado o es privado")
        print("   - El video requiere autenticación (verifica tus cookies)")
        print("   - El video está bloqueado geográficamente")
        if not has_cookies:
            print("   - No se encontraron cookies (algunos videos requieren autenticación)")
    else:
        print(f"❌ Error al descargar después de intentar {len(format_attempts)} formatos: {last_error}")
        print(f"   URL: {url}")
        print("   💡 Sugerencia: Verifica que el video esté disponible y accesible")
    
    return False


def check_audio_volume(file_path: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Verifica el volumen promedio del archivo de audio usando ffmpeg.

    Returns:
        (volumen_lufs, error): Volumen en LUFS o None si hay error; mensaje de error si falló.
        Referencia DJ: la biblioteca vive entre -7 y -9 LUFS; por debajo de -11 conviene
        normalizar y por debajo de -14 se nota en DJUCED. Más bajo = más silencioso.
    """
    def _last_lines(txt: str, n: int = 5) -> str:
        lines = [l.strip() for l in (txt or '').splitlines() if l.strip()]
        return '\n'.join(lines[-n:]) if lines else (txt or '')[:500]

    if not shutil.which('ffmpeg'):
        return None, 'ffmpeg no está instalado o no está en el PATH'

    last_output = ''
    try:
        # Usar ffmpeg para analizar el volumen (EBU R128 loudness)
        # -vn = solo audio, ignora portada/streams de video embebidos (evita fallos con mjpeg dañado)
        cmd = [
            'ffmpeg',
            '-i', file_path,
            '-vn',
            '-af', 'loudnorm=I=-23.0:TP=-2.0:LRA=7.0:print_format=json',
            '-f', 'null',
            '-'
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            encoding='utf-8',
            errors='replace'
        )
        # En Windows ffmpeg escribe mucho en stderr; unir ambas salidas
        output = (result.stdout or '') + (result.stderr or '')
        last_output = output
        json_start = output.find('{')
        if json_start != -1:
            json_str = output[json_start:]
            json_end = json_str.rfind('}') + 1
            if json_end > 0:
                data = json.loads(json_str[:json_end])
                input_i = data.get('input_i')
                if input_i is not None:
                    return float(input_i), None
    except subprocess.TimeoutExpired:
        return None, 'ffmpeg tardó demasiado (timeout)'
    except (json.JSONDecodeError, ValueError, KeyError):
        pass

    # Método alternativo: volumedetect (-vn = solo audio, ignora portada embebida)
    try:
        cmd = [
            'ffmpeg',
            '-i', file_path,
            '-vn',
            '-af', 'volumedetect',
            '-f', 'null',
            '-'
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            encoding='utf-8',
            errors='replace'
        )
        # En Windows ffmpeg escribe en stderr; unir ambas salidas
        output = (result.stdout or '') + (result.stderr or '')
        last_output = output
        # Aceptar punto o coma como decimal (locale)
        match = re.search(r'mean_volume:\s*([-\d]+[.,][\d]+)\s*dB', output)
        if match:
            vol_str = match.group(1).replace(',', '.')
            return float(vol_str), None
    except subprocess.TimeoutExpired:
        return None, 'ffmpeg tardó demasiado (timeout)'
    except ValueError:
        pass

    # Log en consola del servidor para depurar (qué recibió Python de ffmpeg)
    print("[check_audio_volume] FFmpeg no devolvió volumen. Salida recibida:")
    print("---")
    print((last_output or "(vacío)")[-4000:])  # últimos 4000 chars para no saturar
    print("---")

    err = _last_lines(last_output) or 'ffmpeg no devolvió volumen'
    return None, err


def generate_waveform_data(file_path: str, num_points: int = 120) -> Optional[list]:
    """
    Genera una lista de valores normalizados (0.0–1.0) que representan la forma de onda
    de toda la canción, para mostrar una línea de onda en la interfaz.

    Usa ffmpeg para extraer PCM (mono, 16-bit) y promedia por bloques.

    Args:
        file_path: Ruta al archivo de audio (MP3, etc.).
        num_points: Número de puntos de la onda (por defecto 120).

    Returns:
        Lista de floats entre 0 y 1, o None si hay error.
    """
    if not shutil.which('ffmpeg'):
        return None
    path = Path(file_path)
    if not path.exists():
        return None
    try:
        cmd = [
            'ffmpeg', '-i', str(path),
            '-vn', '-acodec', 'pcm_s16le', '-f', 's16le', '-ac', '1',
            '-'
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        raw = proc.stdout.read()
        proc.wait(timeout=120)
        if not raw or len(raw) < 2:
            return None
        # Cada 2 bytes = 1 sample signed 16-bit little endian
        samples = []
        for i in range(0, len(raw), 2):
            if i + 2 <= len(raw):
                samples.append(abs(struct.unpack('<h', raw[i:i + 2])[0]))
        if not samples:
            return None
        # Downsample a num_points: por cada segmento, valor máximo normalizado
        chunk_size = max(1, len(samples) // num_points)
        waveform = []
        for i in range(num_points):
            start = i * chunk_size
            end = min(start + chunk_size, len(samples))
            if start >= len(samples):
                break
            segment = samples[start:end]
            max_val = max(segment) if segment else 0
            waveform.append(max_val / 32768.0)
        return waveform[:num_points]
    except (subprocess.TimeoutExpired, OSError, struct.error, ValueError):
        return None


def normalize_audio_volume(file_path: str, target_lufs: float = DJ_TARGET_LUFS) -> bool:
    """
    Normaliza el volumen del archivo de audio usando ffmpeg loudnorm.

    Args:
        file_path: Ruta al archivo MP3
        target_lufs: Nivel objetivo en LUFS (escala DJ: -9.0, no el -23.0 de broadcast)

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
            '-af', f'loudnorm=I={target_lufs}:TP={DJ_TARGET_TRUE_PEAK}:LRA=7.0',
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


def apply_volume_offset(file_path: str, offset_db: float) -> Tuple[bool, Optional[str]]:
    """
    Aplica un ajuste de volumen al archivo de audio (subir o bajar en dB).
    Modifica el archivo en disco.
    
    Args:
        file_path: Ruta al archivo de audio
        offset_db: Ajuste en dB (positivo = más volumen, negativo = menos)
    
    Returns:
        (ok, error): ok=True si se aplicó correctamente; error con mensaje en caso contrario.
    """
    def _last_lines(txt: str, n: int = 6) -> str:
        lines = [l.strip() for l in (txt or '').splitlines() if l.strip()]
        return '\n'.join(lines[-n:]) if lines else (txt or '')[:500]

    if not shutil.which('ffmpeg'):
        return False, 'ffmpeg no está instalado o no está en el PATH'
    path = Path(file_path)
    if not path.exists():
        return False, f'Archivo no encontrado: {file_path}'

    temp_file = str(path.with_suffix('.tmp.vol.mp3'))
    last_output = ''
    try:
        if Path(temp_file).exists():
            try:
                Path(temp_file).unlink()
            except Exception:
                pass

        cmd = [
            'ffmpeg', '-y', '-i', file_path,
            '-vn',
            '-af', f'volume={offset_db:+.1f}dB',
            '-ar', '44100', '-b:a', '320k',
            temp_file
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            encoding='utf-8',
            errors='replace'
        )
        last_output = (result.stdout or '') + (result.stderr or '')

        if result.returncode != 0 or not Path(temp_file).exists():
            if Path(temp_file).exists():
                try:
                    Path(temp_file).unlink()
                except Exception:
                    pass
            return False, f'ffmpeg falló (código {result.returncode}): {_last_lines(last_output)}'

        try:
            path.unlink()
        except PermissionError as e:
            try:
                Path(temp_file).unlink()
            except Exception:
                pass
            return False, f'No se pudo reemplazar el archivo original (¿está en uso o sincronizando OneDrive?): {e}'

        try:
            Path(temp_file).rename(file_path)
        except Exception as e:
            return False, f'No se pudo renombrar el archivo temporal: {e}'

        return True, None

    except subprocess.TimeoutExpired:
        if Path(temp_file).exists():
            try:
                Path(temp_file).unlink()
            except Exception:
                pass
        return False, 'ffmpeg tardó demasiado (timeout 300s)'
    except Exception as e:
        if Path(temp_file).exists():
            try:
                Path(temp_file).unlink()
            except Exception:
                pass
        return False, f'Excepción aplicando volumen: {e}'


def check_and_normalize_audio(file_path: str, threshold_lufs: float = DJ_LOW_VOLUME_LUFS) -> bool:
    """
    Verifica el volumen del archivo y lo normaliza si está por debajo del umbral.
    No se usa en la descarga: NORMALIZE_VOLUME_ON_DOWNLOAD = False (el audio se guarda sin normalizar).

    Args:
        file_path: Ruta al archivo MP3
        threshold_lufs: Umbral en LUFS. Si el volumen está por debajo de este valor,
                       se normalizará. Por defecto -11.0 (escala DJ; el objetivo es -9.0)
    
    Returns:
        True si se normalizó o no era necesario, False si hubo error
    """
    print("   🔊 Verificando volumen del audio...")
    
    volume, _ = check_audio_volume(file_path)
    
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


SUPPORTED_COOKIE_BROWSERS = (
    'brave', 'chrome', 'chromium', 'edge', 'firefox', 'opera', 'safari', 'vivaldi', 'whale'
)


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


def get_cookies_browser() -> Optional[tuple]:
    """
    Devuelve la configuración de extracción de cookies desde el navegador para yt-dlp.

    Lee la variable de entorno `YOUTUBE_COOKIES_BROWSER` (ej: "chrome", "edge", "firefox", ...).
    Opcionalmente lee `YOUTUBE_COOKIES_BROWSER_PROFILE` (ej: "Default", "Profile 1").

    Returns:
        Tupla compatible con yt-dlp `cookiesfrombrowser`:
            (browser_name,)              si solo se especifica el navegador
            (browser_name, profile)      si también se especifica el perfil
        None si no está configurado o el navegador no es válido.
    """
    raw = (os.getenv('YOUTUBE_COOKIES_BROWSER', '') or '').strip().lower()
    if not raw or raw in ('none', 'no', 'off', 'disabled'):
        return None
    if raw not in SUPPORTED_COOKIE_BROWSERS:
        return None
    profile = (os.getenv('YOUTUBE_COOKIES_BROWSER_PROFILE', '') or '').strip()
    if profile:
        return (raw, profile)
    return (raw,)


def apply_cookies_to_opts(ydl_opts: dict, log_callback=None) -> Optional[str]:
    """
    Inyecta la configuración de cookies en un dict de opciones de yt-dlp.

    Prioridad: navegador (YOUTUBE_COOKIES_BROWSER) > archivo (YOUTUBE_COOKIES_FILE / youtube_cookies.txt).

    Returns:
        - "browser:<name>" si se aplicó cookiesfrombrowser
        - ruta al archivo si se aplicó cookiefile
        - None si no había cookies configuradas
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    browser_cfg = get_cookies_browser()
    if browser_cfg:
        ydl_opts['cookiesfrombrowser'] = browser_cfg
        label = f"navegador {browser_cfg[0]}" + (f" (perfil: {browser_cfg[1]})" if len(browser_cfg) > 1 else '')
        log(f"   📋 Usando cookies del {label}")
        return f"browser:{browser_cfg[0]}"

    cookies_file = get_cookies_file()
    if cookies_file:
        ydl_opts['cookiefile'] = cookies_file
        log(f"   📋 Usando cookies del archivo: {cookies_file}")
        return cookies_file

    return None


def has_cookies_configured() -> bool:
    """Indica si hay alguna fuente de cookies configurada (archivo o navegador)."""
    return bool(get_cookies_browser()) or bool(get_cookies_file())


def test_cookies() -> bool:
    """
    Prueba si las cookies funcionan correctamente accediendo a YouTube.

    Returns:
        True si las cookies funcionan, False en caso contrario.
    """
    browser_cfg = get_cookies_browser()
    cookies_file = get_cookies_file()

    if not browser_cfg and not cookies_file:
        print("❌ No se encontró configuración de cookies.")
        print("   Buscado en:")
        print(f"   - Variable de entorno YOUTUBE_COOKIES_BROWSER (chrome, edge, firefox, ...)")
        print(f"   - Variable de entorno YOUTUBE_COOKIES_FILE")
        print(f"   - {Path.home() / 'youtube_cookies.txt'}")
        print(f"   - {Path.cwd() / 'youtube_cookies.txt'}")
        return False

    if browser_cfg:
        label = f"navegador {browser_cfg[0]}" + (f" (perfil: {browser_cfg[1]})" if len(browser_cfg) > 1 else '')
        print(f"📋 Cookies configuradas: {label}")
    else:
        print(f"📋 Archivo de cookies encontrado: {cookies_file}")
        cookie_path = Path(cookies_file)
        if not cookie_path.exists():
            print(f"❌ El archivo de cookies no existe: {cookies_file}")
            return False
        file_size = cookie_path.stat().st_size
        if file_size == 0:
            print(f"⚠️  El archivo de cookies está vacío: {cookies_file}")
            return False
        print(f"   ✓ Tamaño del archivo: {file_size} bytes")

    # Probar acceso a YouTube con las cookies configuradas
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
    }
    apply_cookies_to_opts(ydl_opts)
    
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
    if not has_cookies_configured():
        print("⚠️  No se encontró configuración de cookies (navegador ni archivo).")
        return []

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
    }
    apply_cookies_to_opts(ydl_opts)
    
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
    if not has_cookies_configured():
        return None

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
    }
    apply_cookies_to_opts(ydl_opts)
    
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
    browser_cfg = get_cookies_browser()
    cookies_file = get_cookies_file()

    if not browser_cfg and not cookies_file:
        print("❌ No se encontró configuración de cookies.")
        print("   Para acceder a tus playlists, configura un navegador (YOUTUBE_COOKIES_BROWSER)")
        print("   o exporta tus cookies de YouTube a un archivo (YOUTUBE_COOKIES_FILE).")
        return

    if browser_cfg:
        label = f"navegador {browser_cfg[0]}" + (f" (perfil: {browser_cfg[1]})" if len(browser_cfg) > 1 else '')
        print(f"📋 Usando cookies del {label}")
    else:
        print(f"📋 Usando cookies desde: {cookies_file}")
    print("🔍 Buscando playlists...\n")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
    }
    apply_cookies_to_opts(ydl_opts)
    
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


def get_liked_videos_from_url(playlist_url: str, limit: int = 10, start_index: int = 1) -> list:
    """
    Obtiene videos de una playlist específica usando su URL.
    
    Args:
        playlist_url: URL de la playlist
        limit: Número máximo de videos a obtener
        start_index: Índice inicial (1-based) para obtener videos desde una posición específica
    """
    if not has_cookies_configured():
        print("⚠️  No se encontró configuración de cookies (navegador ni archivo).")
        return []

    # Calcular el rango de elementos a obtener
    # start_index es 1-based, así que si queremos 10 canciones desde el índice 1, obtenemos 1-10
    end_index = start_index + limit - 1
    playlist_items = f"{start_index}-{end_index}" if limit > 0 else None

    # Usar extract_flat para obtener solo información básica sin problemas de formato
    # y ignoreerrors para continuar aunque algunos videos fallen
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'playlistend': end_index,  # Limitar hasta el final del rango
        'ignoreerrors': True,  # Continuar aunque algunos videos fallen
    }
    apply_cookies_to_opts(ydl_opts)

    # Agregar playlist_items si se especificó un límite
    if playlist_items:
        ydl_opts['playlist_items'] = playlist_items
    
    import time
    start_time = time.time()
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"[{time.strftime('%H:%M:%S')}] 🔍 Obteniendo videos de: {playlist_url} (límite: {limit}, desde índice: {start_index})")
            print(f"[{time.strftime('%H:%M:%S')}]    Llamando a ydl.extract_info...")
            info = ydl.extract_info(playlist_url, download=False)
            elapsed = time.time() - start_time
            print(f"[{time.strftime('%H:%M:%S')}]    ✅ extract_info completado en {elapsed:.2f}s")
            
            if not info:
                print(f"[{time.strftime('%H:%M:%S')}] ❌ No se pudieron obtener videos de la playlist")
                return []
            
            print(f"[{time.strftime('%H:%M:%S')}]    Procesando entries...")
            entries = info.get('entries', [])
            
            # Si entries es None, convertir a lista vacía
            if entries is None:
                entries = []
            
            # Si entries es un generador, convertirlo a lista
            try:
                if hasattr(entries, '__iter__') and not isinstance(entries, (list, tuple, str)):
                    print(f"[{time.strftime('%H:%M:%S')}]    Convirtiendo generador a lista...")
                    entries = list(entries)
                    print(f"[{time.strftime('%H:%M:%S')}]    ✅ Conversión completada: {len(entries)} entradas")
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] ⚠️  Error al convertir entries a lista: {e}")
                entries = []
            
            # Filtrar entradas None (videos que fallaron debido a ignoreerrors)
            total_entries = len(entries)
            print(f"[{time.strftime('%H:%M:%S')}]    Filtrando entradas None...")
            entries = [e for e in entries if e is not None]
            filtered_count = total_entries - len(entries)
            if filtered_count > 0:
                print(f"[{time.strftime('%H:%M:%S')}] ⚠️  Se omitieron {filtered_count} video(s) que no pudieron procesarse")
            
            # Fallback sin extract_flat: SÓLO si no obtuvimos ninguna entrada.
            # Sin extract_flat, yt-dlp resuelve cada vídeo por separado (minutos para
            # un lote grande), y antes se lanzaba también cuando simplemente pedíamos
            # más canciones de las que tiene la playlist: en ese caso el reintento no
            # puede devolver más entradas, sólo hacer esperar.
            if not entries:
                print(f"⚠️  extract_flat no devolvió entradas ({len(entries)} de {limit} solicitadas). Intentando sin extract_flat...")
                ydl_opts_full = {
                    'quiet': True,
                    'no_warnings': True,
                    'playlistend': end_index,
                    'ignoreerrors': True,  # Continuar aunque algunos videos fallen
                }
                apply_cookies_to_opts(ydl_opts_full)
                if playlist_items:
                    ydl_opts_full['playlist_items'] = playlist_items
                try:
                    with yt_dlp.YoutubeDL(ydl_opts_full) as ydl_full:
                        info_full = ydl_full.extract_info(playlist_url, download=False)
                        if info_full:
                            entries_full = info_full.get('entries', [])
                            if entries_full is None:
                                entries_full = []
                            # Convertir generador a lista si es necesario
                            if hasattr(entries_full, '__iter__') and not isinstance(entries_full, (list, tuple, str)):
                                entries_full = list(entries_full)
                            # Filtrar entradas None (videos que fallaron)
                            entries_full = [e for e in entries_full if e is not None]
                            # Usar el método sin extract_flat si obtuvo más resultados
                            if len(entries_full) > len(entries):
                                print(f"✓ Método sin extract_flat obtuvo {len(entries_full)} entradas")
                                entries = entries_full
                except Exception as e:
                    print(f"⚠️  Error en método sin extract_flat: {e}")
            
            if not entries:
                print(f"[{time.strftime('%H:%M:%S')}] ❌ No se pudieron obtener videos de la playlist")
                return []
            
            print(f"[{time.strftime('%H:%M:%S')}] ✓ Se encontraron {len(entries)} entradas en la playlist")
            
            videos = []
            
            # Procesar las entradas del rango solicitado
            # Si start_index > 1, necesitamos tomar solo las entradas desde ese índice
            # playlist_items debería devolver solo las entradas del rango, pero por seguridad
            # tomamos solo las que necesitamos
            print(f"[{time.strftime('%H:%M:%S')}]    Procesando entradas para crear lista de videos...")
            
            # Si start_index > 1, las entradas devueltas deberían empezar desde start_index
            # pero por seguridad, tomamos solo las primeras 'limit' entradas
            entries_to_process = entries[:limit]
            
            for idx, entry in enumerate(entries_to_process, 1):
                if len(videos) >= limit:
                    break
                    
                if entry:
                    video_id = entry.get('id', '')
                    if not video_id:
                        continue
                    
                    title = entry.get('title') or 'Unknown'
                    url = f"https://www.youtube.com/watch?v={video_id}"

                    # El artista ya viene en la entrada plana (gratis, sin otra
                    # petición). YouTube Music usa canales "<Artista> - Topic"
                    # para los artistas autogenerados: quitamos ese sufijo.
                    artists = entry.get('artists')
                    if isinstance(artists, (list, tuple)):
                        artist = ', '.join(str(a) for a in artists if a) or None
                    else:
                        artist = artists or None
                    if not artist:
                        artist = entry.get('artist') or entry.get('creator') or \
                                 entry.get('channel') or entry.get('uploader')
                    if artist:
                        artist = re.sub(r'\s*-\s*Topic$', '', str(artist)).strip() or None

                    videos.append({
                        'id': video_id,
                        'title': title,
                        'url': url,
                        'artist': artist,
                        'duration': entry.get('duration')
                    })

            total_elapsed = time.time() - start_time
            print(f"[{time.strftime('%H:%M:%S')}] ✓ Se procesaron {len(videos)} videos (solicitados: {limit}, desde índice {start_index}) en {total_elapsed:.2f}s")
            return videos
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Error al obtener videos después de {elapsed:.2f}s: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_liked_videos(limit: int = 10) -> list:
    """
    Obtiene las últimas canciones de la lista de 'me gusta' de YouTube.
    
    Nota: Requiere cookies de sesión de YouTube. El usuario debe exportar sus cookies
    desde el navegador y guardarlas en un archivo (formato Netscape).
    """
    browser_cfg = get_cookies_browser()
    cookies_file = get_cookies_file()

    if not browser_cfg and not cookies_file:
        print("⚠️  Advertencia: No se encontró configuración de cookies.")
        print("   Para acceder a tu lista de 'me gusta', configura un navegador (YOUTUBE_COOKIES_BROWSER=chrome)")
        print("   o exporta tus cookies de YouTube a un archivo (YOUTUBE_COOKIES_FILE).")
        return []

    if browser_cfg:
        label = f"navegador {browser_cfg[0]}" + (f" (perfil: {browser_cfg[1]})" if len(browser_cfg) > 1 else '')
        print(f"📋 Usando cookies del {label}")
    else:
        print(f"📋 Usando cookies desde: {cookies_file}")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'playlistend': limit,
    }
    apply_cookies_to_opts(ydl_opts)
    
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
                    
                    title = entry.get('title') or 'Unknown'
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
        
        # PRIMERO: Verificar si está rechazado (verificación rápida)
        if is_rejected_video(video_id):
            print(f"   ⊘ Rechazada anteriormente (se omite)")
            print()
            continue
        
        # SEGUNDO: Verificar si ya está descargada por video_id (verificación rápida)
        existing_song = check_file_exists(video_id=video_id)
        if existing_song:
            print(f"   ✓ Ya está descargada: {existing_song['file_path']}")
            print()
            continue
        
        # Solo si no está rechazado ni descargado, obtener información del video (operación costosa)
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
                    
                    # No normalizar volumen en la descarga (se mide y guarda en BD)
                    
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


def get_mp3_bitrate(file_path: Path) -> Optional[int]:
    """
    Extrae el bitrate de un archivo MP3 en kbps.
    
    Args:
        file_path: Ruta al archivo MP3
        
    Returns:
        Bitrate en kbps o None si no se puede obtener
    """
    try:
        if not file_path.exists():
            return None
        
        audio = MP3(str(file_path))
        # audio.info.bitrate está en bps (bits por segundo), convertir a kbps
        bitrate_bps = audio.info.bitrate
        if bitrate_bps:
            bitrate_kbps = bitrate_bps // 1000  # Convertir a kbps
            return bitrate_kbps
    except Exception as e:
        # Si hay error al leer el archivo, devolver None
        pass
    
    return None


def _save_waveform_for_song(video_id: str, file_path: str) -> None:
    """Genera la forma de onda de la canción y la guarda en la base de datos."""
    waveform = generate_waveform_data(file_path)
    if waveform is not None:
        db.update_song(video_id, waveform_data=json.dumps(waveform))
        print("   〰️  Waveform generado y guardado.")


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

    # Si no hay thumbnail de YouTube, comprobar si el MP3 tiene portada embebida (APIC tag)
    if not thumbnail_url and file_path.exists():
        try:
            _audio = MP3(str(file_path), ID3=ID3)
            if any(k.startswith('APIC') for k in _audio.keys()):
                thumbnail_url = f'/api/database/song/{video_id}/cover'
        except Exception:
            pass

    # Obtener descripción
    description = video_info.get('description', '')
    if len(description) > 1000:  # Limitar tamaño
        description = description[:1000]
    
    # Obtener década
    decade = get_decade_from_year(metadata.get('year'))
    
    # Obtener bitrate del archivo MP3
    bitrate_kbps = get_mp3_bitrate(file_path)
    
    # Medir volumen del archivo (LUFS) para tenerlo en BD — sin normalizar
    volume_lufs, _ = check_audio_volume(str(file_path))
    
    # Verificar si ya existe antes de intentar añadir
    existing_song = db.get_song_by_video_id(video_id)
    if existing_song:
        print(f"⚠️  Advertencia: La canción con video_id '{video_id}' ya existe en la base de datos.")
        print(f"   Título existente: {existing_song.get('title', 'N/A')}")
        print(f"   Artista existente: {existing_song.get('artist', 'N/A')}")
        print(f"   Archivo existente: {existing_song.get('file_path', 'N/A')}")
        print(f"   Archivo nuevo: {file_path}")
        print(f"   📍 Para verla en la interfaz, busca por: '{existing_song.get('title', 'N/A')}' o video_id '{video_id}'")
        # Intentar actualizar en lugar de insertar (actualizar archivo, tamaño, etc.)
        update_data = {
            'file_path': str(file_path),
            'file_size': file_size,
            'file_type': file_type,
            'bitrate_kbps': bitrate_kbps,
            'volume_lufs': volume_lufs
        }
        # También actualizar metadatos si han cambiado
        if metadata.get('title'):
            update_data['title'] = metadata.get('title')
        if metadata.get('artist'):
            update_data['artist'] = metadata.get('artist')
        if metadata.get('genre'):
            update_data['genre'] = metadata.get('genre')
        if metadata.get('year'):
            update_data['year'] = metadata.get('year')
            update_data['decade'] = decade
        
        if db.update_song(video_id, **update_data):
            print(f"✅ Canción actualizada en la base de datos con nueva información.")
            _save_waveform_for_song(video_id, str(file_path))
        else:
            print(f"⚠️  No se pudo actualizar la canción existente, pero ya está en la base de datos.")
        return
    
    # Registrar en BD
    try:
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
            download_source=download_source,
            bitrate_kbps=bitrate_kbps,
            volume_lufs=volume_lufs,
            volume_offset_db=0
        )
        
        if success:
            print(f"✅ Canción registrada correctamente en la base de datos: {metadata.get('title', 'Unknown')}")
            print(f"   Video ID: {video_id}")
            print(f"   Artista: {metadata.get('artist', 'N/A')}")
            print(f"   📍 Puedes encontrarla en la pestaña 'Base de Datos' buscando por: '{metadata.get('title', 'Unknown')}'")
            _save_waveform_for_song(video_id, str(file_path))
        else:
            print(f"⚠️  Error: No se pudo registrar la canción en la base de datos.")
            print(f"   Video ID: {video_id}")
            print(f"   Título: {metadata.get('title', 'Unknown')}")
            print(f"   Artista: {metadata.get('artist', 'N/A')}")
            print(f"   Archivo: {file_path}")
            
            # Verificar si existe por file_path
            existing_by_path = db.get_song_by_file_path(str(file_path))
            if existing_by_path:
                existing_video_id = existing_by_path.get('video_id', 'N/A')
                print(f"   ⚠️  Ya existe una canción con este archivo:")
                print(f"      Video ID existente: {existing_video_id}")
                print(f"      Título existente: {existing_by_path.get('title', 'N/A')}")
                
                # Si el video_id existente es de importación y tenemos un video_id real de YouTube, actualizar
                if existing_video_id.startswith('imported_') and video_id and not video_id.startswith('imported_'):
                    print(f"   🔄 Actualizando canción importada con video_id real de YouTube...")
                    update_data = {
                        'url': clean_url,
                        'title': metadata.get('title', video_info.get('title', 'Unknown')),
                        'artist': metadata.get('artist'),
                        'year': metadata.get('year'),
                        'genre': metadata.get('genre'),
                        'decade': decade,
                        'file_path': str(file_path),
                        'file_size': file_size,
                        'file_type': file_type,
                        'duration': duration,
                        'thumbnail_url': thumbnail_url,
                        'description': description,
                        'download_source': download_source,
                        'bitrate_kbps': bitrate_kbps
                    }
                    
                    if db.update_song_video_id(existing_video_id, video_id, **update_data):
                        print(f"   ✅ Canción actualizada correctamente:")
                        print(f"      Video ID actualizado: {existing_video_id} → {video_id}")
                        print(f"      Título: {metadata.get('title', 'Unknown')}")
                        print(f"      Artista: {metadata.get('artist', 'N/A')}")
                        print(f"      📍 Ahora puedes encontrarla en la base de datos con video_id '{video_id}'")
                        _save_waveform_for_song(video_id, str(file_path))
                        return
                    else:
                        print(f"   ❌ No se pudo actualizar el video_id de la canción existente.")
                else:
                    print(f"      📍 Busca en la base de datos por video_id '{existing_video_id}'")
            
            # Verificar si existe por video_id (por si acaso)
            existing_by_id = db.get_song_by_video_id(video_id)
            if existing_by_id:
                print(f"   ⚠️  También existe una canción con este video_id:")
                print(f"      Título: {existing_by_id.get('title', 'N/A')}")
                print(f"      Archivo: {existing_by_id.get('file_path', 'N/A')}")
    except Exception as e:
        print(f"❌ Error al registrar canción en la base de datos: {e}")
        print(f"   Video ID: {video_id}")
        print(f"   Título: {metadata.get('title', 'Unknown')}")
        import traceback
        traceback.print_exc()


def redownload_full(video_id: str, progress_callback=None) -> Tuple[bool, Optional[str]]:
    """
    Vuelve a descargar una canción con todo el proceso: extracción de metadatos,
    detección de género, carpeta por género/año, descarga, ID3 y registro en BD.
    Si la canción se guarda en otra carpeta, se elimina el archivo viejo.

    Args:
        video_id: ID del video de YouTube (canción ya en BD).
        progress_callback: Opcional, función(status_str) para reportar progreso.

    Returns:
        (éxito: bool, mensaje_error: Optional[str])
    """
    def report(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    song = db.get_song_by_video_id(video_id)
    if not song:
        return False, 'Canción no encontrada en la base de datos'

    url = song.get('url', '')
    if not url or 'youtube' not in url.lower():
        return False, 'No hay URL de YouTube para esta canción'

    old_file_path = song.get('file_path', '')
    if not old_file_path:
        return False, 'No hay ruta de archivo'

    old_path_obj = Path(old_file_path)

    try:
        report('Obteniendo información del video...')
        video_info = get_video_info(url)
        if not video_info:
            return False, 'No se pudo obtener información del video'

        title = video_info.get('title', '')
        description = video_info.get('description', '')
        report('Extrayendo metadatos del título...')
        metadata = extract_metadata_from_title(title, description, video_info)

        if not metadata.get('genre'):
            report('Detectando género...')
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
                metadata['genre'] = 'Sin Clasificar'

        report('Preparando carpeta de salida...')
        output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))

        if metadata.get('artist'):
            filename = f"{metadata['artist']} - {metadata['title']}"
        else:
            filename = metadata.get('title', title)
        filename = sanitize_filename(filename)
        output_path = output_folder / filename

        report('Descargando audio...')
        if not download_audio(url, str(output_path), metadata, progress_callback=None):
            return False, 'Error en la descarga'

        mp3_file = Path(str(output_path) + '.mp3')
        if not mp3_file.exists():
            mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
            mp3_file = mp3_files[0] if mp3_files else mp3_file

        if not metadata.get('genre') or (str(metadata.get('genre', '')).lower() in ['sin clasificar', 'unknown', '']):
            detected_genre = detect_genre_from_audio_file(str(mp3_file))
            if detected_genre:
                metadata['genre'] = detected_genre

        report('Añadiendo metadatos ID3...')
        add_id3_tags(str(mp3_file), metadata, video_info)

        report('Registrando en base de datos...')
        register_song_in_db(video_id, url, mp3_file, metadata, video_info, download_source='puntual')

        # Si el archivo nuevo está en otra ruta, eliminar el viejo
        new_path_resolved = mp3_file.resolve()
        if old_path_obj.exists():
            old_resolved = old_path_obj.resolve()
            if old_resolved != new_path_resolved:
                try:
                    old_path_obj.unlink()
                except OSError:
                    pass  # No crítico si falla

        return True, None
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, str(e)


def sanitize_tag_text(text: Optional[str]) -> Optional[str]:
    """
    Normaliza a NFC y repara la doble codificación UTF-8/Latin-1 (mojibake).

    Escritores externos (yt-dlp/ffmpeg antiguos, otras apps de DJ) guardan a veces
    bytes UTF-8 en frames declarados como Latin-1. Al leerlos con mutagen salen como
    'CanciÃ³n' y, si se reescriben tal cual, la corrupción queda grabada para siempre
    (y se acumula una vuelta más en cada pasada). Sanear aquí cura en vez de perpetuar.
    """
    if not text:
        return text

    import unicodedata
    result = unicodedata.normalize('NFC', str(text))
    for _ in range(3):  # hasta 3 vueltas para corrupción acumulada
        try:
            candidate = result.encode('latin-1').decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            break
        if candidate == result:
            break
        result = candidate
    return result


def add_id3_tags(file_path: str, metadata: Dict, video_info: Dict):
    """
    Añade tags ID3 al archivo MP3.
    """
    try:
        audio = MP3(file_path, ID3=ID3)
    except:
        audio = MP3(file_path)
        audio.add_tags()
    
    # Guardar YouTube ID en campo TXXX personalizado
    youtube_id = video_info.get('id', '')
    if youtube_id:
        audio['TXXX:YouTube ID'] = TXXX(encoding=3, desc='YouTube ID', text=youtube_id)

    # Añadir tags básicos (siempre saneados: NFC + reparación de mojibake)
    if metadata.get('title'):
        title_text = sanitize_tag_text(metadata['title'])
        # Limpiar el YouTube ID del título si aparece como [ID] (11 chars alfanuméricos)
        if youtube_id:
            title_text = re.sub(r'\s*\[' + re.escape(youtube_id) + r'\]\s*', ' ', title_text).strip()
        audio['TIT2'] = TIT2(encoding=3, text=title_text)

    if metadata.get('artist'):
        audio['TPE1'] = TPE1(encoding=3, text=sanitize_tag_text(metadata['artist']))

    if metadata.get('year'):
        audio['TDRC'] = TDRC(encoding=3, text=metadata['year'])
    
    if metadata.get('genre'):
        # Eliminar el tag TCON existente si existe (para evitar conflictos)
        if 'TCON' in audio:
            del audio['TCON']
        
        # Limpiar el género de cualquier formato previo (puede venir con paréntesis y números)
        genre_text = str(metadata['genre']).strip()
        # Si el género viene con formato estándar como "(17)House", extraer solo el texto
        if genre_text.startswith('(') and ')' in genre_text:
            genre_text = genre_text.split(')', 1)[1].strip()
        # Limpiar caracteres nulos o problemáticos
        genre_text = genre_text.replace('\x00', '').strip()
        # Escribir el género correctamente (UTF-8 encoding)
        if genre_text:  # Solo escribir si el género no está vacío después de limpiar
            audio['TCON'] = TCON(encoding=3, text=sanitize_tag_text(genre_text))

    # Añadir álbum si está disponible
    if video_info.get('uploader'):
        uploader = sanitize_tag_text(video_info.get('uploader')) or 'Unknown'
        audio['TALB'] = TALB(encoding=3, text=f"YouTube - {uploader}")
    
    # Intentar añadir thumbnail como portada (siempre como JPEG para compatibilidad con DJUCED)
    if video_info.get('thumbnail'):
        try:
            import urllib.request
            import io
            with urllib.request.urlopen(video_info['thumbnail']) as response:
                image_data = response.read()

            # Convertir a JPEG: YouTube sirve WebP y DJUCED no lo muestra.
            # Si Pillow no está disponible se embebe el original antes que perder la portada.
            mime = 'image/jpeg'
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(image_data)).convert('RGB')
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=90)
                image_data = buf.getvalue()
            except ImportError:
                print("⚠️  Pillow no instalado: portada embebida sin convertir a JPEG "
                      "(puede no verse en DJUCED). Instala con: pip install Pillow")
                if image_data[:4] == b'RIFF':
                    mime = 'image/webp'

            audio['APIC'] = APIC(
                encoding=3,
                mime=mime,
                type=3,  # Cover (front)
                desc='Cover',
                data=image_data
            )
        except Exception as e:
            print(f"⚠️  No se pudo embeber la portada: {type(e).__name__}: {e}")
    
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
        'genre': None,
        'youtube_id': None,
    }
    
    try:
        audio = MP3(file_path, ID3=ID3)
        
        # Leer título (TIT2) — saneado para no arrastrar mojibake heredado
        if 'TIT2' in audio:
            metadata['title'] = sanitize_tag_text(str(audio['TIT2'][0]))

        # Leer artista (TPE1)
        if 'TPE1' in audio:
            metadata['artist'] = sanitize_tag_text(str(audio['TPE1'][0]))

        # Leer año (TDRC). Se valida para no propagar un año corrupto ya escrito
        # en el tag hacia la carpeta de década.
        if 'TDRC' in audio:
            metadata['year'] = parse_year(str(audio['TDRC'][0]))
        
        # Leer género (TCON)
        if 'TCON' in audio:
            genre_text = str(audio['TCON'][0])
            # Limpiar el género si viene con formato estándar como "(17)House"
            if genre_text.startswith('(') and ')' in genre_text:
                genre_text = genre_text.split(')', 1)[1].strip()
            metadata['genre'] = sanitize_tag_text(genre_text.strip())

        # Leer YouTube ID (TXXX:YouTube ID)
        if 'TXXX:YouTube ID' in audio:
            metadata['youtube_id'] = str(audio['TXXX:YouTube ID'].text[0])

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
                         video_info: Optional[Dict] = None,
                         log_callback=None) -> Optional[bool]:
    """
    Procesa un archivo MP3 importado: lo copia a la carpeta correcta,
    actualiza metadatos si es necesario y lo registra en la base de datos.
    
    Args:
        file_path: Ruta al archivo MP3
        base_folder: Carpeta base de música
        existing_metadata: Metadatos existentes del archivo (si ya tiene ID3 tags)
        video_info: Información del video de YouTube (si se obtuvo)
        log_callback: Función para logging
    
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
            len(current_genre) < 2):
            # Intentar detectar género online si hay artista
            if metadata.get('artist'):
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
            else:
                # Si no hay artista, intentar directamente con Essentia (análisis de audio)
                metadata['genre'] = 'Sin Clasificar'  # Temporal, se intentará actualizar con Essentia
        elif not current_genre and not genre_is_valid:
            # Si no hay género, usar 'Sin Clasificar' temporalmente
            metadata['genre'] = 'Sin Clasificar'
        elif genre_is_valid:
            # Si el género ya detectado es válido, asegurarse de que se use
            metadata['genre'] = existing_genre
        
        # Si no hay año, usar año actual
        if not metadata.get('year'):
            metadata['year'] = str(datetime.now().year)
        
        # ANTES de determinar la carpeta de destino, intentar usar Essentia si el género es genérico
        # Esto es especialmente útil cuando no hay artista
        if (not metadata.get('genre') or 
            metadata.get('genre', '').lower() in ['sin clasificar', 'unknown', 'desconocido', '']):
            detected_genre = detect_genre_from_audio_file(str(file_path), log_callback=log_callback)
            if detected_genre:
                metadata['genre'] = detected_genre
        
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
            # Si aún no se detectó género o es genérico, intentar con Essentia una vez más
            if (not metadata.get('genre') or 
                metadata.get('genre', '').lower() in ['sin clasificar', 'unknown', 'desconocido', '']):
                detected_genre = detect_genre_from_audio_file(str(file_path), log_callback=log_callback)
                if detected_genre:
                    metadata['genre'] = detected_genre
                    # Si cambió el género, actualizar la carpeta de destino
                    output_folder = get_output_folder(base_folder, metadata.get('genre'), metadata.get('year'))
                    if file_path.parent != output_folder:
                        # El archivo necesita moverse a la nueva carpeta
                        new_filename = output_folder / file_path.name
                        if not new_filename.exists():
                            output_folder.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(file_path), str(new_filename))
                            final_file_path = new_filename
                        else:
                            final_file_path = file_path
                    else:
                        final_file_path = file_path
                else:
                    final_file_path = file_path
            else:
                final_file_path = file_path
            
            # Actualizar metadatos siempre para asegurar que los ID3 tags estén actualizados
            add_id3_tags(str(final_file_path), metadata, video_info or {})
        else:
            # Verificar si el archivo ya existe exactamente (sin variaciones)
            if new_file_path.exists():
                # El archivo ya existe, pero intentar actualizar metadatos si el género cambió
                # Intentar usar Essentia si el género es genérico
                if (not metadata.get('genre') or 
                    metadata.get('genre', '').lower() in ['sin clasificar', 'unknown', 'desconocido', '']):
                    detected_genre = detect_genre_from_audio_file(str(new_file_path), log_callback=log_callback)
                    if detected_genre:
                        metadata['genre'] = detected_genre
                        # Actualizar metadatos del archivo existente
                        add_id3_tags(str(new_file_path), metadata, video_info or {})
                return None
            
            # Mover o copiar el archivo a la nueva ubicación
            # Si ya existe un archivo con ese nombre, añadir número
            counter = 1
            original_new_path = new_file_path
            while new_file_path.exists():
                new_file_path = output_folder / f"{filename} ({counter}).mp3"
                counter += 1

            # Si el archivo ya estaba en la biblioteca hay que MOVERLO: copiarlo
            # dejaría el original en su carpeta anterior (normalmente
            # 'Sin Clasificar') y la canción saldría dos veces en DJUCED, que
            # escanea el disco y no la BD. Lo importado de fuera sí se copia.
            if is_inside_library(file_path, base_folder):
                shutil.move(str(file_path), str(new_file_path))
                if log_callback:
                    src = f"{file_path.parent.parent.name}/{file_path.parent.name}"
                    dst = f"{output_folder.parent.name}/{output_folder.name}"
                    log_callback(f"   ↪️  Movido de {src} a {dst}")
            else:
                shutil.copy2(str(file_path), str(new_file_path))
            
            # Si no se detectó género o es genérico, intentar con Essentia
            if (not metadata.get('genre') or 
                metadata.get('genre', '').lower() in ['sin clasificar', 'unknown', 'desconocido', '']):
                detected_genre = detect_genre_from_audio_file(str(new_file_path), log_callback=log_callback)
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
            title=metadata.get('title'),
            base_folder=base_folder
        )

        if not existing_song:
            # Registrar en base de datos
            # Si no hay video_id, generar uno determinista a partir de la ruta
            if not video_id:
                video_id = stable_imported_video_id(final_file_path, base_folder)
            
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
    
    # Verificar si se quiere probar Essentia
    if len(sys.argv) >= 2 and sys.argv[1] == '--test-essentia':
        success, message = test_essentia_installation()
        print(message)
        if len(sys.argv) >= 3:
            # Probar con un archivo de audio
            audio_file = sys.argv[2]
            if Path(audio_file).exists():
                print(f"\n🎵 Probando análisis de audio: {audio_file}")
                detected_genre = detect_genre_from_audio_file(audio_file)
                if detected_genre:
                    print(f"✅ Género detectado: {detected_genre}")
                else:
                    print("⚠️  No se pudo detectar el género")
            else:
                print(f"❌ Archivo no encontrado: {audio_file}")
        sys.exit(0 if success else 1)
    
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
        print("   o: python download_youtube.py --test-essentia [archivo.mp3]")
        print("\nEjemplo:")
        print("  python download_youtube.py https://www.youtube.com/watch?v=VIDEO_ID")
        print("  python download_youtube.py https://www.youtube.com/watch?v=VIDEO_ID --genre House --artist 'Artista' --year 2023")
        print("  python download_youtube.py --monitor-liked  # Monitorea tu lista de 'me gusta'")
        print("  python download_youtube.py --monitor-liked --playlist-url 'https://music.youtube.com/playlist?list=LM'")
        print("  python download_youtube.py --list-playlists  # Lista tus playlists de YouTube")
        print("  python download_youtube.py --test-cookies  # Prueba si las cookies funcionan")
        print("  python download_youtube.py --test-essentia  # Prueba si Essentia está instalado")
        print("  python download_youtube.py --test-essentia archivo.mp3  # Prueba Essentia con un archivo")
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
        
        # No normalizar volumen en la descarga (se mide y guarda en BD)
        
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

