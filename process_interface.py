#!/usr/bin/env python3
"""
Interfaz de comunicación entre la IDE y los procesos de descarga.
Esta capa permite que la IDE se comunique con los procesos sin importarlos directamente,
permitiendo actualizar el código de los procesos sin modificar la IDE.

USO:
    # En lugar de importar directamente:
    # from download_youtube import download_audio
    
    # Usa la interfaz:
    from process_interface import get_interface
    interface = get_interface()
    result = interface.download_quick(url)
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable
from datetime import datetime


class ProcessInterface:
    """
    Interfaz para comunicarse con los procesos de descarga.
    Ejecuta los scripts como subprocesos independientes.
    
    Esta clase permite que la IDE se comunique con los procesos sin importarlos,
    lo que permite actualizar el código de los procesos sin reiniciar la IDE.
    """
    
    def __init__(self, base_dir: Optional[str] = None, use_direct_imports: bool = False):
        """
        Inicializa la interfaz.
        
        Args:
            base_dir: Directorio base donde están los scripts. Si es None, usa el directorio actual.
            use_direct_imports: Si True, usa imports directos (modo rápido, sin separación).
                              Si False, usa subprocesos (modo separado, permite actualizar procesos).
        """
        if base_dir is None:
            base_dir = Path(__file__).parent
        self.base_dir = Path(base_dir)
        self.python_executable = sys.executable
        self.use_direct_imports = use_direct_imports
        
        # Cache de módulos importados (para modo directo)
        self._imported_modules = {}
    
    def _import_module(self, module_name: str):
        """Importa un módulo dinámicamente (solo en modo directo)."""
        if module_name not in self._imported_modules:
            if module_name == 'download_youtube':
                from download_youtube import (
                    download_audio, get_video_info, extract_metadata_from_title,
                    detect_genre_online, get_output_folder, check_file_exists,
                    register_song_in_db, add_id3_tags, monitor_liked_videos,
                    save_rejected_video, is_rejected_video, sanitize_filename,
                    get_liked_videos, get_genre_from_title_keywords, get_liked_videos_from_url
                )
                self._imported_modules[module_name] = {
                    'download_audio': download_audio,
                    'get_video_info': get_video_info,
                    'extract_metadata_from_title': extract_metadata_from_title,
                    'detect_genre_online': detect_genre_online,
                    'get_output_folder': get_output_folder,
                    'check_file_exists': check_file_exists,
                    'register_song_in_db': register_song_in_db,
                    'add_id3_tags': add_id3_tags,
                    'monitor_liked_videos': monitor_liked_videos,
                    'save_rejected_video': save_rejected_video,
                    'is_rejected_video': is_rejected_video,
                    'sanitize_filename': sanitize_filename,
                    'get_liked_videos': get_liked_videos,
                    'get_genre_from_title_keywords': get_genre_from_title_keywords,
                    'get_liked_videos_from_url': get_liked_videos_from_url,
                }
            elif module_name == 'download_quick':
                from download_quick import download_quick
                self._imported_modules[module_name] = {'download_quick': download_quick}
            elif module_name == 'database':
                from database import MusicDatabase
                import os
                from dotenv import load_dotenv
                load_dotenv()
                DB_PATH = os.getenv('DB_PATH', None)
                self._imported_modules[module_name] = {
                    'MusicDatabase': MusicDatabase,
                    'db_instance': MusicDatabase(DB_PATH)
                }
            elif module_name == 'query_db':
                from query_db import show_statistics, search_songs
                self._imported_modules[module_name] = {
                    'show_statistics': show_statistics,
                    'search_songs': search_songs
                }
        return self._imported_modules[module_name]
    
    def _run_process(self, script_name: str, args: List[str] = None, 
                    capture_output: bool = True) -> Dict[str, Any]:
        """
        Ejecuta un script Python como subproceso.
        
        Args:
            script_name: Nombre del script a ejecutar (ej: 'download_youtube.py')
            args: Argumentos de línea de comandos
            capture_output: Si True, captura la salida del proceso
        
        Returns:
            Diccionario con 'success', 'output', 'error', 'returncode'
        """
        if args is None:
            args = []
        
        script_path = self.base_dir / script_name
        if not script_path.exists():
            return {
                'success': False,
                'error': f"Script no encontrado: {script_path}",
                'output': '',
                'returncode': -1
            }
        
        try:
            # Ejecutar el script
            cmd = [self.python_executable, str(script_path)] + args
            
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                cwd=str(self.base_dir),
                timeout=600  # 10 minutos de timeout
            )
            
            output = result.stdout if capture_output else ''
            error = result.stderr if capture_output else ''
            
            return {
                'success': result.returncode == 0,
                'output': output,
                'error': error,
                'returncode': result.returncode
            }
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Timeout: El proceso tardó demasiado',
                'output': '',
                'returncode': -1
            }
        except Exception as e:
            return {
                'success': False,
                'error': f"Error al ejecutar proceso: {e}",
                'output': '',
                'returncode': -1
            }
    
    def download_quick(self, url: str) -> Dict[str, Any]:
        """
        Ejecuta descarga rápida.
        
        Args:
            url: URL de YouTube
        
        Returns:
            Resultado del proceso con 'success', 'output', 'error'
        """
        if self.use_direct_imports:
            # Modo directo: importar y ejecutar
            try:
                module = self._import_module('download_quick')
                module['download_quick'](url)
                return {'success': True, 'output': 'Descarga completada', 'error': ''}
            except Exception as e:
                return {'success': False, 'output': '', 'error': str(e)}
        else:
            # Modo separado: ejecutar como subproceso
            return self._run_process('download_quick.py', args=[url])
    
    def download_with_metadata(self, url: str, genre: Optional[str] = None,
                              artist: Optional[str] = None, 
                              year: Optional[str] = None) -> Dict[str, Any]:
        """
        Ejecuta descarga con metadatos.
        
        Args:
            url: URL de YouTube
            genre: Género (opcional)
            artist: Artista (opcional)
            year: Año (opcional)
        
        Returns:
            Resultado del proceso
        """
        if self.use_direct_imports:
            # Modo directo: usar imports (requiere implementación más compleja)
            # Por ahora, usar subproceso también
            pass
        
        args = [url]
        if genre:
            args.extend(['--genre', genre])
        if artist:
            args.extend(['--artist', artist])
        if year:
            args.extend(['--year', year])
        
        return self._run_process('download_youtube.py', args=args)
    
    # Métodos para acceso directo a funciones (modo directo)
    def get_video_info_direct(self, url: str):
        """Obtiene información del video usando import directo."""
        if not self.use_direct_imports:
            raise RuntimeError("Este método solo está disponible en modo directo (use_direct_imports=True)")
        module = self._import_module('download_youtube')
        return module['get_video_info'](url)
    
    def check_file_exists_direct(self, video_id: Optional[str] = None,
                                artist: Optional[str] = None,
                                title: Optional[str] = None):
        """Verifica si un archivo existe usando import directo."""
        if not self.use_direct_imports:
            raise RuntimeError("Este método solo está disponible en modo directo (use_direct_imports=True)")
        module = self._import_module('download_youtube')
        return module['check_file_exists'](video_id=video_id, artist=artist, title=title)
    
    def get_liked_videos_direct(self, playlist_url: Optional[str] = None, limit: int = 20):
        """Obtiene videos de 'me gusta' usando import directo."""
        if not self.use_direct_imports:
            raise RuntimeError("Este método solo está disponible en modo directo (use_direct_imports=True)")
        module = self._import_module('download_youtube')
        if playlist_url:
            return module['get_liked_videos_from_url'](playlist_url, limit=limit)
        else:
            return module['get_liked_videos'](limit=limit)
    
    def get_database_direct(self):
        """Obtiene instancia de base de datos usando import directo."""
        if not self.use_direct_imports:
            raise RuntimeError("Este método solo está disponible en modo directo (use_direct_imports=True)")
        module = self._import_module('database')
        return module['db_instance']


# Instancia global para uso fácil
_interface = None

def get_interface(use_direct_imports: bool = False) -> ProcessInterface:
    """
    Obtiene la instancia global de la interfaz.
    
    Args:
        use_direct_imports: Si True, usa imports directos (más rápido pero sin separación).
                          Si False, usa subprocesos (separado, permite actualizar procesos).
    
    Returns:
        Instancia de ProcessInterface
    """
    global _interface
    if _interface is None or _interface.use_direct_imports != use_direct_imports:
        _interface = ProcessInterface(use_direct_imports=use_direct_imports)
    return _interface

