#!/usr/bin/env python3
"""
Módulo de gestión de base de datos SQLite para el sistema de descarga de música.
"""

import sqlite3
import os
import sys
import threading
import json
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime


class MusicDatabase:
    """Clase para gestionar la base de datos de música."""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Inicializa la conexión a la base de datos.
        
        Args:
            db_path: Ruta al archivo de base de datos. Si es None, usa la ruta por defecto.
        """
        if db_path is None:
            if getattr(sys, 'frozen', False):
                # Ejecutable empaquetado (PyInstaller): base de datos junto al .exe
                # Evita "unable to open database file" en Windows (OneDrive, permisos, etc.)
                base_dir = Path(sys.executable).parent.resolve()
                db_path = base_dir / 'youtube_music.db'
            else:
                db_path = Path.home() / '.youtube_music.db'

        self.db_path = Path(db_path)
        # Usar threading.local() para tener una conexión por thread
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_database()
    
    def _get_connection(self):
        """
        Obtiene una conexión a la base de datos.
        Crea una conexión por thread para evitar problemas de concurrencia.
        """
        # Obtener o crear conexión para el thread actual
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            # Usar check_same_thread=False para permitir uso desde diferentes threads
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False
            )
            self._local.conn.row_factory = sqlite3.Row  # Permite acceso por nombre de columna
            # Habilitar WAL mode para mejor concurrencia
            self._local.conn.execute('PRAGMA journal_mode=WAL')
        return self._local.conn
    
    def _init_database(self):
        """Inicializa las tablas de la base de datos si no existen."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Tabla de canciones descargadas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT,
                year TEXT,
                genre TEXT,
                decade TEXT,
                file_path TEXT UNIQUE NOT NULL,
                file_size INTEGER,
                file_type TEXT,
                duration REAL,
                thumbnail_url TEXT,
                description TEXT,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                download_source TEXT
            )
        ''')
        
        # Migraciones: añadir columnas si no existen (para bases de datos existentes)
        try:
            cursor.execute('ALTER TABLE songs ADD COLUMN download_source TEXT')
        except sqlite3.OperationalError:
            # La columna ya existe, no hacer nada
            pass
        
        try:
            cursor.execute('ALTER TABLE songs ADD COLUMN file_type TEXT')
        except sqlite3.OperationalError:
            # La columna ya existe, no hacer nada
            pass
        
        try:
            cursor.execute('ALTER TABLE songs ADD COLUMN bitrate_kbps INTEGER')
        except sqlite3.OperationalError:
            # La columna ya existe, no hacer nada
            pass
        
        # Índices para búsquedas rápidas
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_video_id ON songs(video_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_artist ON songs(artist)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_genre ON songs(genre)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_year ON songs(year)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_path ON songs(file_path)')
        
        # Tabla de videos rechazados
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rejected_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT UNIQUE NOT NULL,
                url TEXT,
                title TEXT,
                rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reason TEXT
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_rejected_video_id ON rejected_videos(video_id)')
        
        # Tabla de historial de descargas (opcional, para estadísticas)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                action TEXT NOT NULL,  -- 'downloaded', 'rejected', 'skipped', 'failed'
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_video_id ON download_history(video_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_timestamp ON download_history(timestamp)')
        
        # Tabla de caché para datos de videos y clasificaciones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS video_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT UNIQUE NOT NULL,
                video_info TEXT,  -- JSON con información del video
                metadata TEXT,    -- JSON con metadatos extraídos
                genre TEXT,       -- Género detectado
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_cache_video_id ON video_cache(video_id)')
        
        conn.commit()
    
    def add_song(self, video_id: str, url: str, title: str, file_path: str,
                 artist: Optional[str] = None, year: Optional[str] = None,
                 genre: Optional[str] = None, decade: Optional[str] = None,
                 file_size: Optional[int] = None, file_type: Optional[str] = None,
                 duration: Optional[float] = None,
                 thumbnail_url: Optional[str] = None, description: Optional[str] = None,
                 download_source: Optional[str] = None, bitrate_kbps: Optional[int] = None) -> bool:
        """
        Añade una canción a la base de datos.
        
        Returns:
            True si se añadió correctamente, False si ya existe.
        """
        with self._lock:  # Proteger operaciones de escritura
            conn = self._get_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT INTO songs (
                        video_id, url, title, artist, year, genre, decade,
                        file_path, file_size, file_type, duration, thumbnail_url, description, download_source, bitrate_kbps
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (video_id, url, title, artist, year, genre, decade,
                      str(file_path), file_size, file_type, duration, thumbnail_url, description, download_source, bitrate_kbps))
                
                # Registrar en historial
                cursor.execute('''
                    INSERT INTO download_history (video_id, action, notes)
                    VALUES (?, 'downloaded', ?)
                ''', (video_id, f"Downloaded: {title}"))
                
                conn.commit()
                return True
            except sqlite3.IntegrityError as e:
                # Ya existe (video_id o file_path duplicado)
                conn.rollback()
                # Verificar qué causó el error
                error_msg = str(e)
                if 'video_id' in error_msg.lower() or 'UNIQUE constraint failed: songs.video_id' in error_msg:
                    # Verificar si existe por video_id
                    existing = self.get_song_by_video_id(video_id)
                    if existing:
                        print(f"   ⚠️  Ya existe una canción con video_id '{video_id}': {existing.get('title', 'N/A')}")
                elif 'file_path' in error_msg.lower() or 'UNIQUE constraint failed: songs.file_path' in error_msg:
                    # Verificar si existe por file_path
                    existing = self.get_song_by_file_path(str(file_path))
                    if existing:
                        print(f"   ⚠️  Ya existe una canción con file_path '{file_path}': video_id={existing.get('video_id', 'N/A')}")
                return False
    
    def update_song(self, video_id: str, **kwargs) -> bool:
        """
        Actualiza los datos de una canción existente.
        
        Args:
            video_id: ID del video
            **kwargs: Campos a actualizar (artist, year, genre, etc.)
        """
        if not kwargs:
            return False
        
        with self._lock:  # Proteger operaciones de escritura
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Construir query de actualización
            allowed_fields = ['title', 'artist', 'year', 'genre', 'decade', 'file_path',
                             'file_size', 'file_type', 'duration', 'thumbnail_url', 'description', 'download_source', 'bitrate_kbps']
            
            updates = []
            values = []
            
            for key, value in kwargs.items():
                if key in allowed_fields:
                    updates.append(f"{key} = ?")
                    values.append(value)
            
            if not updates:
                return False
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            values.append(video_id)
            
            query = f"UPDATE songs SET {', '.join(updates)} WHERE video_id = ?"
            
            try:
                cursor.execute(query, values)
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                conn.rollback()
                print(f"Error al actualizar canción: {e}")
                return False
    
    def update_song_video_id(self, old_video_id: str, new_video_id: str, **kwargs) -> bool:
        """
        Actualiza el video_id de una canción y opcionalmente otros campos.
        Útil para actualizar canciones importadas con el video_id real de YouTube.
        
        Args:
            old_video_id: Video ID actual (ej: imported_xxx)
            new_video_id: Nuevo video ID (ej: video_id real de YouTube)
            **kwargs: Campos adicionales a actualizar
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Construir query de actualización
            allowed_fields = ['url', 'title', 'artist', 'year', 'genre', 'decade', 'file_path',
                             'file_size', 'file_type', 'duration', 'thumbnail_url', 'description', 'download_source', 'bitrate_kbps']
            
            updates = ['video_id = ?']
            values = [new_video_id]
            
            for key, value in kwargs.items():
                if key in allowed_fields:
                    updates.append(f"{key} = ?")
                    values.append(value)
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            values.append(old_video_id)
            
            query = f"UPDATE songs SET {', '.join(updates)} WHERE video_id = ?"
            
            try:
                cursor.execute(query, values)
                # También actualizar el historial si existe
                cursor.execute('''
                    UPDATE download_history 
                    SET video_id = ? 
                    WHERE video_id = ?
                ''', (new_video_id, old_video_id))
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                conn.rollback()
                print(f"Error al actualizar video_id de canción: {e}")
                return False
    
    def get_song_by_video_id(self, video_id: str) -> Optional[Dict]:
        """Obtiene una canción por su video_id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM songs WHERE video_id = ?', (video_id,))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def get_song_by_file_path(self, file_path: str) -> Optional[Dict]:
        """Obtiene una canción por su ruta de archivo."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM songs WHERE file_path = ?', (str(file_path),))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def find_song(self, artist: Optional[str] = None, title: Optional[str] = None,
                  video_id: Optional[str] = None) -> List[Dict]:
        """
        Busca canciones por artista, título o video_id.
        
        Returns:
            Lista de canciones que coinciden.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        conditions = []
        params = []
        
        if video_id:
            conditions.append("video_id = ?")
            params.append(video_id)
        
        if artist:
            conditions.append("artist LIKE ?")
            params.append(f"%{artist}%")
        
        if title:
            conditions.append("title LIKE ?")
            params.append(f"%{title}%")
        
        if not conditions:
            return []
        
        query = f"SELECT * FROM songs WHERE {' AND '.join(conditions)}"
        cursor.execute(query, params)
        
        return [dict(row) for row in cursor.fetchall()]
    
    def song_exists(self, video_id: Optional[str] = None, 
                   artist: Optional[str] = None, 
                   title: Optional[str] = None) -> bool:
        """
        Verifica si una canción ya existe en la base de datos.
        
        Args:
            video_id: ID del video (más preciso)
            artist: Nombre del artista
            title: Título de la canción
        
        Returns:
            True si existe, False si no.
        """
        if video_id:
            song = self.get_song_by_video_id(video_id)
            if song:
                return True
        
        if artist and title:
            songs = self.find_song(artist=artist, title=title)
            if songs:
                return True
        
        return False
    
    def add_rejected_video(self, video_id: str, url: Optional[str] = None,
                          title: Optional[str] = None, reason: Optional[str] = None) -> bool:
        """Añade un video a la lista de rechazados."""
        with self._lock:  # Proteger operaciones de escritura
            conn = self._get_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT INTO rejected_videos (video_id, url, title, reason)
                    VALUES (?, ?, ?, ?)
                ''', (video_id, url, title, reason))
                
                # Registrar en historial
                cursor.execute('''
                    INSERT INTO download_history (video_id, action, notes)
                    VALUES (?, 'rejected', ?)
                ''', (video_id, reason or "User rejected"))
                
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Ya existe
                conn.rollback()
                return False
    
    def is_rejected(self, video_id: str) -> bool:
        """Verifica si un video está rechazado."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM rejected_videos WHERE video_id = ?', (video_id,))
        return cursor.fetchone() is not None
    
    def get_all_rejected_videos(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Obtiene todas las canciones ignoradas/rechazadas.
        
        Args:
            limit: Número máximo de resultados
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM rejected_videos ORDER BY rejected_at DESC"
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]
    
    def remove_rejected_video(self, video_id: str) -> bool:
        """
        Elimina un video de la lista de rechazados (designorar).
        
        Args:
            video_id: ID del video a designorar
        
        Returns:
            True si se eliminó correctamente, False si no se encontró.
        """
        with self._lock:  # Proteger operaciones de escritura
            conn = self._get_connection()
            cursor = conn.cursor()
            
            try:
                # Verificar si existe
                cursor.execute('SELECT 1 FROM rejected_videos WHERE video_id = ?', (video_id,))
                if not cursor.fetchone():
                    return False
                
                # Eliminar de la tabla de rechazados
                cursor.execute('DELETE FROM rejected_videos WHERE video_id = ?', (video_id,))
                
                # Registrar en historial
                cursor.execute('''
                    INSERT INTO download_history (video_id, action, notes)
                    VALUES (?, 'unrejected', ?)
                ''', (video_id, "Video unmarked as rejected"))
                
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                print(f"Error al designorar video: {e}")
                return False
    
    def get_all_songs(self, limit: Optional[int] = None, 
                     genre: Optional[str] = None,
                     decade: Optional[str] = None) -> List[Dict]:
        """
        Obtiene todas las canciones, opcionalmente filtradas.
        
        Args:
            limit: Número máximo de resultados
            genre: Filtrar por género
            decade: Filtrar por década
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        conditions = []
        params = []
        
        if genre:
            conditions.append("genre = ?")
            params.append(genre)
        
        if decade:
            conditions.append("decade = ?")
            params.append(decade)
        
        query = "SELECT * FROM songs"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY downloaded_at DESC"
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def get_statistics(self) -> Dict:
        """Obtiene estadísticas de la base de datos."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        # Total de canciones
        cursor.execute('SELECT COUNT(*) FROM songs')
        stats['total_songs'] = cursor.fetchone()[0]
        
        # Canciones por género
        cursor.execute('''
            SELECT genre, COUNT(*) as count 
            FROM songs 
            WHERE genre IS NOT NULL 
            GROUP BY genre 
            ORDER BY count DESC
        ''')
        stats['by_genre'] = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Canciones por década
        cursor.execute('''
            SELECT decade, COUNT(*) as count 
            FROM songs 
            WHERE decade IS NOT NULL 
            GROUP BY decade 
            ORDER BY decade DESC
        ''')
        stats['by_decade'] = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Total de rechazados
        cursor.execute('SELECT COUNT(*) FROM rejected_videos')
        stats['rejected_count'] = cursor.fetchone()[0]
        
        # Tamaño total de archivos
        cursor.execute('SELECT SUM(file_size) FROM songs WHERE file_size IS NOT NULL')
        result = cursor.fetchone()[0]
        stats['total_size_bytes'] = result if result else 0
        
        return stats
    
    def delete_song(self, video_id: str) -> Optional[Dict]:
        """
        Elimina una canción de la base de datos.
        
        Args:
            video_id: ID del video a eliminar
        
        Returns:
            Diccionario con los datos de la canción eliminada (incluyendo file_path) si existe,
            None si no se encontró.
        """
        with self._lock:  # Proteger operaciones de escritura
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Primero obtener los datos de la canción antes de eliminarla
            song = self.get_song_by_video_id(video_id)
            if not song:
                return None
            
            try:
                # Eliminar de la tabla de canciones
                cursor.execute('DELETE FROM songs WHERE video_id = ?', (video_id,))
                
                # Registrar en historial
                cursor.execute('''
                    INSERT INTO download_history (video_id, action, notes)
                    VALUES (?, 'deleted', ?)
                ''', (video_id, f"Deleted: {song.get('title', 'Unknown')}"))
                
                conn.commit()
                return dict(song)  # Devolver los datos de la canción eliminada
            except Exception as e:
                conn.rollback()
                print(f"Error al eliminar canción: {e}")
                return None
    
    def get_cached_video_info(self, video_id: str) -> Optional[Dict]:
        """
        Obtiene la información del video desde la caché.
        
        Args:
            video_id: ID del video de YouTube
        
        Returns:
            Diccionario con información del video o None si no está en caché
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT video_info FROM video_cache WHERE video_id = ?', (video_id,))
        row = cursor.fetchone()
        
        if row and row[0]:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None
        return None
    
    def get_cached_metadata(self, video_id: str) -> Optional[Dict]:
        """
        Obtiene los metadatos desde la caché.
        
        Args:
            video_id: ID del video de YouTube
        
        Returns:
            Diccionario con metadatos o None si no está en caché
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT metadata FROM video_cache WHERE video_id = ?', (video_id,))
        row = cursor.fetchone()
        
        if row and row[0]:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None
        return None
    
    def get_cached_genre(self, video_id: str) -> Optional[str]:
        """
        Obtiene el género desde la caché.
        
        Args:
            video_id: ID del video de YouTube
        
        Returns:
            Género como string o None si no está en caché
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT genre FROM video_cache WHERE video_id = ?', (video_id,))
        row = cursor.fetchone()
        
        if row and row[0]:
            return row[0]
        return None
    
    def set_cached_video_info(self, video_id: str, video_info: Dict) -> bool:
        """
        Guarda la información del video en la caché.
        
        Args:
            video_id: ID del video de YouTube
            video_info: Diccionario con información del video
        
        Returns:
            True si se guardó correctamente
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            try:
                video_info_json = json.dumps(video_info, default=str)
                
                cursor.execute('''
                    INSERT INTO video_cache (video_id, video_info, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(video_id) DO UPDATE SET
                        video_info = excluded.video_info,
                        updated_at = CURRENT_TIMESTAMP
                ''', (video_id, video_info_json))
                
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                print(f"Error al guardar video_info en caché: {e}")
                return False
    
    def set_cached_metadata(self, video_id: str, metadata: Dict) -> bool:
        """
        Guarda los metadatos en la caché.
        
        Args:
            video_id: ID del video de YouTube
            metadata: Diccionario con metadatos
        
        Returns:
            True si se guardó correctamente
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            try:
                metadata_json = json.dumps(metadata, default=str)
                
                cursor.execute('''
                    INSERT INTO video_cache (video_id, metadata, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(video_id) DO UPDATE SET
                        metadata = excluded.metadata,
                        updated_at = CURRENT_TIMESTAMP
                ''', (video_id, metadata_json))
                
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                print(f"Error al guardar metadata en caché: {e}")
                return False
    
    def set_cached_genre(self, video_id: str, genre: str) -> bool:
        """
        Guarda el género en la caché.
        
        Args:
            video_id: ID del video de YouTube
            genre: Género como string
        
        Returns:
            True si se guardó correctamente
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT INTO video_cache (video_id, genre, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(video_id) DO UPDATE SET
                        genre = excluded.genre,
                        updated_at = CURRENT_TIMESTAMP
                ''', (video_id, genre))
                
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                print(f"Error al guardar género en caché: {e}")
                return False
    
    def get_all_cached_data(self, video_id: str) -> Optional[Dict]:
        """
        Obtiene todos los datos en caché para un video (info, metadata, genre).
        
        Args:
            video_id: ID del video de YouTube
        
        Returns:
            Diccionario con 'video_info', 'metadata', 'genre' o None si no está en caché
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT video_info, metadata, genre 
            FROM video_cache 
            WHERE video_id = ?
        ''', (video_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        result = {}
        
        if row[0]:  # video_info
            try:
                result['video_info'] = json.loads(row[0])
            except json.JSONDecodeError:
                pass
        
        if row[1]:  # metadata
            try:
                result['metadata'] = json.loads(row[1])
            except json.JSONDecodeError:
                pass
        
        if row[2]:  # genre
            result['genre'] = row[2]
        
        return result if result else None
    
    def clear_cache(self, video_id: Optional[str] = None) -> bool:
        """
        Limpia la caché. Si se proporciona video_id, solo limpia ese video.
        
        Args:
            video_id: ID del video específico o None para limpiar toda la caché
        
        Returns:
            True si se limpió correctamente
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            try:
                if video_id:
                    cursor.execute('DELETE FROM video_cache WHERE video_id = ?', (video_id,))
                else:
                    cursor.execute('DELETE FROM video_cache')
                
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                print(f"Error al limpiar caché: {e}")
                return False
    
    def close(self):
        """Cierra la conexión a la base de datos del thread actual."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

