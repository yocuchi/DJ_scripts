#!/usr/bin/env python3
"""
Interfaz gráfica (GUI) para llamar a los métodos del programa de descarga de música.
"""

import sys
import os
import re
import threading
import webbrowser
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Configurar DISPLAY para WSL si no está configurado
if not os.getenv('DISPLAY'):
    # Intentar WSLg primero
    if os.path.exists('/tmp/.X11-unix/X0'):
        os.environ['DISPLAY'] = ':0'
        print("✓ DISPLAY configurado para WSLg: :0")
    else:
        # Intentar con IP de Windows (para VcXsrv/X410)
        try:
            result = subprocess.run(['ip', 'route'], capture_output=True, text=True, timeout=2)
            for line in result.stdout.split('\n'):
                if 'default' in line:
                    windows_ip = line.split()[2]
                    os.environ['DISPLAY'] = f'{windows_ip}:0.0'
                    print(f"✓ DISPLAY configurado para servidor X11: {os.environ['DISPLAY']}")
                    break
        except:
            # Último intento con valor por defecto
            os.environ['DISPLAY'] = ':0'
            print("⚠️  Usando DISPLAY=:0 por defecto")

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog, filedialog

# Importar PIL para manejar imágenes
try:
    from PIL import Image, ImageTk
    import urllib.request
    import io
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Intentar importar PyQt6 WebEngine para videos embebidos (opcional)
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtCore import QUrl, Qt
    from PyQt6.QtWidgets import QApplication
    PYQT6_WEBENGINE_AVAILABLE = True
except ImportError:
    PYQT6_WEBENGINE_AVAILABLE = False
    print("⚠️  PyQt6 WebEngine no está instalado. Los videos embebidos abrirán en el navegador.")
    print("💡 Para videos embebidos con JavaScript, instala: pip install PyQt6 PyQt6-WebEngine")

# Importar módulos del proyecto
import shutil
import download_youtube as dy_module
from database import MusicDatabase

from download_youtube import (
    download_audio, get_video_info, extract_metadata_from_title,
    detect_genre_online, get_output_folder, check_file_exists,
    register_song_in_db, add_id3_tags, monitor_liked_videos,
    save_rejected_video, is_rejected_video, sanitize_filename,
    check_and_normalize_audio,
    get_liked_videos, get_genre_from_title_keywords, get_liked_videos_from_url,
    get_genre_from_database, get_genre_from_video_tags, get_genre_from_channel_name,
    get_genre_from_description_deep, get_genre_from_lastfm, get_genre_from_musicbrainz,
    get_genre_from_web_search, get_genre_from_hashtags, get_genre_from_spotify_search,
    read_id3_tags, search_youtube_music_url, process_imported_mp3, get_decade_from_year,
    detect_genre_from_audio_file
)
from download_quick import download_quick
from query_db import show_statistics, search_songs

# Cargar variables de entorno
load_dotenv()

# Inicializar base de datos
DB_PATH = os.getenv('DB_PATH', None)
db = MusicDatabase(DB_PATH)
MUSIC_FOLDER = os.getenv('MUSIC_FOLDER', os.path.expanduser('~/Music'))

# Información del software
SOFTWARE_NAME = "DJ_CUCHIDownloader"
GITHUB_URL = "https://github.com/yocuchi/DJ_scripts"


class MusicDownloaderGUI:
    """Interfaz gráfica para el gestor de descarga de música."""
    
    def __init__(self, root):
        self.root = root
        self.root.title("🎵 Gestor de Música para DJ")
        self.root.geometry("900x700")
        self.root.configure(bg='#f0f0f0')
        
        # Detectar y configurar fuentes con soporte de emojis
        self.emoji_font = self._detect_emoji_font()
        self.default_font = ('Arial', 11)
        
        # Configurar fallback de fuentes para emojis
        self._configure_font_fallback()
        
        # Variables
        self.url_var = tk.StringVar()
        self.test_url_var = tk.StringVar()  # URL para probar clasificación (sin auto-descarga)
        
        # Variable para rastrear si estamos descargando
        self._downloading = False
        self._last_url = ""  # Para evitar descargas duplicadas
        
        # Variables para pestaña de monitoreo
        self.liked_limit_var = tk.StringVar(value="10")
        self.liked_playlist_url_var = tk.StringVar(value="https://music.youtube.com/playlist?list=LM")  # URL por defecto de "Me gusta"
        self.liked_hide_ignored_var = tk.BooleanVar(value=True)  # Ocultar ignoradas y descargadas por defecto
        self.liked_checkboxes = {}  # Diccionario para guardar checkboxes: {video_id: checkbox_var}
        self.liked_videos_data = []  # Lista de datos de videos
        self.downloading_videos = {}  # Diccionario para rastrear videos en descarga: {video_id: song_frame}
        self.song_frames = {}  # Diccionario para guardar referencias a los frames de cada canción: {video_id: song_frame}
        self.thumbnail_labels = {}  # Diccionario para guardar referencias a los thumbnails: {video_id: thumbnail_label}
        self.video_players = {}  # Diccionario para guardar reproductores activos: {video_id: webview o widget}
        
        # Sistema de caché para datos y clasificaciones
        self._video_info_cache = {}  # {video_id: video_info}
        self._metadata_cache = {}  # {video_id: metadata}
        self._genre_cache = {}  # {video_id: genre}
        
        # Variables para pestaña de base de datos
        self.db_search_results = []
        self.db_show_ignored_only_var = tk.BooleanVar(value=False)  # Checkbox para mostrar solo ignoradas
        self.db_all_data = []  # Almacenar todos los datos para filtrado
        self.db_sort_column = None  # Columna actual de ordenamiento
        self.db_sort_reverse = False  # Dirección del ordenamiento
        self.db_global_search_var = tk.StringVar()  # Variable para búsqueda global
        
        # Inicializar CEF si está disponible
        
        self.setup_ui()
        
        # Configurar estilos para estados de descarga
        self.setup_styles()
        
        # Configurar redirección de salida para capturar prints
        self.setup_output_capture()
    
    def setup_styles(self):
        """Configura estilos personalizados para los frames."""
        style = ttk.Style()
        
        # Estilo para frame en descarga (fondo gris)
        style.configure('Downloading.TFrame', background='#e0e0e0')
        
        # Estilo para frame con error
        style.configure('Error.TFrame', background='#ffe0e0')
    
    def _detect_emoji_font(self):
        """Detecta una fuente con soporte de emojis."""
        import subprocess
        
        # Verificar si estamos en WSL
        is_wsl = os.path.exists('/proc/version') and 'microsoft' in open('/proc/version').read().lower()
        
        # Lista de fuentes a probar (en orden de preferencia)
        # Nota: Algunas fuentes tienen mejor soporte de emojis que otras
        emoji_fonts = [
            'Noto Color Emoji',
            'Noto Emoji',
            'Noto Sans',
            'Apple Color Emoji',
            'Segoe UI Emoji',
            'DejaVu Sans',
            'Liberation Sans',
            'Arial'
        ]
        
        try:
            # Obtener lista de fuentes disponibles
            result = subprocess.run(['fc-list', ':', 'family'], 
                                 capture_output=True, text=True, timeout=2)
            available_fonts = result.stdout.lower()
            
            # Buscar la primera fuente disponible
            for font in emoji_fonts:
                if font.lower() in available_fonts:
                    if is_wsl:
                        print(f"✓ WSL detectado. Usando fuente: {font}")
                        print("💡 Si los emojis no se ven, instala: sudo apt-get install fonts-noto-color-emoji")
                    else:
                        print(f"✓ Usando fuente: {font}")
                    return font
            
            if is_wsl:
                print("⚠️  WSL detectado. No se encontró fuente con emojis, usando Arial")
                print("💡 Para ver emojis en WSL, instala:")
                print("   sudo apt-get update")
                print("   sudo apt-get install fonts-noto-color-emoji")
                print("   fc-cache -f -v")
            else:
                print("⚠️  No se encontró fuente con emojis, usando Arial")
                print("💡 Instala fuentes de emojis para mejor soporte:")
                print("   sudo apt-get install fonts-noto-color-emoji")
            return 'Arial'
        except:
            print("⚠️  No se pudo detectar fuentes, usando Arial")
            if is_wsl:
                print("💡 Para emojis en WSL: sudo apt-get install fonts-noto-color-emoji")
            return 'Arial'
    
    def _get_best_font_for_emojis(self):
        """Obtiene la mejor fuente para mostrar emojis."""
        import subprocess
        
        # Fuentes que tienen mejor soporte de emojis (texto + emojis)
        best_fonts = [
            'Noto Sans',
            'DejaVu Sans',
            'Liberation Sans',
            'Arial'
        ]
        
        try:
            result = subprocess.run(['fc-list', ':', 'family'], 
                                   capture_output=True, text=True, timeout=2)
            available_fonts = result.stdout.lower()
            
            for font in best_fonts:
                if font.lower() in available_fonts:
                    return font
        except:
            pass
        
        return self.emoji_font
    
    def _configure_font_fallback(self):
        """Configura fallback de fuentes para emojis usando fontconfig."""
        import subprocess
        
        # Verificar si estamos en WSL
        is_wsl = os.path.exists('/proc/version') and 'microsoft' in open('/proc/version').read().lower()
        
        # Crear configuración de fontconfig para usar Noto Color Emoji como fallback
        config_dir = Path.home() / '.config' / 'fontconfig'
        config_dir.mkdir(parents=True, exist_ok=True)
        
        config_file = config_dir / 'fonts.conf'
        
        # Verificar si Noto Color Emoji está disponible
        try:
            result = subprocess.run(['fc-list', ':', 'family'], 
                                   capture_output=True, text=True, timeout=2)
            has_noto_emoji = 'noto color emoji' in result.stdout.lower() or 'noto emoji' in result.stdout.lower()
            
            if has_noto_emoji and not config_file.exists():
                # Crear configuración de fontconfig
                fontconfig = '''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <!-- Usar Noto Color Emoji como fallback para emojis -->
  <alias>
    <family>sans-serif</family>
    <prefer>
      <family>Noto Color Emoji</family>
      <family>Noto Emoji</family>
    </prefer>
  </alias>
  <alias>
    <family>serif</family>
    <prefer>
      <family>Noto Color Emoji</family>
      <family>Noto Emoji</family>
    </prefer>
  </alias>
  <alias>
    <family>monospace</family>
    <prefer>
      <family>Noto Color Emoji</family>
      <family>Noto Emoji</family>
    </prefer>
  </alias>
</fontconfig>'''
                
                try:
                    with open(config_file, 'w') as f:
                        f.write(fontconfig)
                    if is_wsl:
                        print("✓ Configuración de fontconfig creada para mejor soporte de emojis en WSL")
                    else:
                        print("✓ Configuración de fontconfig creada para mejor soporte de emojis")
                    # Actualizar caché
                    subprocess.run(['fc-cache', '-f'], timeout=5, capture_output=True)
                except:
                    pass  # Si no se puede escribir, continuar sin configuración
            elif is_wsl and not has_noto_emoji:
                print("💡 Para emojis en WSL, instala: sudo apt-get install fonts-noto-color-emoji")
        except:
            pass  # Si no se puede configurar, continuar sin fallback
    
    def setup_ui(self):
        """Configura la interfaz de usuario con pestañas."""
        # Frame principal
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # Título - usar fuente con mejor soporte de emojis
        title_font = self._get_best_font_for_emojis()
        title_label = ttk.Label(main_frame, text="🎵 Gestor de Música para DJ", 
                               font=(title_font, 16, 'bold'))
        title_label.grid(row=0, column=0, pady=(0, 10))
        
        # Crear notebook (pestañas)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        # Pestaña 1: Descarga
        self.setup_download_tab()
        
        # Pestaña 2: Base de Datos
        self.setup_database_tab()
        
        # Pestaña 3: Monitorear "Me Gusta"
        self.setup_monitor_tab()
        
        # Pestaña 4: Importar Carpeta
        self.setup_import_tab()
        
        # Pestaña 5: Testing/Pruebas
        self.setup_testing_tab()
        
        # Pestaña 6: Configuración
        self.setup_config_tab()

        # Pestaña 7: About
        self.setup_about_tab()
    
    def setup_download_tab(self):
        """Configura la pestaña de descarga."""
        download_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(download_tab, text="📥 Descargar")
        download_tab.columnconfigure(0, weight=1)
        download_tab.rowconfigure(2, weight=1)
        
        # Sección de URL para descarga directa
        url_frame = ttk.LabelFrame(download_tab, text="URL de YouTube (Descarga Directa)", padding="10")
        url_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        url_frame.columnconfigure(0, weight=1)
        
        url_entry = ttk.Entry(url_frame, textvariable=self.url_var, font=self.default_font)
        url_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5)
        url_entry.bind('<Control-v>', self.paste_url)
        # Detectar cuando se pega texto (también funciona con botón derecho -> pegar)
        # Usar un delay más largo para evitar múltiples disparos
        url_entry.bind('<Button-3>', lambda e: self.root.after(300, self.check_url_and_download))
        url_entry.focus_set()
        
        paste_btn = ttk.Button(url_frame, text="📋 Pegar URL", command=self.paste_url)
        paste_btn.grid(row=0, column=1, padx=5)
        
        # Botones principales
        buttons_frame = ttk.Frame(download_tab, padding="10")
        buttons_frame.grid(row=1, column=0, pady=10)
        
        download_btn = ttk.Button(buttons_frame, text="📥 Descargar (con metadatos)", 
                                  command=self.download_with_metadata, width=25)
        download_btn.grid(row=0, column=0, padx=5, pady=5)
        
        info_btn = ttk.Button(buttons_frame, text="🎵 Info del Video", 
                             command=self.show_video_info, width=25)
        info_btn.grid(row=0, column=1, padx=5, pady=5)
        
        # Área de log/resultados
        log_frame = ttk.LabelFrame(download_tab, text="Log / Resultados", padding="10")
        log_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        download_tab.rowconfigure(3, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, width=80, 
                                                   font=('Consolas', 10), wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        clear_btn = ttk.Button(log_frame, text="🗑️ Limpiar Log", command=self.clear_log)
        clear_btn.grid(row=1, column=0, pady=5)
    
    def setup_database_tab(self):
        """Configura la pestaña de base de datos."""
        db_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(db_tab, text="💾 Base de Datos")
        db_tab.columnconfigure(0, weight=1)
        db_tab.rowconfigure(1, weight=1)
        
        # Controles de búsqueda
        search_frame = ttk.LabelFrame(db_tab, text="Buscar", padding="10")
        search_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        search_frame.columnconfigure(1, weight=1)
        
        # Búsqueda global que filtra en todas las columnas
        ttk.Label(search_frame, text="🔍 Buscar en todas las columnas:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        search_entry = ttk.Entry(search_frame, textvariable=self.db_global_search_var, width=50)
        search_entry.grid(row=0, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        # Filtrar en tiempo real mientras se escribe
        self.db_global_search_var.trace('w', lambda *args: self.filter_database_table())
        
        # Botones y controles
        buttons_frame = ttk.Frame(search_frame)
        buttons_frame.grid(row=0, column=2, padx=10, pady=5, sticky=tk.W)
        
        ttk.Button(buttons_frame, text="🔄 Actualizar", command=self.load_all_songs).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="📊 Estadísticas", command=self.show_statistics_tab).pack(side=tk.LEFT, padx=2)
        
        # Checkbox para mostrar solo ignoradas
        ttk.Checkbutton(search_frame, text="Mostrar solo ignoradas", 
                       variable=self.db_show_ignored_only_var,
                       command=self.load_all_songs).grid(row=1, column=0, columnspan=3, padx=5, pady=2, sticky=tk.W)
        
        # Área de resultados
        results_frame = ttk.LabelFrame(db_tab, text="Resultados", padding="10")
        results_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        
        # Treeview para mostrar resultados
        columns = ('Título', 'Artista', 'Género', 'Año', 'Tamaño (MB)', 'Tipo', 'Calidad (kbps)', 'Fecha Descarga', 'Origen', 'URL', 'Archivo')
        self.db_tree = ttk.Treeview(results_frame, columns=columns, show='headings', height=20)
        
        # Configurar encabezados y anchos de columna
        column_widths = {
            'Título': 200,
            'Artista': 150,
            'Género': 120,
            'Año': 60,
            'Tamaño (MB)': 80,
            'Tipo': 50,
            'Calidad (kbps)': 100,
            'Fecha Descarga': 120,
            'Origen': 100,
            'URL': 200,
            'Archivo': 200
        }
        
        for col in columns:
            # Configurar ordenamiento al hacer clic en los encabezados
            self.db_tree.heading(col, text=col, command=lambda c=col: self.sort_treeview_column(c))
            self.db_tree.column(col, width=column_widths.get(col, 150), minwidth=50)
        
        # Configurar columnas para que se expandan
        self.db_tree.column('Título', stretch=tk.YES)
        self.db_tree.column('URL', stretch=tk.YES)
        self.db_tree.column('Archivo', stretch=tk.YES)
        
        scrollbar = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.db_tree.yview)
        self.db_tree.configure(yscrollcommand=scrollbar.set)
        
        self.db_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Menú contextual (clic derecho)
        self.db_context_menu = tk.Menu(self.root, tearoff=0)
        self.db_context_menu.add_command(label="🎵 Escuchar integrado", command=self.play_selected_song)
        self.db_context_menu.add_command(label="📁 Ver fichero en carpeta", command=self.open_file_in_folder)
        self.db_context_menu.add_separator()
        self.db_context_menu.add_command(label="🗑️ Eliminar fichero", command=self.delete_file_from_context_menu)
        
        # Binding del clic derecho (multiplataforma)
        def on_right_click(event):
            # Seleccionar el item bajo el cursor
            item = self.db_tree.identify_row(event.y)
            if item:
                self.db_tree.selection_set(item)
                self.show_db_context_menu(event)
        
        # Linux usa Button-3, Windows/Mac usan Button-2
        self.db_tree.bind("<Button-3>", on_right_click)  # Linux
        self.db_tree.bind("<Button-2>", on_right_click)  # Windows/Mac
        
        # Botones de acción
        actions_frame = ttk.Frame(results_frame)
        actions_frame.grid(row=1, column=0, columnspan=2, pady=5)
        
        ttk.Button(actions_frame, text="🗑️ Eliminar Seleccionada", 
                  command=self.delete_selected_song).pack(side=tk.LEFT, padx=5)
        ttk.Button(actions_frame, text="↩️ Designorar Seleccionada", 
                  command=self.unreject_selected_song).pack(side=tk.LEFT, padx=5)
        ttk.Button(actions_frame, text="🔄 Recargar", 
                  command=self.load_all_songs).pack(side=tk.LEFT, padx=5)
        
        # Cargar todas las canciones al inicio
        self.load_all_songs()
    
    def setup_monitor_tab(self):
        """Configura la pestaña de monitoreo de 'me gusta'."""
        monitor_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(monitor_tab, text="Playlist Youtube")
        monitor_tab.columnconfigure(0, weight=1)
        monitor_tab.rowconfigure(1, weight=1)
        monitor_tab.rowconfigure(2, weight=1)
        
        # Controles superiores
        control_frame = ttk.LabelFrame(monitor_tab, text="Controles", padding="10")
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        control_frame.columnconfigure(1, weight=1)
        
        # URL de playlist
        ttk.Label(control_frame, text="URL de Playlist:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        playlist_url_entry = ttk.Entry(control_frame, textvariable=self.liked_playlist_url_var, width=50)
        playlist_url_entry.grid(row=0, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        
        # Checkbox para cargar me gusta
        def on_load_liked_check():
            if self.load_liked_checkbox_var.get():
                # Poner la URL de me gusta por defecto
                self.liked_playlist_url_var.set("https://music.youtube.com/playlist?list=LM")
        
        self.load_liked_checkbox_var = tk.BooleanVar(value=False)
        load_liked_checkbox = ttk.Checkbutton(control_frame, text="Cargar me gusta", 
                                              variable=self.load_liked_checkbox_var,
                                              command=on_load_liked_check)
        load_liked_checkbox.grid(row=0, column=2, padx=10, pady=5, sticky=tk.W)
        
        # Checkbox para ocultar ignoradas y descargadas
        hide_checkbox = ttk.Checkbutton(control_frame, text="Ocultar ignoradas y descargadas", 
                                       variable=self.liked_hide_ignored_var)
        hide_checkbox.grid(row=0, column=3, padx=10, pady=5, sticky=tk.W)
        
        # Segunda fila: límite y botones
        ttk.Label(control_frame, text="Descargar las últimas número de canciones:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        limit_entry = ttk.Entry(control_frame, textvariable=self.liked_limit_var, width=10)
        limit_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        
        ttk.Button(control_frame, text="🔄 Cargar Playlist", command=self.load_liked_playlist).grid(row=1, column=2, padx=10, pady=5)
        
        # Área de lista de canciones con checkboxes
        list_frame = ttk.LabelFrame(monitor_tab, text="Canciones de 'Me Gusta'", padding="10")
        list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        # Canvas con scrollbar para la lista de checkboxes
        self.liked_canvas = tk.Canvas(list_frame)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.liked_canvas.yview)
        self.liked_scrollable_frame = ttk.Frame(self.liked_canvas)
        
        # Configurar scroll del ratón - funciones de manejo
        def _on_mousewheel(event):
            """Maneja el scroll del ratón para Windows/Mac."""
            self.liked_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"
        
        def _on_mousewheel_linux(event):
            """Maneja el scroll del ratón para Linux."""
            if event.num == 4:
                self.liked_canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.liked_canvas.yview_scroll(1, "units")
            return "break"
        
        # Función para propagar el evento de scroll a los hijos del frame scrollable
        def bind_scroll_to_children(parent):
            """Recursivamente bindea el scroll a todos los hijos."""
            for child in parent.winfo_children():
                child.bind("<MouseWheel>", _on_mousewheel)
                child.bind("<Button-4>", _on_mousewheel_linux)
                child.bind("<Button-5>", _on_mousewheel_linux)
                # Recursivo para widgets anidados
                if hasattr(child, 'winfo_children'):
                    bind_scroll_to_children(child)
        
        def update_scroll_region(event=None):
            self.liked_canvas.configure(scrollregion=self.liked_canvas.bbox("all"))
            # Re-bindear scroll a los nuevos hijos cuando se actualiza
            bind_scroll_to_children(self.liked_scrollable_frame)
        
        def configure_canvas_width(event=None):
            # Ajustar el ancho del frame interno al ancho del canvas
            canvas_width = event.width
            self.liked_canvas.itemconfig(self.liked_canvas_window, width=canvas_width)
        
        self.liked_scrollable_frame.bind("<Configure>", update_scroll_region)
        
        self.liked_canvas_window = self.liked_canvas.create_window((0, 0), window=self.liked_scrollable_frame, anchor="nw")
        self.liked_canvas.configure(yscrollcommand=scrollbar.set)
        self.liked_canvas.bind('<Configure>', configure_canvas_width)
        
        # Binding directo al canvas
        self.liked_canvas.bind("<MouseWheel>", _on_mousewheel)
        self.liked_canvas.bind("<Button-4>", _on_mousewheel_linux)
        self.liked_canvas.bind("<Button-5>", _on_mousewheel_linux)
        
        # Binding al frame scrollable (para cuando el mouse está sobre los widgets hijos)
        self.liked_scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        self.liked_scrollable_frame.bind("<Button-4>", _on_mousewheel_linux)
        self.liked_scrollable_frame.bind("<Button-5>", _on_mousewheel_linux)
        
        
        # Binding global como respaldo (solo cuando el mouse está sobre el área)
        def _on_mousewheel_global(event):
            """Scroll global con verificación de área."""
            widget = event.widget
            # Verificar si el widget está dentro del área de canciones
            try:
                # Obtener el widget que contiene el mouse
                x = self.root.winfo_pointerx()
                y = self.root.winfo_pointery()
                widget_at_mouse = self.root.winfo_containing(x, y)
                
                # Verificar si es parte del área de canciones
                if widget_at_mouse:
                    current = widget_at_mouse
                    while current:
                        if current == self.liked_canvas or current == self.liked_scrollable_frame or current == list_frame:
                            self.liked_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                            return "break"
                        current = current.master
            except:
                pass
        
        def _on_mousewheel_linux_global(event):
            """Scroll global Linux con verificación de área."""
            try:
                x = self.root.winfo_pointerx()
                y = self.root.winfo_pointery()
                widget_at_mouse = self.root.winfo_containing(x, y)
                
                if widget_at_mouse:
                    current = widget_at_mouse
                    while current:
                        if current == self.liked_canvas or current == self.liked_scrollable_frame or current == list_frame:
                            if event.num == 4:
                                self.liked_canvas.yview_scroll(-1, "units")
                            elif event.num == 5:
                                self.liked_canvas.yview_scroll(1, "units")
                            return "break"
                        current = current.master
            except:
                pass
        
        # Binding global para Windows/Mac
        self.root.bind_all("<MouseWheel>", _on_mousewheel_global)
        # Binding global para Linux
        self.root.bind_all("<Button-4>", _on_mousewheel_linux_global)
        self.root.bind_all("<Button-5>", _on_mousewheel_linux_global)
        
        self.liked_canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Configurar el canvas para que se expanda
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        # Área de log
        log_frame = ttk.LabelFrame(monitor_tab, text="Log", padding="10")
        log_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        monitor_tab.rowconfigure(2, weight=1)
        
        self.monitor_log_text = scrolledtext.ScrolledText(log_frame, height=8, width=80, 
                                                          font=('Consolas', 9), wrap=tk.WORD)
        self.monitor_log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
    
    def setup_import_tab(self):
        """Configura la pestaña de importar carpeta de canciones."""
        import_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(import_tab, text="📁 Importar Carpeta")
        import_tab.columnconfigure(0, weight=1)
        import_tab.rowconfigure(2, weight=1)
        
        # Sección de selección de carpeta
        folder_frame = ttk.LabelFrame(import_tab, text="Seleccionar Carpeta", padding="10")
        folder_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        folder_frame.columnconfigure(0, weight=1)
        
        self.import_folder_var = tk.StringVar()
        folder_entry = ttk.Entry(folder_frame, textvariable=self.import_folder_var, font=self.default_font)
        folder_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5)
        
        browse_btn = ttk.Button(folder_frame, text="📂 Buscar Carpeta", command=self.browse_import_folder)
        browse_btn.grid(row=0, column=1, padx=5)
        
        # Botones de acción
        buttons_frame = ttk.Frame(import_tab, padding="10")
        buttons_frame.grid(row=1, column=0, pady=10)
        
        import_btn = ttk.Button(buttons_frame, text="🔄 Importar Canciones", 
                               command=self.import_folder_songs, width=30)
        import_btn.grid(row=0, column=0, padx=5, pady=5)
        
        # Área de log
        log_frame = ttk.LabelFrame(import_tab, text="Log de Importación", padding="10")
        log_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.import_log_text = scrolledtext.ScrolledText(log_frame, height=15, width=80, 
                                                         font=('Consolas', 10), wrap=tk.WORD)
        self.import_log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        clear_btn = ttk.Button(log_frame, text="🗑️ Limpiar Log", command=self.clear_import_log)
        clear_btn.grid(row=1, column=0, pady=5)
    
    def setup_testing_tab(self):
        """Configura la pestaña de testing/pruebas."""
        testing_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(testing_tab, text="🧪 Testing")
        testing_tab.columnconfigure(0, weight=1)
        testing_tab.rowconfigure(2, weight=1)
        
        # Sección de URL
        url_frame = ttk.LabelFrame(testing_tab, text="URL de YouTube para Probar", padding="10")
        url_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        url_frame.columnconfigure(0, weight=1)
        
        test_url_entry = ttk.Entry(url_frame, textvariable=self.test_url_var, font=self.default_font)
        test_url_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5)
        # No añadir bindings de auto-descarga para este campo
        
        test_paste_btn = ttk.Button(url_frame, text="📋 Pegar URL", 
                                   command=self.paste_test_url)
        test_paste_btn.grid(row=0, column=1, padx=5)
        
        # Botones de prueba
        buttons_frame = ttk.Frame(testing_tab, padding="10")
        buttons_frame.grid(row=1, column=0, pady=10)
        
        # Botón para probar clasificación
        test_classification_btn = ttk.Button(buttons_frame, text="🔍 Probar Clasificación", 
                                            command=self.test_classification, width=30)
        test_classification_btn.grid(row=0, column=0, padx=5, pady=5)
        
        # Botón para obtener info del video (sin descargar)
        test_info_btn = ttk.Button(buttons_frame, text="🎵 Info del Video (Solo)", 
                                  command=self.test_video_info, width=30)
        test_info_btn.grid(row=0, column=1, padx=5, pady=5)
        
        # Área de log/resultados
        log_frame = ttk.LabelFrame(testing_tab, text="Resultados de Pruebas", padding="10")
        log_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.test_log_text = scrolledtext.ScrolledText(log_frame, height=20, width=80, 
                                                       font=('Consolas', 10), wrap=tk.WORD)
        self.test_log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        clear_btn = ttk.Button(log_frame, text="🗑️ Limpiar Log", command=self.clear_test_log)
        clear_btn.grid(row=1, column=0, pady=5)
    
    def setup_config_tab(self):
        """Configura la pestaña de configuración."""
        config_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(config_tab, text="⚙️ Configuración")
        config_tab.columnconfigure(0, weight=1)

        # Variables de configuración
        self.config_vars = {}
        
        # Frame de variables de entorno
        env_frame = ttk.LabelFrame(config_tab, text="Variables de Entorno (.env)", padding="10")
        env_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N), pady=5)
        env_frame.columnconfigure(1, weight=1)

        # Leer archivo .env actual
        env_path = '.env'
        env_data = {}
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            env_data[parts[0].strip()] = parts[1].strip()

        # Configurar campos específicos
        # 1. MUSIC_FOLDER
        ttk.Label(env_frame, text="Carpeta de Música:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.music_folder_var = tk.StringVar(value=env_data.get('MUSIC_FOLDER', ''))
        ttk.Entry(env_frame, textvariable=self.music_folder_var).grid(row=0, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        ttk.Button(env_frame, text="📂 Seleccionar", command=self.select_music_folder_config).grid(row=0, column=2, padx=5, pady=5)

        # 2. DB_PATH
        ttk.Label(env_frame, text="Ruta Base de Datos:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.db_path_var = tk.StringVar(value=env_data.get('DB_PATH', ''))
        ttk.Entry(env_frame, textvariable=self.db_path_var).grid(row=1, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        ttk.Button(env_frame, text="📂 Seleccionar", command=self.select_db_file_config).grid(row=1, column=2, padx=5, pady=5)
        
        # 3. LASTFM_API_KEY
        ttk.Label(env_frame, text="Last.fm API Key:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.lastfm_key_var = tk.StringVar(value=env_data.get('LASTFM_API_KEY', ''))
        ttk.Entry(env_frame, textvariable=self.lastfm_key_var).grid(row=2, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))

        # Botón de guardar
        save_btn = ttk.Button(config_tab, text="💾 Guardar Configuración", command=self.save_config)
        save_btn.grid(row=1, column=0, pady=10)
        
        # Botón de reset
        reset_frame = ttk.LabelFrame(config_tab, text="Zona de Peligro", padding="10")
        reset_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=10)
        reset_frame.columnconfigure(0, weight=1)
        
        ttk.Label(reset_frame, text="⚠️ Estas acciones son destructivas e irreversibles").pack(pady=5)
        
        reset_btn = ttk.Button(reset_frame, text="💣 RESETEAR BASE DE DATOS (BORRAR TODO)", 
                             command=self.reset_database)
        reset_btn.pack(pady=5)

    def select_music_folder_config(self):
        folder = filedialog.askdirectory(initialdir=self.music_folder_var.get())
        if folder:
            self.music_folder_var.set(folder)

    def select_db_file_config(self):
        current_dir = os.path.dirname(self.db_path_var.get()) if self.db_path_var.get() else os.path.expanduser("~")
        filename = filedialog.asksaveasfilename(
            title="Seleccionar archivo de Base de Datos",
            initialdir=current_dir,
            defaultextension=".db",
            filetypes=[("SQLite Database", "*.db"), ("All Files", "*.*")]
        )
        if filename:
            self.db_path_var.set(filename)

    def reset_database(self):
        if not messagebox.askyesno("Confirmar Reset", 
                                 "¿Estás SEGURO de que quieres borrar toda la base de datos?\n\nEsto eliminará permanentemente el historial de descargas y la caché.\nNo se puede deshacer."):
            return
            
        if not messagebox.askyesno("Confirmar Definitivamente", 
                                 "¿De verdad? Esta es tu última oportunidad."):
            return
            
        try:
            # Cerrar conexiones
            global db
            db.close()
            
            # Intentar cerrar conexión en módulo importado si existe
            if 'download_youtube' in sys.modules and hasattr(sys.modules['download_youtube'], 'db'):
                 sys.modules['download_youtube'].db.close()
            
            # Borrar archivo
            current_path = db.db_path
            if current_path.exists():
                os.remove(current_path)
            
            # Re-inicializar
            # Crear nueva instancia
            from database import MusicDatabase
            new_db = MusicDatabase(str(current_path))
            
            # Actualizar referencias globales
            db = new_db
            
            # Actualizar referencia en módulo
            if 'download_youtube' in sys.modules and hasattr(sys.modules['download_youtube'], 'db'):
                sys.modules['download_youtube'].db = new_db
                
            # Actualizar referencia local si existe (aunque ide.py usa global db)
            
            # Recargar UI
            self.load_all_songs()
            if hasattr(self, 'log_text'):
                self.log_text.insert(tk.END, f"\n✅ Base de datos reseteada correctamente en: {current_path}\n")
            
            messagebox.showinfo("Éxito", "Base de datos reseteada y recreada correctamente.")
            
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo resetear la base de datos:\n{str(e)}")
            # Intentar restaurar
            try:
                db = MusicDatabase(str(current_path))
            except:
                pass

    def save_config(self):
        env_path = '.env'
        
        new_values = {
            'MUSIC_FOLDER': self.music_folder_var.get(),
            'DB_PATH': self.db_path_var.get(),
            'LASTFM_API_KEY': self.lastfm_key_var.get()
        }
        
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.readlines()
        
        updated_keys = set()
        new_lines = []
        
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and '=' in stripped:
                key = stripped.split('=', 1)[0].strip()
                if key in new_values:
                    new_lines.append(f"{key}={new_values[key]}\n")
                    updated_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        for key, value in new_values.items():
            if key not in updated_keys and value:
                if new_lines and not new_lines[-1].endswith('\n'):
                     new_lines.append('\n')
                new_lines.append(f"{key}={value}\n")
        
        try:
            with open(env_path, 'w') as f:
                f.writelines(new_lines)
            messagebox.showinfo("Configuración", "Configuración guardada correctamente.\nReinicia la aplicación para aplicar todos los cambios.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar la configuración:\n{e}")

    def setup_about_tab(self):
        """Configura la pestaña About con información del software."""
        about_tab = ttk.Frame(self.notebook, padding="20")
        self.notebook.add(about_tab, text="ℹ️ About")
        about_tab.columnconfigure(0, weight=1)
        
        # Frame central para centrar el contenido
        center_frame = ttk.Frame(about_tab)
        center_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        about_tab.rowconfigure(0, weight=1)
        about_tab.columnconfigure(0, weight=1)
        center_frame.columnconfigure(0, weight=1)
        
        # Título del software
        title_font = self._get_best_font_for_emojis()
        title_label = ttk.Label(center_frame, text=SOFTWARE_NAME, 
                               font=(title_font, 24, 'bold'))
        title_label.grid(row=0, column=0, pady=(20, 10))
        
        # Descripción
        desc_text = "Descargador de música de YouTube para DJ\ncon gestión de metadatos y base de datos"
        desc_label = ttk.Label(center_frame, text=desc_text, 
                              font=self.default_font, justify=tk.CENTER)
        desc_label.grid(row=1, column=0, pady=10)
        
        # Separador
        separator = ttk.Separator(center_frame, orient='horizontal')
        separator.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=20)
        
        # Información de GitHub
        github_frame = ttk.Frame(center_frame)
        github_frame.grid(row=3, column=0, pady=10)
        
        github_label = ttk.Label(github_frame, text="GitHub:", font=self.default_font)
        github_label.grid(row=0, column=0, padx=5)
        
        # URL de GitHub como botón clickeable
        github_link = ttk.Label(github_frame, text=GITHUB_URL, 
                               font=('Arial', 10, 'underline'),
                               foreground='blue', cursor='hand2')
        github_link.grid(row=0, column=1, padx=5)
        github_link.bind('<Button-1>', lambda e: webbrowser.open(GITHUB_URL))
        github_link.bind('<Enter>', lambda e: github_link.config(foreground='darkblue'))
        github_link.bind('<Leave>', lambda e: github_link.config(foreground='blue'))
        
        # Versión (opcional, puedes añadir una variable VERSION si quieres)
        version_label = ttk.Label(center_frame, text="Versión: 1.0.0", 
                                 font=('Arial', 9), foreground='gray')
        version_label.grid(row=4, column=0, pady=(20, 0))
        
        # Copyright
        copyright_label = ttk.Label(center_frame, text="© 2024", 
                                   font=('Arial', 9), foreground='gray')
        copyright_label.grid(row=5, column=0, pady=5)
    
    def setup_output_capture(self):
        """Configura la captura de salida para mostrar prints en el log."""
        class TextRedirector:
            def __init__(self, text_widget):
                self.text_widget = text_widget
            
            def write(self, string):
                self.text_widget.insert(tk.END, string)
                self.text_widget.see(tk.END)
            
            def flush(self):
                pass
        
        sys.stdout = TextRedirector(self.log_text)
    
    def log(self, message):
        """Añade un mensaje al log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update()
    
    def clear_log(self):
        """Limpia el área de log."""
        self.log_text.delete(1.0, tk.END)
    
    def paste_url(self, event=None):
        """Pega la URL desde el portapapeles y inicia descarga automática."""
        try:
            url = self.root.clipboard_get()
            self.url_var.set(url)
            self.log(f"✓ URL pegada: {url[:50]}...")
            # Iniciar descarga automática después de un breve delay
            self.root.after(200, self.auto_download)
            return "break"  # Evitar el comportamiento por defecto
        except:
            self.log("⚠️ No hay URL en el portapapeles")
            return "break"
    
    def paste_test_url(self):
        """Pega la URL desde el portapapeles en el campo de prueba (sin auto-descarga)."""
        try:
            url = self.root.clipboard_get()
            self.test_url_var.set(url)
            self.log(f"✓ URL pegada en campo de prueba: {url[:50]}...")
        except:
            self.log("⚠️ No hay URL en el portapapeles")
    
    def check_url_and_download(self):
        """Verifica si hay una URL válida en el campo y la descarga automáticamente."""
        url = self.url_var.get().strip()
        # Solo descargar si parece una URL de YouTube y no está vacía
        if url and ('youtube.com' in url or 'youtu.be' in url):
            # Evitar múltiples descargas de la misma URL
            if url != self._last_url and not self._downloading:
                self.auto_download()
    
    def auto_download(self):
        """Inicia descarga automática de la URL en el campo."""
        url = self.url_var.get().strip()
        if not url:
            return
        
        # Verificar que no estemos ya descargando
        if self._downloading:
            return
        
        # Verificar que sea una URL válida de YouTube
        if not ('youtube.com' in url or 'youtu.be' in url):
            return
        
        # Marcar que estamos descargando y guardar la URL
        self._downloading = True
        self._last_url = url
        
        # Limpiar el campo después de un momento
        self.root.after(1000, lambda: self.url_var.set(""))
        
        # Iniciar descarga automática con el mismo método que playlist
        self.log(f"{'='*60}")
        self.log("⚡ DESCARGA AUTOMÁTICA INICIADA")
        self.log(f"{'='*60}\n")
        
        def download_thread():
            try:
                self.log(f"🔗 URL: {url}")
                
                # Extraer video_id
                video_id = None
                match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
                if match:
                    video_id = match.group(1)
                
                # 1. Obtener información del video
                self.log(f"🔍 Obteniendo información del video...")
                video_info = get_video_info(url)
                
                if not video_info:
                    self.log("❌ No se pudo obtener información del video")
                    self.root.after(1000, lambda: setattr(self, '_downloading', False))
                    return
                
                title = video_info.get('title', 'Unknown')
                self.log(f"✓ Título: {title}")
                
                # 2. Extraer metadatos
                self.log(f"🔍 Extrayendo metadatos...")
                description = video_info.get('description', '')
                metadata = extract_metadata_from_title(title, description, video_info)
                self.log(f"✓ Metadatos extraídos")
                
                self.log(f"🎤 Artista: {metadata.get('artist', 'No detectado')}")
                self.log(f"📅 Año: {metadata.get('year', 'No detectado')}")
                
                # 3. Detectar género si no está
                if not metadata.get('genre') and metadata.get('artist'):
                    self.log(f"🔍 Detectando género...")
                    detected_genre = detect_genre_online(
                        metadata.get('artist'), 
                        metadata.get('title', title),
                        video_info=video_info,
                        title=title,
                        description=description
                    )
                    if detected_genre:
                        metadata['genre'] = detected_genre
                        self.log(f"✓ Género detectado: {detected_genre}")
                    else:
                        metadata['genre'] = 'Sin Clasificar'
                        self.log(f"⚠️  Género no detectado, usando 'Sin Clasificar'")
                else:
                    self.log(f"🎵 Género: {metadata.get('genre', 'Sin Clasificar')}")
                
                # 4. Usar año actual si no hay
                if not metadata.get('year'):
                    metadata['year'] = str(datetime.now().year)
                    self.log(f"📅 Usando año actual: {metadata['year']}")
                
                # 5. Obtener carpeta de salida
                output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))
                self.log(f"📁 Carpeta de destino: {output_folder}")
                
                # 6. Crear nombre de archivo
                if metadata.get('artist'):
                    filename = f"{metadata['artist']} - {metadata['title']}"
                else:
                    filename = metadata['title']
                
                filename = sanitize_filename(filename)
                output_path = output_folder / filename
                self.log(f"📄 Nombre de archivo: {filename}")
                
                # 7. Descargar
                self.log(f"📥 Iniciando descarga de audio...")
                if download_audio(url, str(output_path), metadata):
                    mp3_file = Path(str(output_path) + '.mp3')
                    if not mp3_file.exists():
                        mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
                        if mp3_files:
                            mp3_file = mp3_files[0]
                        else:
                            self.log("❌ Archivo no encontrado")
                            self.root.after(1000, lambda: setattr(self, '_downloading', False))
                            return
                    
                    self.log(f"✓ Archivo descargado: {mp3_file.name}")
                    
                    # 8. Verificar y normalizar volumen
                    self.log(f"🔊 Verificando volumen...")
                    check_and_normalize_audio(str(mp3_file))
                    
                    # 9. Si no se detectó género, intentar con Essentia (análisis de audio)
                    if not metadata.get('genre') or metadata.get('genre', '').lower() in ['sin clasificar', 'unknown', '']:
                        self.log(f"🔍 Intentando detectar género con análisis de audio...")
                        detected_genre = detect_genre_from_audio_file(str(mp3_file))
                        if detected_genre:
                            metadata['genre'] = detected_genre
                            self.log(f"✓ Género detectado por audio: {detected_genre}")
                    
                    # 10. Añadir metadatos ID3
                    self.log(f"🏷️  Añadiendo metadatos ID3...")
                    add_id3_tags(str(mp3_file), metadata, video_info)
                    
                    # 11. Registrar en base de datos
                    self.log(f"💾 Registrando en base de datos...")
                    if video_id:
                        register_song_in_db(video_id, url, mp3_file, metadata, video_info, download_source='puntual')
                        self.log(f"✓ Registrado en base de datos")
                    else:
                        self.log(f"⚠️  No se pudo obtener video_id, la canción no se registró en la BD")
                    
                    self.log(f"\n✅ COMPLETADA: {mp3_file.name}")
                    self.log(f"📁 Ruta completa: {mp3_file}")
                else:
                    self.log("❌ Error en la descarga")
                
                # Resetear flag después de completar
                self.root.after(1000, lambda: setattr(self, '_downloading', False))
                
            except Exception as e:
                self.log(f"❌ Error: {str(e)}")
                import traceback
                self.log(f"⚠️  Error durante la descarga: {str(e)}")
                self.log(f"📋 Detalles: {traceback.format_exc()}")
                # Resetear flag en caso de error
                self.root.after(1000, lambda: setattr(self, '_downloading', False))
        
        threading.Thread(target=download_thread, daemon=True).start()
    
    def get_url(self):
        """Obtiene la URL del campo de texto."""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL vacía", "Por favor, ingresa una URL de YouTube")
            return None
        return url
    
    def download_with_metadata(self):
        """Descarga una canción con metadatos completos."""
        url = self.get_url()
        if not url:
            return
        
        def download_thread():
            try:
                self.log(f"\n{'='*60}")
                self.log("📥 INICIANDO DESCARGA CON METADATOS")
                self.log(f"{'='*60}\n")
                
                # Obtener información del video
                self.log("🔍 Obteniendo información del video...")
                video_info = get_video_info(url)
                
                if not video_info:
                    self.log("❌ Error: No se pudo obtener información del video.")
                    messagebox.showerror("Error", "No se pudo obtener información del video.")
                    return
                
                title = video_info.get('title', 'Unknown')
                description = video_info.get('description', '')
                
                self.log(f"✓ Título: {title}")
                
                # Extraer metadatos básicos
                metadata = extract_metadata_from_title(title, description, video_info)
                
                self.log(f"📝 Artista: {metadata.get('artist', 'No detectado')}")
                self.log(f"📝 Año: {metadata.get('year', 'No detectado')}")
                self.log(f"📝 Género: {metadata.get('genre', 'No detectado')}")
                
                # Si no hay género, intentar detectarlo online
                if not metadata.get('genre') and metadata.get('artist'):
                    self.log("\n🔍 Intentando detectar género automáticamente...")
                    detected_genre = detect_genre_online(
                        metadata.get('artist'), 
                        metadata.get('title', title),
                        video_info=video_info,
                        title=title,
                        description=description
                    )
                    if detected_genre:
                        metadata['genre'] = detected_genre
                        self.log(f"✓ Género detectado: {detected_genre}")
                    else:
                        # Preguntar al usuario en un diálogo
                        self.root.after(0, lambda: self.ask_genre(metadata))
                        return
                
                # Si no hay año, usar año actual
                if not metadata.get('year'):
                    metadata['year'] = str(datetime.now().year)
                
                # Continuar con la descarga
                self.continue_download(url, video_info, metadata)
                
            except Exception as e:
                self.log(f"❌ Error: {str(e)}")
                messagebox.showerror("Error", f"Error durante la descarga: {str(e)}")
        
        threading.Thread(target=download_thread, daemon=True).start()
    
    def ask_genre(self, metadata):
        """Pregunta al usuario por el género."""
        genre = simpledialog.askstring("Género", 
                                       "¿Qué género es esta canción?\n(Deja vacío para 'Sin Clasificar'):")
        if genre is None:  # Usuario canceló
            return
        metadata['genre'] = genre if genre else 'Sin Clasificar'
        # Continuar con la descarga
        url = self.url_var.get().strip()
        video_info = get_video_info(url)
        if video_info:
            threading.Thread(target=lambda: self.continue_download(url, video_info, metadata), daemon=True).start()
    
    def continue_download(self, url, video_info, metadata):
        """Continúa con el proceso de descarga."""
        try:
            title = video_info.get('title', 'Unknown')
            
            # Extraer video_id
            video_id = video_info.get('id', '')
            if not video_id:
                import re
                match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
                if match:
                    video_id = match.group(1)
            
            # Verificar si el archivo ya existe
            existing_song = check_file_exists(
                video_id=video_id,
                artist=metadata.get('artist'),
                title=metadata.get('title', title)
            )
            if existing_song:
                self.log(f"\n⚠️ El archivo ya existe: {existing_song['file_path']}")
                response = messagebox.askyesno("Archivo existente", 
                                               f"El archivo ya existe:\n{existing_song['file_path']}\n\n¿Deseas descargarlo de todas formas?")
                if not response:
                    self.log("❌ Descarga cancelada.")
                    return
            
            # Obtener carpeta de salida
            output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))
            
            # Crear nombre de archivo
            if metadata.get('artist'):
                filename = f"{metadata['artist']} - {metadata['title']}"
            else:
                filename = metadata['title']
            
            filename = sanitize_filename(filename)
            output_path = output_folder / filename
            
            self.log(f"\n📁 Carpeta de destino: {output_folder}")
            self.log(f"📥 Descargando a: {output_path}")
            
            # Descargar
            self.log("\n📥 Descargando audio...")
            if download_audio(url, str(output_path), metadata):
                # El archivo se descarga como .mp3
                mp3_file = Path(str(output_path) + '.mp3')
                if not mp3_file.exists():
                    # Buscar el archivo descargado
                    mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
                    if mp3_files:
                        mp3_file = mp3_files[0]
                    else:
                        self.log("❌ Error: No se encontró el archivo descargado.")
                        return
                
                # Verificar y normalizar volumen si es necesario
                check_and_normalize_audio(str(mp3_file))
                
                self.log("🏷️ Añadiendo metadatos...")
                add_id3_tags(str(mp3_file), metadata, video_info)
                
                # Registrar en base de datos
                self.log("💾 Registrando en base de datos...")
                if video_id:
                    register_song_in_db(video_id, url, mp3_file, metadata, video_info, download_source='puntual')
                
                self.log(f"\n✅ Descarga completada: {mp3_file}")
                self.log(f"📁 Ruta completa: {mp3_file}")
                # No mostrar pop-up, solo escribir en logs
            else:
                self.log("❌ Error en la descarga.")
                messagebox.showerror("Error", "Error durante la descarga del audio.")
                
        except Exception as e:
            self.log(f"❌ Error: {str(e)}")
            messagebox.showerror("Error", f"Error durante la descarga: {str(e)}")
    
    def show_video_info(self):
        """Muestra información de un video de YouTube."""
        url = self.get_url()
        if not url:
            return
        
        def info_thread():
            try:
                self.log(f"\n{'='*60}")
                self.log("🎵 INFORMACIÓN DEL VIDEO")
                self.log(f"{'='*60}\n")
                self.log("🔍 Obteniendo información...")
                
                video_info = get_video_info(url)
                
                if not video_info:
                    self.log("❌ Error: No se pudo obtener información del video.")
                    messagebox.showerror("Error", "No se pudo obtener información del video.")
                    return
                
                self.log(f"\nTítulo: {video_info.get('title', 'N/A')}")
                self.log(f"ID: {video_info.get('id', 'N/A')}")
                self.log(f"Canal: {video_info.get('uploader', 'N/A')}")
                self.log(f"Duración: {video_info.get('duration', 'N/A')} segundos")
                self.log(f"Vistas: {video_info.get('view_count', 'N/A')}")
                self.log(f"Fecha de subida: {video_info.get('upload_date', 'N/A')}")
                
                description = video_info.get('description', '')
                if description:
                    desc_preview = description[:200] + "..." if len(description) > 200 else description
                    self.log(f"\nDescripción:\n{desc_preview}")
                
                # Extraer metadatos
                title = video_info.get('title', '')
                description = video_info.get('description', '')
                metadata = extract_metadata_from_title(title, description, video_info)
                
                self.log(f"\n{'-'*60}")
                self.log("📝 METADATOS EXTRAÍDOS")
                self.log(f"{'-'*60}")
                self.log(f"Artista: {metadata.get('artist', 'No detectado')}")
                self.log(f"Año: {metadata.get('year', 'No detectado')}")
                self.log(f"Género: {metadata.get('genre', 'No detectado')}")
                self.log(f"Título limpio: {metadata.get('title', title)}")
                
            except Exception as e:
                self.log(f"❌ Error: {str(e)}")
                messagebox.showerror("Error", f"Error al obtener información: {str(e)}")
        
        threading.Thread(target=info_thread, daemon=True).start()
    
    def clear_test_log(self):
        """Limpia el área de log de pruebas."""
        self.test_log_text.delete(1.0, tk.END)
    
    def test_log(self, message):
        """Añade un mensaje al log de pruebas."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.test_log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.test_log_text.see(tk.END)
        self.root.update()
    
    def test_video_info(self):
        """Muestra información del video sin descargar (solo para testing)."""
        url = self.test_url_var.get().strip()
        if not url:
            messagebox.showwarning("URL vacía", "Por favor, ingresa una URL de YouTube")
            return
        
        def info_thread():
            try:
                self.test_log(f"\n{'='*60}")
                self.test_log("🎵 INFORMACIÓN DEL VIDEO (Solo Lectura)")
                self.test_log(f"{'='*60}\n")
                self.test_log("🔍 Obteniendo información...")
                
                video_info = get_video_info(url)
                
                if not video_info:
                    self.test_log("❌ Error: No se pudo obtener información del video.")
                    messagebox.showerror("Error", "No se pudo obtener información del video.")
                    return
                
                self.test_log(f"\nTítulo: {video_info.get('title', 'N/A')}")
                self.test_log(f"ID: {video_info.get('id', 'N/A')}")
                self.test_log(f"Canal: {video_info.get('uploader', 'N/A')}")
                self.test_log(f"Duración: {video_info.get('duration', 'N/A')} segundos")
                self.test_log(f"Vistas: {video_info.get('view_count', 'N/A')}")
                self.test_log(f"Fecha de subida: {video_info.get('upload_date', 'N/A')}")
                
                description = video_info.get('description', '')
                if description:
                    desc_preview = description[:200] + "..." if len(description) > 200 else description
                    self.test_log(f"\nDescripción:\n{desc_preview}")
                
                # Extraer metadatos
                title = video_info.get('title', '')
                description = video_info.get('description', '')
                metadata = extract_metadata_from_title(title, description, video_info)
                
                self.test_log(f"\n{'-'*60}")
                self.test_log("📝 METADATOS EXTRAÍDOS")
                self.test_log(f"{'-'*60}")
                self.test_log(f"Artista: {metadata.get('artist', 'No detectado')}")
                self.test_log(f"Año: {metadata.get('year', 'No detectado')}")
                self.test_log(f"Género: {metadata.get('genre', 'No detectado')}")
                self.test_log(f"Título limpio: {metadata.get('title', title)}")
                
            except Exception as e:
                self.test_log(f"❌ Error: {str(e)}")
                messagebox.showerror("Error", f"Error al obtener información: {str(e)}")
        
        threading.Thread(target=info_thread, daemon=True).start()
    
    def test_classification(self):
        """Prueba cómo se clasifica una canción mostrando todos los métodos de detección."""
        # Usar el campo de prueba
        url = self.test_url_var.get().strip()
        if not url:
            messagebox.showwarning("URL vacía", "Por favor, ingresa una URL de YouTube en el campo de prueba")
            return
        
        def test_thread():
            try:
                self.test_log(f"\n{'='*60}")
                self.test_log("🔍 PRUEBA DE CLASIFICACIÓN DE CANCIÓN")
                self.test_log(f"{'='*60}\n")
                self.test_log("⚠️ NOTA: Este video NO se descargará, solo se analizará.\n")
                self.test_log("🔍 Obteniendo información del video...")
                
                video_info = get_video_info(url)
                
                if not video_info:
                    self.test_log("❌ Error: No se pudo obtener información del video.")
                    messagebox.showerror("Error", "No se pudo obtener información del video.")
                    return
                
                title = video_info.get('title', 'Unknown')
                description = video_info.get('description', '')
                
                self.test_log(f"\n📹 VIDEO:")
                self.test_log(f"   Título: {title}")
                self.test_log(f"   ID: {video_info.get('id', 'N/A')}")
                self.test_log(f"   Canal: {video_info.get('uploader', 'N/A')}")
                self.test_log(f"   Canal completo: {video_info.get('channel', 'N/A')}")
                
                # Extraer metadatos básicos
                metadata = extract_metadata_from_title(title, description, video_info)
                artist = metadata.get('artist')
                track_title = metadata.get('title', title)
                year = metadata.get('year')
                
                self.test_log(f"\n📝 METADATOS EXTRAÍDOS:")
                self.test_log(f"   Artista: {artist or 'No detectado'}")
                self.test_log(f"   Título: {track_title}")
                self.test_log(f"   Año: {year or 'No detectado'}")
                
                self.test_log(f"\n{'='*60}")
                self.test_log("🎯 PROBANDO MÉTODOS DE DETECCIÓN DE GÉNERO")
                self.test_log(f"{'='*60}\n")
                
                results = {}
                
                # 1. Base de datos local
                self.test_log("1️⃣  Probando: Base de datos local (género histórico del artista)...")
                if artist:
                    genre_db = get_genre_from_database(artist)
                    results['Base de datos local'] = genre_db
                    if genre_db:
                        self.test_log(f"   ✅ Género encontrado: {genre_db}")
                    else:
                        self.test_log(f"   ❌ No se encontró género en la base de datos")
                else:
                    self.test_log(f"   ⚠️  No hay artista, se omite este método")
                    results['Base de datos local'] = None
                
                # 2. Tags del video
                self.test_log("\n2️⃣  Probando: Tags del video de YouTube...")
                genre_tags = get_genre_from_video_tags(video_info)
                results['Tags del video'] = genre_tags
                if genre_tags:
                    self.test_log(f"   ✅ Género encontrado: {genre_tags}")
                    tags_list = video_info.get('tags', [])
                    if tags_list:
                        self.test_log(f"   📋 Tags disponibles: {', '.join(tags_list[:10])}")
                else:
                    self.test_log(f"   ❌ No se encontró género en los tags")
                    tags_list = video_info.get('tags', [])
                    if tags_list:
                        self.test_log(f"   📋 Tags disponibles: {', '.join(tags_list[:10])}")
                    else:
                        self.test_log(f"   ⚠️  El video no tiene tags")
                
                # 3. Nombre del canal
                self.test_log("\n3️⃣  Probando: Nombre del canal/uploader...")
                genre_channel = get_genre_from_channel_name(video_info)
                results['Nombre del canal'] = genre_channel
                if genre_channel:
                    self.test_log(f"   ✅ Género encontrado: {genre_channel}")
                else:
                    self.test_log(f"   ❌ No se encontró género en el nombre del canal")
                
                # 4. Palabras clave del título
                self.test_log("\n4️⃣  Probando: Palabras clave del título...")
                genre_title = get_genre_from_title_keywords(title)
                results['Palabras clave del título'] = genre_title
                if genre_title:
                    self.test_log(f"   ✅ Género encontrado: {genre_title}")
                else:
                    self.test_log(f"   ❌ No se encontró género en el título")
                
                # 5. Análisis profundo de la descripción
                self.test_log("\n5️⃣  Probando: Análisis profundo de la descripción...")
                genre_desc = get_genre_from_description_deep(description)
                results['Análisis de descripción'] = genre_desc
                if genre_desc:
                    self.test_log(f"   ✅ Género encontrado: {genre_desc}")
                    if description:
                        desc_preview = description[:150] + "..." if len(description) > 150 else description
                        self.test_log(f"   📄 Vista previa de descripción: {desc_preview}")
                else:
                    self.test_log(f"   ❌ No se encontró género en la descripción")
                    if not description:
                        self.test_log(f"   ⚠️  El video no tiene descripción")
                
                # 6. Last.fm
                self.test_log("\n6️⃣  Probando: Last.fm API...")
                if artist:
                    genre_lastfm = get_genre_from_lastfm(artist, track_title)
                    results['Last.fm'] = genre_lastfm
                    if genre_lastfm:
                        self.test_log(f"   ✅ Género encontrado: {genre_lastfm}")
                    else:
                        self.test_log(f"   ❌ No se encontró género en Last.fm")
                else:
                    self.test_log(f"   ⚠️  No hay artista, se omite este método")
                    results['Last.fm'] = None
                
                # 7. MusicBrainz
                self.test_log("\n7️⃣  Probando: MusicBrainz API...")
                if artist:
                    genre_mb = get_genre_from_musicbrainz(artist, track_title)
                    results['MusicBrainz'] = genre_mb
                    if genre_mb:
                        self.test_log(f"   ✅ Género encontrado: {genre_mb}")
                    else:
                        self.test_log(f"   ❌ No se encontró género en MusicBrainz")
                else:
                    self.test_log(f"   ⚠️  No hay artista, se omite este método")
                    results['MusicBrainz'] = None
                
                # 8. Búsqueda web
                self.test_log("\n8️⃣  Probando: Búsqueda web (DuckDuckGo)...")
                if artist:
                    genre_web = get_genre_from_web_search(artist, track_title)
                    results['Búsqueda web'] = genre_web
                    if genre_web:
                        self.test_log(f"   ✅ Género encontrado: {genre_web}")
                    else:
                        self.test_log(f"   ❌ No se encontró género en búsqueda web")
                else:
                    self.test_log(f"   ⚠️  No hay artista, se omite este método")
                    results['Búsqueda web'] = None
                
                # Resumen final
                self.test_log(f"\n{'='*60}")
                self.test_log("📊 RESUMEN DE RESULTADOS")
                self.test_log(f"{'='*60}\n")
                
                found_genres = []
                for method, genre in results.items():
                    if genre:
                        found_genres.append((method, genre))
                        self.test_log(f"   ✅ {method}: {genre}")
                    else:
                        self.test_log(f"   ❌ {method}: No encontrado")
                
                # Resultado final usando detect_genre_online (que usa todos los métodos en orden)
                self.test_log(f"\n{'='*60}")
                self.test_log("🎯 RESULTADO FINAL (usando detect_genre_online)")
                self.test_log(f"{'='*60}\n")
                
                final_genre = detect_genre_online(
                    artist,
                    track_title,
                    video_info=video_info,
                    title=title,
                    description=description
                )
                
                if final_genre:
                    self.test_log(f"   ✅ Género detectado: {final_genre}")
                    self.test_log(f"\n   📍 Este es el género que se usaría para clasificar la canción")
                else:
                    self.test_log(f"   ❌ No se pudo detectar el género automáticamente")
                    self.test_log(f"\n   ⚠️  La canción se clasificaría como 'Sin Clasificar'")
                
                # Mostrar información adicional
                if description:
                    self.test_log(f"\n📄 DESCRIPCIÓN COMPLETA (primeros 500 caracteres):")
                    self.test_log(f"{'-'*60}")
                    desc_preview = description[:500] + "..." if len(description) > 500 else description
                    self.test_log(desc_preview)
                
            except Exception as e:
                self.test_log(f"❌ Error: {str(e)}")
                import traceback
                self.test_log(f"   Detalles: {traceback.format_exc()}")
                messagebox.showerror("Error", f"Error al probar clasificación: {str(e)}")
        
        threading.Thread(target=test_thread, daemon=True).start()
    
    def monitor_liked(self):
        """Monitorea la lista de 'me gusta' de YouTube."""
        response = messagebox.askyesno("Monitorear 'Me Gusta'", 
                                      "Esto monitoreará tu lista de 'me gusta' de YouTube.\n\n"
                                      "⚠️ NOTA: Esta función requiere interacción del usuario.\n"
                                      "Las preguntas aparecerán en el log y en ventanas emergentes.\n\n"
                                      "¿Continuar?")
        if not response:
            return
        
        def monitor_thread():
            try:
                self.log(f"\n{'='*60}")
                self.log("👀 MONITOREANDO LISTA DE 'ME GUSTA'")
                self.log(f"{'='*60}\n")
                self.log("⚠️ Esta función requiere interacción. Las preguntas aparecerán en ventanas emergentes.\n")
                
                # Ejecutar monitoreo (las preguntas se harán con messagebox)
                # Nota: monitor_liked_videos() usa input(), así que necesitamos adaptarlo
                # Por ahora, ejecutamos la función original y capturamos la salida
                monitor_liked_videos()
                self.log("\n✅ Monitoreo completado.")
            except Exception as e:
                self.log(f"❌ Error: {str(e)}")
                messagebox.showerror("Error", f"Error durante el monitoreo: {str(e)}")
        
        threading.Thread(target=monitor_thread, daemon=True).start()
    
    def search_database(self):
        """Abre un diálogo para buscar en la base de datos."""
        # Crear ventana de búsqueda
        search_window = tk.Toplevel(self.root)
        search_window.title("🔍 Buscar en Base de Datos")
        search_window.geometry("500x300")
        
        frame = ttk.Frame(search_window, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="Filtros de búsqueda (deja vacío para omitir):").pack(pady=5)
        
        artist_var = tk.StringVar()
        title_var = tk.StringVar()
        genre_var = tk.StringVar()
        decade_var = tk.StringVar()
        limit_var = tk.StringVar(value="10")
        
        ttk.Label(frame, text="Artista:").pack(anchor=tk.W, pady=2)
        ttk.Entry(frame, textvariable=artist_var, width=40).pack(pady=2)
        
        ttk.Label(frame, text="Título:").pack(anchor=tk.W, pady=2)
        ttk.Entry(frame, textvariable=title_var, width=40).pack(pady=2)
        
        ttk.Label(frame, text="Género:").pack(anchor=tk.W, pady=2)
        ttk.Entry(frame, textvariable=genre_var, width=40).pack(pady=2)
        
        ttk.Label(frame, text="Década (ej: 2020s):").pack(anchor=tk.W, pady=2)
        ttk.Entry(frame, textvariable=decade_var, width=40).pack(pady=2)
        
        ttk.Label(frame, text="Límite:").pack(anchor=tk.W, pady=2)
        ttk.Entry(frame, textvariable=limit_var, width=40).pack(pady=2)
        
        def do_search():
            try:
                limit = int(limit_var.get()) if limit_var.get() else 10
            except:
                limit = 10
            
            search_window.destroy()
            
            def search_thread():
                try:
                    self.log(f"\n{'='*60}")
                    self.log("🔍 BUSCANDO EN BASE DE DATOS")
                    self.log(f"{'='*60}\n")
                    
                    # Capturar la salida de search_songs
                    search_songs(
                        artist=artist_var.get().strip() or None,
                        title=title_var.get().strip() or None,
                        genre=genre_var.get().strip() or None,
                        decade=decade_var.get().strip() or None,
                        limit=limit
                    )
                except Exception as e:
                    self.log(f"❌ Error: {str(e)}")
                    messagebox.showerror("Error", f"Error durante la búsqueda: {str(e)}")
            
            threading.Thread(target=search_thread, daemon=True).start()
        
        ttk.Button(frame, text="Buscar", command=do_search).pack(pady=10)
    
    def show_statistics(self):
        """Muestra estadísticas de la base de datos."""
        def stats_thread():
            try:
                self.log(f"\n{'='*60}")
                self.log("📊 ESTADÍSTICAS DE LA BASE DE DATOS")
                self.log(f"{'='*60}\n")
                show_statistics()
            except Exception as e:
                self.log(f"❌ Error: {str(e)}")
                messagebox.showerror("Error", f"Error al obtener estadísticas: {str(e)}")
        
        threading.Thread(target=stats_thread, daemon=True).start()
    
    # Funciones para pestaña de Base de Datos
    def load_all_songs(self):
        """Carga todas las canciones en el treeview, o solo las ignoradas si el checkbox está marcado."""
        # Limpiar treeview y datos almacenados
        for item in self.db_tree.get_children():
            self.db_tree.delete(item)
        self.db_all_data = []
        
        try:
            # Si el checkbox de "mostrar solo ignoradas" está marcado, mostrar solo las ignoradas
            if self.db_show_ignored_only_var.get():
                rejected_videos = db.get_all_rejected_videos(limit=1000)
                for rejected in rejected_videos:
                    # Formatear fecha de rechazo
                    rejected_at = rejected.get('rejected_at', '')
                    if rejected_at:
                        try:
                            if isinstance(rejected_at, str):
                                date_obj = datetime.strptime(rejected_at, '%Y-%m-%d %H:%M:%S')
                                formatted_date = date_obj.strftime('%d/%m/%Y %H:%M')
                            else:
                                formatted_date = str(rejected_at)
                        except:
                            formatted_date = str(rejected_at)
                    else:
                        formatted_date = 'N/A'
                    
                    # Obtener título y URL
                    title = rejected.get('title', 'N/A')
                    url = rejected.get('url', 'N/A')
                    reason = rejected.get('reason', 'Sin razón')
                    
                    # Preparar valores para el treeview
                    values = (
                        title,
                        'N/A',  # Artista (no disponible en rejected_videos)
                        'N/A',  # Género
                        'N/A',  # Año
                        'N/A',  # Tamaño
                        'N/A',  # Tipo
                        'N/A',  # Calidad (kbps)
                        formatted_date,  # Fecha de rechazo
                        'Ignorada',  # Origen
                        url,
                        'N/A'  # Archivo (no descargado)
                    )
                    tags = (rejected.get('video_id', ''),)
                    
                    # Almacenar datos para filtrado
                    self.db_all_data.append({
                        'values': values,
                        'tags': tags
                    })
                
                # Aplicar filtro si hay texto de búsqueda
                self.filter_database_table()
                return
            
            # Si no está marcado, mostrar canciones descargadas normalmente
            songs = db.get_all_songs(limit=1000)  # Obtener hasta 1000 canciones
            for song in songs:
                # Formatear fecha de descarga
                downloaded_at = song.get('downloaded_at', '')
                if downloaded_at:
                    try:
                        # Intentar parsear la fecha y formatearla
                        if isinstance(downloaded_at, str):
                            # SQLite devuelve timestamps en formato 'YYYY-MM-DD HH:MM:SS'
                            date_obj = datetime.strptime(downloaded_at, '%Y-%m-%d %H:%M:%S')
                            formatted_date = date_obj.strftime('%d/%m/%Y %H:%M')
                        else:
                            formatted_date = str(downloaded_at)
                    except:
                        formatted_date = str(downloaded_at)
                else:
                    formatted_date = 'N/A'
                
                # Obtener origen (playlist o puntual)
                download_source = song.get('download_source', '')
                if download_source == 'playlist':
                    origen = 'Playlist'
                elif download_source == 'puntual':
                    origen = 'Puntual'
                else:
                    origen = 'N/A'
                
                # Formatear tamaño en MB
                file_size_bytes = song.get('file_size')
                if file_size_bytes:
                    size_mb = file_size_bytes / (1024 * 1024)
                    size_str = f"{size_mb:.2f}"
                else:
                    size_str = 'N/A'
                
                # Obtener tipo de archivo
                file_type = song.get('file_type', 'N/A')
                
                # Obtener bitrate
                bitrate_kbps = song.get('bitrate_kbps')
                if bitrate_kbps:
                    bitrate_str = str(bitrate_kbps)
                else:
                    bitrate_str = 'N/A'
                
                # Obtener URL
                url = song.get('url', 'N/A')
                
                # Preparar valores para el treeview
                values = (
                    song.get('title', 'N/A'),
                    song.get('artist', 'N/A'),
                    song.get('genre', 'N/A'),
                    song.get('year', 'N/A'),
                    size_str,
                    file_type,
                    bitrate_str,
                    formatted_date,
                    origen,
                    url,
                    song.get('file_path', 'N/A')
                )
                tags = (song.get('video_id', ''),)
                
                # Almacenar datos para filtrado
                self.db_all_data.append({
                    'values': values,
                    'tags': tags
                })
            
            # Aplicar filtro si hay texto de búsqueda
            self.filter_database_table()
        except Exception as e:
            messagebox.showerror("Error", f"Error al cargar canciones: {str(e)}")
    
    def search_database_tab(self):
        """Busca canciones en la pestaña de base de datos. 
        Ahora usa el sistema de búsqueda global, así que simplemente recarga los datos."""
        # La búsqueda ahora se hace en tiempo real con el campo de búsqueda global
        # Esta función simplemente recarga los datos
        self.load_all_songs()
    
    def sort_treeview_column(self, col):
        """Ordena el treeview por la columna especificada."""
        # Cambiar dirección si se hace clic en la misma columna
        if self.db_sort_column == col:
            self.db_sort_reverse = not self.db_sort_reverse
        else:
            self.db_sort_column = col
            self.db_sort_reverse = False
        
        # Obtener todos los items con sus valores
        items = [(self.db_tree.set(item, col), item) for item in self.db_tree.get_children('')]
        
        # Determinar si es numérico o texto
        try:
            # Intentar convertir a número (para columnas numéricas como Año, Tamaño)
            items.sort(key=lambda t: float(t[0]) if t[0] and t[0] != 'N/A' else 0, reverse=self.db_sort_reverse)
        except (ValueError, TypeError):
            # Ordenar como texto
            items.sort(key=lambda t: str(t[0]).lower() if t[0] else '', reverse=self.db_sort_reverse)
        
        # Reordenar items en el treeview
        for index, (val, item) in enumerate(items):
            self.db_tree.move(item, '', index)
        
        # Actualizar encabezado con indicador de ordenamiento
        for c in self.db_tree['columns']:
            heading_text = c
            if c == col:
                heading_text += ' ▲' if not self.db_sort_reverse else ' ▼'
            self.db_tree.heading(c, text=heading_text)
    
    def filter_database_table(self):
        """Filtra la tabla según el texto de búsqueda global."""
        search_text = self.db_global_search_var.get().strip().lower()
        
        # Limpiar treeview
        for item in self.db_tree.get_children():
            self.db_tree.delete(item)
        
        # Si no hay texto de búsqueda, mostrar todos los datos
        if not search_text:
            self._populate_treeview_from_data(self.db_all_data)
            return
        
        # Filtrar datos
        filtered_data = []
        for row_data in self.db_all_data:
            # Buscar en todos los valores de la fila
            row_values = ' '.join(str(val) for val in row_data['values']).lower()
            if search_text in row_values:
                filtered_data.append(row_data)
        
        # Mostrar datos filtrados
        self._populate_treeview_from_data(filtered_data)
    
    def _populate_treeview_from_data(self, data_list):
        """Pobla el treeview con una lista de datos."""
        for row_data in data_list:
            self.db_tree.insert('', tk.END, values=row_data['values'], tags=row_data.get('tags', ()))
    
    def show_statistics_tab(self):
        """Muestra estadísticas en la pestaña de base de datos."""
        try:
            stats = db.get_statistics()
            stats_text = f"Total de canciones: {stats['total_songs']}\n"
            stats_text += f"Videos rechazados: {stats['rejected_count']}\n"
            total_size_mb = stats['total_size_bytes'] / (1024 * 1024)
            stats_text += f"Tamaño total: {total_size_mb:.2f} MB\n\n"
            
            if stats['by_genre']:
                stats_text += "Por género:\n"
                for genre, count in sorted(stats['by_genre'].items(), key=lambda x: x[1], reverse=True)[:10]:
                    stats_text += f"  {genre}: {count}\n"
            
            if stats['by_decade']:
                stats_text += "\nPor década:\n"
                for decade, count in sorted(stats['by_decade'].items(), reverse=True):
                    stats_text += f"  {decade}: {count}\n"
            
            messagebox.showinfo("Estadísticas", stats_text)
        except Exception as e:
            messagebox.showerror("Error", f"Error al obtener estadísticas: {str(e)}")
    
    def delete_selected_song(self):
        """Elimina la canción seleccionada de la base de datos y el archivo asociado."""
        # Obtener el item seleccionado
        selected_item = self.db_tree.selection()
        if not selected_item:
            messagebox.showwarning("Sin selección", "Por favor, selecciona una canción para eliminar.")
            return
        
        # Obtener el video_id del tag del item seleccionado
        item_id = selected_item[0]
        tags = self.db_tree.item(item_id, 'tags')
        if not tags or not tags[0]:
            messagebox.showerror("Error", "No se pudo identificar la canción seleccionada.")
            return
        
        video_id = tags[0]
        
        # Obtener información de la canción para mostrar en la confirmación
        values = self.db_tree.item(item_id, 'values')
        title = values[0] if values else 'Desconocido'
        artist = values[1] if len(values) > 1 else 'Desconocido'
        file_path = values[10] if len(values) > 10 else ''  # Archivo está en la columna 10 (índice 10)
        
        # Confirmar eliminación
        confirm_msg = f"¿Estás seguro de que deseas eliminar esta canción?\n\n"
        confirm_msg += f"Título: {title}\n"
        confirm_msg += f"Artista: {artist}\n"
        if file_path:
            confirm_msg += f"Archivo: {file_path}\n"
        confirm_msg += f"\n⚠️ Esta acción eliminará:\n"
        confirm_msg += f"  - El registro de la base de datos\n"
        confirm_msg += f"  - El archivo físico asociado\n\n"
        confirm_msg += f"Esta acción NO se puede deshacer."
        
        response = messagebox.askyesno("Confirmar eliminación", confirm_msg, icon='warning')
        if not response:
            return
        
        # Eliminar canción
        try:
            # Obtener datos de la canción antes de eliminarla
            song = db.get_song_by_video_id(video_id)
            if not song:
                messagebox.showerror("Error", "No se encontró la canción en la base de datos.")
                return
            
            file_path = song.get('file_path', '')
            
            # Eliminar archivo físico si existe
            file_deleted = False
            if file_path:
                try:
                    file_path_obj = Path(file_path)
                    if file_path_obj.exists():
                        file_path_obj.unlink()
                        file_deleted = True
                except Exception as e:
                    print(f"Error al eliminar archivo: {e}")
                    # Continuar aunque falle la eliminación del archivo
            
            # Eliminar de la base de datos
            deleted_song = db.delete_song(video_id)
            if deleted_song:
                # Eliminar del treeview
                self.db_tree.delete(item_id)
                
                # Mostrar mensaje de éxito
                success_msg = f"✅ Canción eliminada correctamente:\n\n"
                success_msg += f"Título: {title}\n"
                success_msg += f"Artista: {artist}\n"
                if file_deleted:
                    success_msg += f"✓ Archivo eliminado: {file_path}\n"
                else:
                    success_msg += f"⚠️ Archivo no encontrado o no se pudo eliminar: {file_path}\n"
                success_msg += f"✓ Registro eliminado de la base de datos"
                
                messagebox.showinfo("Eliminación exitosa", success_msg)
            else:
                messagebox.showerror("Error", "No se pudo eliminar la canción de la base de datos.")
                
        except Exception as e:
            messagebox.showerror("Error", f"Error al eliminar la canción: {str(e)}")
    
    def unreject_selected_song(self):
        """Designora (elimina de rejected_videos) la canción seleccionada."""
        # Obtener el item seleccionado
        selected_item = self.db_tree.selection()
        if not selected_item:
            messagebox.showwarning("Sin selección", "Por favor, selecciona una canción ignorada para designorar.")
            return
        
        # Obtener el video_id del tag del item seleccionado
        item_id = selected_item[0]
        tags = self.db_tree.item(item_id, 'tags')
        if not tags or not tags[0]:
            messagebox.showerror("Error", "No se pudo identificar la canción seleccionada.")
            return
        
        video_id = tags[0]
        
        # Obtener información de la canción para mostrar en la confirmación
        values = self.db_tree.item(item_id, 'values')
        title = values[0] if values else 'Desconocido'
        
        # Verificar que realmente está ignorada
        if not db.is_rejected(video_id):
            messagebox.showwarning("No ignorada", f"Esta canción no está en la lista de ignoradas.")
            return
        
        # Confirmar designoración
        confirm_msg = f"¿Estás seguro de que deseas designorar esta canción?\n\n"
        confirm_msg += f"Título: {title}\n"
        confirm_msg += f"\n✓ Esta acción eliminará la canción de la lista de ignoradas\n"
        confirm_msg += f"  y volverá a aparecer en las búsquedas normales."
        
        response = messagebox.askyesno("Confirmar designoración", confirm_msg)
        if not response:
            return
        
        # Designorar canción
        try:
            success = db.remove_rejected_video(video_id)
            if success:
                # Eliminar del treeview
                self.db_tree.delete(item_id)
                
                # Mostrar mensaje de éxito
                messagebox.showinfo("Designoración exitosa", 
                                  f"✅ Canción designorada correctamente:\n\n"
                                  f"Título: {title}\n"
                                  f"✓ Eliminada de la lista de ignoradas")
                
                # Si estamos en modo "solo ignoradas", recargar la lista
                if self.db_show_ignored_only_var.get():
                    self.load_all_songs()
            else:
                messagebox.showerror("Error", "No se pudo designorar la canción.")
                
        except Exception as e:
            messagebox.showerror("Error", f"Error al designorar la canción: {str(e)}")
    
    def show_db_context_menu(self, event):
        """Muestra el menú contextual al hacer clic derecho en el Treeview."""
        try:
            self.db_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.db_context_menu.grab_release()
    
    def play_selected_song(self):
        """Reproduce el archivo de audio seleccionado usando el reproductor predeterminado del sistema."""
        selected_item = self.db_tree.selection()
        if not selected_item:
            messagebox.showwarning("Sin selección", "Por favor, selecciona una canción para reproducir.")
            return
        
        item_id = selected_item[0]
        values = self.db_tree.item(item_id, 'values')
        file_path = values[10] if len(values) > 10 else ''  # Archivo está en la columna 10 (índice 10)
        
        if not file_path or file_path == 'N/A':
            messagebox.showwarning("Sin archivo", "No hay archivo asociado a esta canción.")
            return
        
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            messagebox.showerror("Archivo no encontrado", f"El archivo no existe:\n{file_path}")
            return
        
        try:
            # Abrir con el reproductor predeterminado del sistema
            if sys.platform == "win32":
                os.startfile(str(file_path_obj))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(file_path_obj)], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
            else:
                # Linux - usar xdg-open que abre con el reproductor predeterminado
                subprocess.Popen(["xdg-open", str(file_path_obj)], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
        except Exception as e:
            messagebox.showerror("Error", f"Error al reproducir el archivo:\n{str(e)}")
    
    def open_file_in_folder(self):
        """Abre el explorador de archivos en la carpeta del archivo seleccionado."""
        selected_item = self.db_tree.selection()
        if not selected_item:
            messagebox.showwarning("Sin selección", "Por favor, selecciona una canción para ver su ubicación.")
            return
        
        item_id = selected_item[0]
        values = self.db_tree.item(item_id, 'values')
        file_path = values[10] if len(values) > 10 else ''  # Archivo está en la columna 10 (índice 10)
        
        if not file_path or file_path == 'N/A':
            messagebox.showwarning("Sin archivo", "No hay archivo asociado a esta canción.")
            return
        
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            messagebox.showerror("Archivo no encontrado", f"El archivo no existe:\n{file_path}")
            return
        
        try:
            # Abrir el explorador de archivos en la carpeta del archivo
            folder_path = file_path_obj.parent
            
            if sys.platform == "win32":
                # Windows: abrir carpeta y seleccionar archivo
                subprocess.run(["explorer", "/select,", str(file_path_obj)])
            elif sys.platform == "darwin":
                # Mac: abrir carpeta y seleccionar archivo
                subprocess.run(["open", "-R", str(file_path_obj)])
            else:
                # Linux: abrir carpeta en el administrador de archivos predeterminado
                file_managers = ["nautilus", "dolphin", "thunar", "pcmanfm", "nemo"]
                for fm in file_managers:
                    if shutil.which(fm):
                        subprocess.Popen([fm, str(folder_path)], 
                                       stdout=subprocess.DEVNULL, 
                                       stderr=subprocess.DEVNULL)
                        return
                # Si no se encuentra ningún administrador, usar xdg-open
                subprocess.Popen(["xdg-open", str(folder_path)], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
        except Exception as e:
            messagebox.showerror("Error", f"Error al abrir el explorador de archivos:\n{str(e)}")
    
    def delete_file_from_context_menu(self):
        """Elimina el archivo seleccionado desde el menú contextual."""
        # Reutilizar la función existente de eliminación
        self.delete_selected_song()
    
    # Funciones para pestaña de Monitoreo
    def monitor_log(self, message):
        """Añade un mensaje al log de monitoreo."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.monitor_log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.monitor_log_text.see(tk.END)
        self.root.update()
    
    def load_liked_playlist(self):
        """Carga la playlist con botones de acción."""
        # Limpiar widgets anteriores
        for widget in self.liked_scrollable_frame.winfo_children():
            widget.destroy()
        self.liked_checkboxes.clear()
        self.liked_videos_data.clear()
        # Limpiar referencias a frames antiguos (se recrearán con la nueva lista)
        self.song_frames.clear()
        # Limpiar reproductores activos
        for video_id in list(self.video_players.keys()):
            try:
                self.restore_thumbnail(video_id)
            except:
                pass
        self.video_players.clear()
        self.thumbnail_labels.clear()
        # Mantener downloading_videos para mostrar estado correcto al recargar
        
        def load_thread():
            try:
                playlist_url = self.liked_playlist_url_var.get().strip()
                if not playlist_url:
                    self.monitor_log("❌ Por favor, ingresa una URL de playlist.")
                    messagebox.showerror("Error", "Por favor, ingresa una URL de playlist.")
                    return
                
                self.monitor_log(f"🔍 Cargando playlist desde: {playlist_url}")
                
                try:
                    limit = int(self.liked_limit_var.get())
                except:
                    limit = 10
                
                # Obtener canciones una a una hasta tener el número solicitado de canciones visibles
                # (excluyendo las descargadas o ignoradas si el checkbox está marcado)
                visible_videos = []  # Solo canciones visibles (no ignoradas ni descargadas)
                all_checked_videos = set()  # IDs de todas las canciones que ya hemos verificado
                hide_ignored = self.liked_hide_ignored_var.get()
                start_index = 1  # Índice inicial (1-based)
                batch_size = 5  # Obtener 5 canciones a la vez para ser más eficiente
                max_attempts = limit * 20  # Límite de seguridad: buscar hasta 20x el límite solicitado
                attempt = 0
                
                self.monitor_log(f"🔍 Buscando {limit} canciones visibles (una a una)...")
                
                while len(visible_videos) < limit and attempt < max_attempts:
                    attempt += 1
                    
                    # Obtener un pequeño lote de canciones
                    batch_videos = get_liked_videos_from_url(playlist_url, limit=batch_size, start_index=start_index)
                    
                    if not batch_videos:
                        self.monitor_log("❌ No se pudieron obtener más canciones de la playlist.")
                        if attempt == 1:
                            messagebox.showerror("Error", "No se pudieron obtener las canciones de la playlist.")
                            return
                        break
                    
                    # Procesar cada canción del lote
                    found_visible = False
                    for video in batch_videos:
                        video_id = video['id']
                        
                        # Evitar procesar la misma canción dos veces
                        if video_id in all_checked_videos:
                            continue
                        
                        all_checked_videos.add(video_id)
                        
                        # Verificar si está ignorada o descargada
                        is_rejected = is_rejected_video(video_id)
                        existing_song = check_file_exists(video_id=video_id)
                        
                        if hide_ignored and (is_rejected or existing_song):
                            # Esta canción está ignorada o descargada, saltarla
                            continue
                        
                        # Esta canción es visible, agregarla
                        visible_videos.append(video)
                        found_visible = True
                        self.monitor_log(f"  ✓ [{len(visible_videos)}/{limit}] Canción visible encontrada: {video.get('title', 'Unknown')}")
                        
                        # Si ya tenemos suficientes, parar
                        if len(visible_videos) >= limit:
                            break
                    
                    # Avanzar el índice para el siguiente lote
                    start_index += len(batch_videos)
                    
                    # Si no encontramos ninguna canción visible en este lote, continuar
                    if not found_visible and len(batch_videos) > 0:
                        self.monitor_log(f"  ⊘ Lote procesado: todas las canciones estaban ignoradas/descargadas. Continuando...")
                    
                    # Si obtuvimos menos canciones de las esperadas, puede que hayamos llegado al final
                    if len(batch_videos) < batch_size:
                        self.monitor_log(f"⚠️  Se obtuvieron menos canciones de las esperadas. Puede que hayamos llegado al final de la playlist.")
                        if len(visible_videos) < limit:
                            self.monitor_log(f"⚠️  Solo se encontraron {len(visible_videos)} canciones visibles de {limit} solicitadas.")
                        break
                
                # Usar las canciones visibles encontradas
                all_videos = visible_videos
                
                if not all_videos:
                    self.monitor_log("❌ No se pudieron obtener canciones visibles de la playlist.")
                    messagebox.showerror("Error", "No se pudieron obtener canciones visibles de la playlist.")
                    return
                
                # Mostrar resumen final
                if hide_ignored:
                    self.monitor_log(f"✓ Se encontraron {len(all_videos)} canciones visibles (solicitadas: {limit})")
                else:
                    self.monitor_log(f"✓ Se encontraron {len(all_videos)} canciones en total")
                
                self.monitor_log(f"🔍 Iniciando análisis de canciones...\n")
                
                # Contadores para estadísticas
                visible_count = 0
                cached_info_count = 0
                cached_metadata_count = 0
                cached_genre_count = 0
                analyzed_count = 0
                
                # Crear botones para cada canción
                for i, video in enumerate(all_videos, 1):
                    video_id = video['id']
                    title = video['title']
                    url = video['url']
                    
                    self.monitor_log(f"[{i}/{len(all_videos)}] 🔍 Analizando: {title}")
                    
                    # Verificar si ya está descargada o rechazada
                    is_rejected = is_rejected_video(video_id)
                    existing_song = check_file_exists(video_id=video_id)
                    
                    # Si el checkbox de ocultar está marcado, saltar canciones ignoradas o descargadas
                    if self.liked_hide_ignored_var.get() and (is_rejected or existing_song):
                        if is_rejected:
                            self.monitor_log(f"  ⊘ Ignorada (se omite)")
                        elif existing_song:
                            self.monitor_log(f"  ✓ Ya descargada (se omite)")
                        continue
                    
                    visible_count += 1
                    
                    # Obtener género/estilo usando la misma lógica que en Testing
                    genre = None
                    
                    # Verificar caché de género primero (memoria y BD)
                    if video_id in self._genre_cache:
                        genre = self._genre_cache[video_id]
                        cached_genre_count += 1
                        self.monitor_log(f"  📋 Género desde caché (memoria): {genre}")
                    else:
                        # Intentar desde base de datos
                        cached_genre = db.get_cached_genre(video_id)
                        if cached_genre:
                            genre = cached_genre
                            self._genre_cache[video_id] = genre  # Cargar en memoria también
                            cached_genre_count += 1
                            self.monitor_log(f"  📋 Género desde caché (BD): {genre}")
                    
                    if existing_song and not genre:
                        # Si está descargada, obtener de la base de datos
                        song_data = db.get_song_by_video_id(video_id)
                        if song_data:
                            genre = song_data.get('genre', 'Sin Clasificar')
                            self.monitor_log(f"  📋 Género desde BD: {genre}")
                            # Guardar en caché (memoria y BD)
                            self._genre_cache[video_id] = genre
                            db.set_cached_genre(video_id, genre)
                    
                    # Obtener video_info para clasificación y thumbnail
                    video_info = None
                    
                    # Verificar caché de video_info primero (memoria y BD)
                    video_info = None
                    if video_id in self._video_info_cache:
                        video_info = self._video_info_cache[video_id]
                        cached_info_count += 1
                        self.monitor_log(f"  📋 Video info desde caché (memoria)")
                    else:
                        # Intentar desde base de datos
                        cached_data = db.get_cached_video_info(video_id)
                        if cached_data:
                            video_info = cached_data
                            self._video_info_cache[video_id] = video_info  # Cargar en memoria también
                            cached_info_count += 1
                            self.monitor_log(f"  📋 Video info desde caché (BD)")
                    
                    if not genre and not video_info:
                        try:
                            self.monitor_log(f"  🔍 Obteniendo información del video...")
                            # Obtener información del video para clasificación completa
                            video_info = get_video_info(url)
                            if video_info:
                                # Guardar en caché (memoria y BD)
                                self._video_info_cache[video_id] = video_info
                                db.set_cached_video_info(video_id, video_info)
                                self.monitor_log(f"  ✓ Información obtenida y guardada en caché")
                                
                                title_from_info = video_info.get('title', title)
                                description = video_info.get('description', '')
                                
                                # Verificar caché de metadatos (memoria y BD)
                                metadata = None
                                if video_id in self._metadata_cache:
                                    metadata = self._metadata_cache[video_id]
                                    cached_metadata_count += 1
                                    self.monitor_log(f"  📋 Metadatos desde caché (memoria)")
                                else:
                                    # Intentar desde base de datos
                                    cached_meta = db.get_cached_metadata(video_id)
                                    if cached_meta:
                                        metadata = cached_meta
                                        self._metadata_cache[video_id] = metadata  # Cargar en memoria también
                                        cached_metadata_count += 1
                                        self.monitor_log(f"  📋 Metadatos desde caché (BD)")
                                    else:
                                        # Extraer metadatos básicos
                                        metadata = extract_metadata_from_title(title_from_info, description, video_info)
                                        # Guardar en caché (memoria y BD)
                                        self._metadata_cache[video_id] = metadata
                                        db.set_cached_metadata(video_id, metadata)
                                        analyzed_count += 1
                                
                                artist = metadata.get('artist')
                                track_title = metadata.get('title', title_from_info)
                                
                                self.monitor_log(f"  🎤 Artista detectado: {artist or 'No detectado'}")
                                self.monitor_log(f"  🎵 Título: {track_title}")
                                
                                # Usar detect_genre_online() igual que en Testing
                                self.monitor_log(f"  🔍 Detectando género...")
                                detected_genre = detect_genre_online(
                                    artist,
                                    track_title,
                                    video_info=video_info,
                                    title=title_from_info,
                                    description=description
                                )
                                
                                if detected_genre:
                                    genre = detected_genre
                                    # Guardar en caché (memoria y BD)
                                    self._genre_cache[video_id] = genre
                                    db.set_cached_genre(video_id, genre)
                                    self.monitor_log(f"  ✓ Género detectado: {genre}")
                                else:
                                    self.monitor_log(f"  ⚠️  No se pudo detectar género")
                        except Exception as e:
                            self.monitor_log(f"  ⚠️  Error al obtener info: {str(e)}")
                            # Si falla, intentar método rápido como fallback
                            try:
                                detected_genre = get_genre_from_title_keywords(title)
                                if detected_genre:
                                    genre = detected_genre
                                    self._genre_cache[video_id] = genre
                                    self.monitor_log(f"  ✓ Género desde título: {genre}")
                            except:
                                pass
                    
                    # Si aún no hay video_info, intentar obtenerlo solo para el thumbnail
                    if not video_info:
                        try:
                            if video_id not in self._video_info_cache:
                                # Intentar desde BD primero
                                cached_data = db.get_cached_video_info(video_id)
                                if cached_data:
                                    video_info = cached_data
                                    self._video_info_cache[video_id] = video_info
                                else:
                                    video_info = get_video_info(url)
                                    if video_info:
                                        self._video_info_cache[video_id] = video_info
                                        db.set_cached_video_info(video_id, video_info)
                            else:
                                video_info = self._video_info_cache[video_id]
                        except:
                            pass
                    
                    # Si aún no hay género, usar "Sin Clasificar"
                    if not genre:
                        genre = 'Sin Clasificar'
                    
                    # Frame para cada canción
                    song_frame = ttk.Frame(self.liked_scrollable_frame)
                    song_frame.pack(fill=tk.X, padx=5, pady=3)
                    song_frame.columnconfigure(2, weight=1)
                    
                    # Guardar referencia al frame para poder actualizarlo después
                    self.song_frames[video_id] = song_frame
                    
                    # Verificar si está en descarga para mostrar estado
                    is_downloading = video_id in self.downloading_videos
                    if is_downloading:
                        # Aplicar estilo de descarga
                        song_frame.configure(style='Downloading.TFrame')
                    
                    # Frame para el thumbnail/reproductor (480x270 - tamaño más grande para mejor visualización)
                    thumbnail_frame = ttk.Frame(song_frame, width=480, height=270)
                    thumbnail_frame.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
                    thumbnail_frame.grid_propagate(False)  # Mantener tamaño fijo
                    
                    # Mostrar thumbnail al principio si está disponible
                    thumbnail_label = None
                    if video_info and video_info.get('thumbnail') and PIL_AVAILABLE:
                        try:
                            thumbnail_url = video_info.get('thumbnail')
                            # Descargar imagen
                            with urllib.request.urlopen(thumbnail_url) as response:
                                image_data = response.read()
                                image = Image.open(io.BytesIO(image_data))
                                # Redimensionar a tamaño para thumbnail (480x270 para que coincida con el reproductor)
                                image = image.resize((480, 270), Image.Resampling.LANCZOS)
                                photo = ImageTk.PhotoImage(image)
                                
                                # Crear label con la imagen y hacerlo clickeable
                                thumbnail_label = ttk.Label(thumbnail_frame, image=photo, cursor="hand2")
                                thumbnail_label.image = photo  # Mantener referencia
                                thumbnail_label.pack(fill=tk.BOTH, expand=True)
                                
                                # Guardar referencia al thumbnail
                                self.thumbnail_labels[video_id] = {
                                    'label': thumbnail_label,
                                    'frame': thumbnail_frame,
                                    'url': url,
                                    'title': title
                                }
                                
                                # Hacer clickeable para mostrar video embebido
                                def make_thumbnail_handler(vid_id, vid_url, vid_title):
                                    def thumbnail_click_handler(event):
                                        self.show_embedded_video_in_thumbnail(vid_id, vid_url, vid_title)
                                    return thumbnail_click_handler
                                
                                thumbnail_handler = make_thumbnail_handler(video_id, url, title)
                                thumbnail_label.bind("<Button-1>", thumbnail_handler)
                        except Exception as e:
                            # Si falla, continuar sin thumbnail
                            pass
                    
                    # Truncar título si es muy largo
                    display_title = title if len(title) <= 80 else title[:77] + "..."
                    title_col = 1 if thumbnail_label else 0
                    title_label = ttk.Label(song_frame, text=f"{visible_count}. {display_title}", 
                                           font=('Arial', 10))
                    title_label.grid(row=0, column=title_col, sticky=tk.W, padx=5)
                    
                    # Frame para información adicional (género y enlace)
                    info_frame = ttk.Frame(song_frame)
                    info_frame.grid(row=0, column=2, sticky=(tk.W, tk.E), padx=5)
                    info_frame.columnconfigure(0, weight=1)
                    
                    # Mostrar género/estilo
                    col_index = 0
                    genre_label = ttk.Label(info_frame, text=f"🎵 {genre}", 
                                           foreground="blue", font=('Arial', 9))
                    genre_label.grid(row=0, column=col_index, sticky=tk.W, padx=(0, 10))
                    col_index += 1
                    
                    # Enlace clickeable a YouTube
                    # Usar closure correcto para capturar la URL específica de cada canción
                    def make_open_handler(url_to_open):
                        def open_url_handler(event):
                            webbrowser.open(url_to_open)
                        return open_url_handler
                    
                    # Crear handler con la URL específica de esta canción
                    open_handler = make_open_handler(url)
                    
                    link_label = ttk.Label(info_frame, text="🔗 Escuchar", 
                                          foreground="blue", cursor="hand2",
                                          font=('Arial', 9, 'underline'))
                    link_label.grid(row=0, column=col_index, sticky=tk.W, padx=5)
                    link_label.bind("<Button-1>", open_handler)
                    
                    # Tooltip para mostrar la URL al pasar el ratón
                    def make_tooltip_handlers(url_to_show):
                        tooltip_window = [None]  # Usar lista para poder modificar desde funciones anidadas
                        
                        def show_tooltip(event):
                            # Crear tooltip si no existe
                            if tooltip_window[0] is None:
                                tooltip_window[0] = tk.Toplevel(self.root)
                                tooltip_window[0].wm_overrideredirect(True)
                                tooltip_window[0].wm_geometry("+%d+%d" % (event.x_root + 10, event.y_root + 10))
                                label = tk.Label(tooltip_window[0], text=url_to_show, 
                                                background="#ffffe0", relief=tk.SOLID, 
                                                borderwidth=1, font=('Arial', 8),
                                                padx=5, pady=2, wraplength=400)
                                label.pack()
                        
                        def hide_tooltip(event):
                            if tooltip_window[0]:
                                tooltip_window[0].destroy()
                                tooltip_window[0] = None
                        
                        return show_tooltip, hide_tooltip
                    
                    show_tooltip_handler, hide_tooltip_handler = make_tooltip_handlers(url)
                    link_label.bind("<Enter>", show_tooltip_handler)
                    link_label.bind("<Leave>", hide_tooltip_handler)
                    
                    # Botones de acción (solo si no está descargada ni rechazada)
                    buttons_frame = ttk.Frame(song_frame)
                    buttons_frame.grid(row=0, column=3, sticky=tk.E, padx=5)
                    
                    if not is_rejected and not existing_song:
                        # Botón Descargar - usar closure para capturar valores correctamente
                        def make_download_handler(vid_id, vid_data, btn_ref):
                            def handler():
                                # Actualizar estado visual inmediatamente
                                self.downloading_videos[vid_id] = song_frame
                                self.update_song_row_state(vid_id, "downloading")
                                # Iniciar descarga
                                self.download_single_song(vid_data, vid_id)
                            return handler
                        
                        # Crear botón y guardar referencia
                        download_btn = ttk.Button(buttons_frame, text="📥 Descargar", 
                                                 command=make_download_handler(video_id, video, None))
                        download_btn.grid(row=0, column=0, padx=2)
                        
                        # Si está en descarga, actualizar el botón
                        if is_downloading:
                            download_btn.configure(text="⏳ Descargando...", state="disabled")
                        
                        # Botón Ignorar siempre - usar closure para capturar valores correctamente
                        def make_ignore_handler(vid_id, vid_title, vid_url):
                            def handler():
                                save_rejected_video(vid_id, url=vid_url, title=vid_title, reason="Ignorar siempre")
                                self.monitor_log(f"⊘ '{vid_title}' marcada como ignorar siempre")
                                # Recargar la lista para ocultar la canción
                                self.root.after(500, self.load_liked_playlist)
                            return handler
                        
                        ignore_btn = ttk.Button(buttons_frame, text="⊘ Ignorar siempre", 
                                               command=make_ignore_handler(video_id, title, url))
                        ignore_btn.grid(row=0, column=1, padx=2)
                    else:
                        # Mostrar estado si está descargada o rechazada
                        if is_rejected:
                            status_label = ttk.Label(buttons_frame, text="[Ignorada]", foreground="gray")
                            status_label.grid(row=0, column=0, padx=5)
                        elif existing_song:
                            status_label = ttk.Label(buttons_frame, text="[Descargada]", foreground="green")
                            status_label.grid(row=0, column=0, padx=5)
                    
                    # Guardar datos
                    checkbox_var = tk.BooleanVar(value=False)  # Mantener por compatibilidad
                    self.liked_checkboxes[video_id] = checkbox_var
                    self.liked_videos_data.append({
                        'video': video,
                        'video_id': video_id,
                        'checkbox_var': checkbox_var,
                        'is_rejected': is_rejected,
                        'existing_song': existing_song
                    })
                
                # Actualizar scroll region
                self.root.after(100, lambda: self.liked_canvas.configure(
                    scrollregion=self.liked_canvas.bbox("all")))
                
                # Mostrar resumen final
                self.monitor_log(f"\n{'='*60}")
                self.monitor_log(f"✅ ANÁLISIS COMPLETADO")
                self.monitor_log(f"{'='*60}")
                self.monitor_log(f"📊 Estadísticas:")
                self.monitor_log(f"  • Total de canciones encontradas: {len(all_videos)}")
                self.monitor_log(f"  • Canciones visibles: {visible_count}")
                self.monitor_log(f"  • Información desde caché: {cached_info_count}")
                self.monitor_log(f"  • Metadatos desde caché: {cached_metadata_count}")
                self.monitor_log(f"  • Géneros desde caché: {cached_genre_count}")
                self.monitor_log(f"  • Canciones analizadas: {analyzed_count}")
                self.monitor_log(f"✅ Lista cargada. {visible_count} canción(es) visible(s).")
                
            except Exception as e:
                self.monitor_log(f"❌ Error: {str(e)}")
                messagebox.showerror("Error", f"Error al cargar playlist: {str(e)}")
        
        threading.Thread(target=load_thread, daemon=True).start()
    
    def show_embedded_video_in_thumbnail(self, video_id, video_url, video_title=""):
        """Muestra el video de YouTube embebido usando QWebEngineView en una ventana flotante."""
        import re
        if not video_id:
            video_id_match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', video_url)
            if not video_id_match:
                webbrowser.open(video_url)
                return
            video_id = video_id_match.group(1)
        
        # Verificar si ya hay un reproductor activo para este video
        if video_id in self.video_players:
            self.monitor_log(f"ℹ️  El reproductor ya está activo para este video")
            return
        
        # Verificar si existe el thumbnail para este video
        if video_id not in self.thumbnail_labels:
            webbrowser.open(video_url)
            return
        
        thumbnail_data = self.thumbnail_labels[video_id]
        thumbnail_frame = thumbnail_data.get('frame')
        thumbnail_label = thumbnail_data.get('label')
        
        # Obtener posición del thumbnail en la pantalla
        if thumbnail_frame:
            thumbnail_frame.update_idletasks()
            x = thumbnail_frame.winfo_rootx()
            y = thumbnail_frame.winfo_rooty()
            width = 480
            height = 270
        else:
            # Valores por defecto
            x, y, width, height = 100, 100, 480, 270
        
        # Crear URL de embed de YouTube
        embed_url = f"https://www.youtube.com/embed/{video_id}?autoplay=1&rel=0&modestbranding=1&controls=1&playsinline=1"
        
        self.monitor_log(f"🎬 Cargando reproductor para: {video_title}")
        self.monitor_log(f"🔗 URL embed: {embed_url}")
        
        # Intentar usar PyQt6 WebEngine si está disponible
        if PYQT6_WEBENGINE_AVAILABLE:
            try:
                # Crear una ventana flotante de PyQt6 con QWebEngineView
                from PyQt6.QtWidgets import QWidget, QVBoxLayout
                
                # Crear aplicación PyQt6 si no existe
                # IMPORTANTE: Pasar sys.argv correctamente para evitar el error
                import sys
                if not hasattr(self, '_qt_app') or self._qt_app is None:
                    self._qt_app = QApplication.instance()
                    if self._qt_app is None:
                        # Crear con sys.argv completo, o al menos con el nombre del programa
                        if len(sys.argv) > 0:
                            self._qt_app = QApplication(sys.argv)
                        else:
                            self._qt_app = QApplication(['ide.py'])
                
                # Crear ventana flotante
                video_window = QWidget()
                video_window.setWindowTitle(f"🎵 {video_title}")
                video_window.setGeometry(x, y, width, height)
                video_window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
                
                # Layout para la ventana
                layout = QVBoxLayout(video_window)
                layout.setContentsMargins(0, 0, 0, 0)
                
                # Crear QWebEngineView
                webview = QWebEngineView()
                webview.setUrl(QUrl(embed_url))
                layout.addWidget(webview)
                
                # Mostrar ventana
                video_window.show()
                
                # Procesar eventos de Qt para que la ventana se muestre
                self._qt_app.processEvents()
                
                # Guardar referencia
                self.video_players[video_id] = {
                    'window': video_window,
                    'webview': webview,
                    'thumbnail_label': thumbnail_label,
                    'type': 'webengine'
                }
                
                self.monitor_log(f"✅ Reproductor QWebEngineView creado correctamente")
                
                # Usar un timer de tkinter para procesar eventos de Qt periódicamente
                # Esto permite que ambos loops funcionen juntos sin conflictos
                def process_qt_events():
                    try:
                        if hasattr(self, '_qt_app') and self._qt_app:
                            self._qt_app.processEvents()
                        # Programar siguiente procesamiento
                        self.root.after(10, process_qt_events)
                    except:
                        pass
                
                # Iniciar procesamiento periódico de eventos de Qt
                self.root.after(10, process_qt_events)
                
                return
                
            except Exception as e:
                error_details = f"{type(e).__name__}: {str(e)}"
                self.monitor_log(f"❌ Error al crear reproductor PyQt6: {error_details}")
                import traceback
                self.monitor_log(f"📋 Traceback: {traceback.format_exc()}")
        
        # Fallback: abrir en navegador
        self.monitor_log(f"💡 Abriendo video en el navegador...")
        webbrowser.open(video_url)
    
    def _handle_video_load_error(self, video_id, video_url, error_msg):
        """Maneja errores al cargar el video embebido."""
        try:
            # NO restaurar el thumbnail - dejar el reproductor visible aunque haya error
            # Solo mostrar el error en el log
            
            # Mostrar mensaje de error detallado (sin abrir ventana adicional)
            self.monitor_log(f"\n{'='*60}")
            self.monitor_log(f"❌ ERROR AL CARGAR REPRODUCTOR")
            self.monitor_log(f"{'='*60}")
            self.monitor_log(f"Video ID: {video_id}")
            self.monitor_log(f"Error: {error_msg}")
            self.monitor_log(f"⚠️  No se pudo cargar el reproductor embebido")
            self.monitor_log(f"💡 Posibles causas:")
            self.monitor_log(f"   • tkinterweb puede tener problemas con YouTube")
            self.monitor_log(f"   • El video puede no permitir embebido")
            self.monitor_log(f"   • Problemas de conexión o permisos")
            self.monitor_log(f"💡 El reproductor permanecerá visible. Abriendo video en el navegador como alternativa...")
            self.monitor_log(f"{'='*60}\n")
            
            # Abrir en navegador como fallback (pero no restaurar thumbnail)
            webbrowser.open(video_url)
            
        except Exception as e:
            self.monitor_log(f"❌ Error al manejar error de video: {e}")
            import traceback
            self.monitor_log(f"📋 Traceback: {traceback.format_exc()}")
    
    def restore_thumbnail(self, video_id):
        """Restaura el thumbnail original ocultando el reproductor."""
        if video_id not in self.video_players:
            return
        
        try:
            player_data = self.video_players[video_id]
            html_frame = player_data['html_frame']
            thumbnail_label = player_data['thumbnail_label']
            
            # Ocultar reproductor
            html_frame.pack_forget()
            html_frame.destroy()
            
            # Mostrar thumbnail
            thumbnail_label.pack(fill=tk.BOTH, expand=True)
            
            # Eliminar de la lista de reproductores activos
            del self.video_players[video_id]
            
        except Exception as e:
            print(f"Error al restaurar thumbnail: {e}")
    
    def show_embedded_video(self, video_url, video_title=""):
        """Muestra una ventana con el video de YouTube embebido (función legacy)."""
        # Redirigir a la nueva función si es posible
        import re
        video_id_match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', video_url)
        if video_id_match:
            video_id = video_id_match.group(1)
            if video_id in self.thumbnail_labels:
                self.show_embedded_video_in_thumbnail(video_id, video_url, video_title)
                return
        
        # Si no se puede usar el thumbnail, abrir en navegador
        webbrowser.open(video_url)
    
    def update_song_row_state(self, video_id, state="downloading"):
        """Actualiza el estado visual de una fila de canción."""
        if video_id not in self.song_frames:
            return
        
        song_frame = self.song_frames[video_id]
        
        def update_in_main_thread():
            if state == "downloading":
                # Cambiar el fondo a gris
                song_frame.configure(style='Downloading.TFrame')
                # Buscar y actualizar el botón de descarga si existe
                for widget in song_frame.winfo_children():
                    if isinstance(widget, ttk.Frame):
                        for child in widget.winfo_children():
                            if isinstance(child, ttk.Button):
                                btn_text = child.cget("text")
                                if "Descargar" in btn_text and "Descargando" not in btn_text:
                                    child.configure(text="⏳ Descargando...", state="disabled")
                                    break
            elif state == "completed":
                # Restaurar estado normal (se recargará la lista)
                if video_id in self.downloading_videos:
                    del self.downloading_videos[video_id]
            elif state == "error":
                # Mostrar error
                song_frame.configure(style='Error.TFrame')
                if video_id in self.downloading_videos:
                    del self.downloading_videos[video_id]
        
        # Ejecutar en el hilo principal
        self.root.after(0, update_in_main_thread)
    
    def download_single_song(self, video, video_id):
        """Descarga una sola canción."""
        def download_thread():
            try:
                url = video['url']
                title = video['title']
                
                self.monitor_log(f"\n{'='*60}")
                self.monitor_log(f"📥 INICIANDO DESCARGA")
                self.monitor_log(f"{'='*60}")
                self.monitor_log(f"🎵 Canción: {title}")
                self.monitor_log(f"🔗 URL: {url}")
                
                # Verificar caché de video_info primero (memoria y BD)
                video_info = None
                if video_id in self._video_info_cache:
                    video_info = self._video_info_cache[video_id]
                    self.monitor_log(f"📋 Usando información desde caché (memoria)")
                else:
                    # Intentar desde base de datos
                    cached_data = db.get_cached_video_info(video_id)
                    if cached_data:
                        video_info = cached_data
                        self._video_info_cache[video_id] = video_info  # Cargar en memoria también
                        self.monitor_log(f"📋 Usando información desde caché (BD)")
                    else:
                        self.monitor_log(f"🔍 Obteniendo información del video...")
                        video_info = get_video_info(url)
                        if video_info:
                            self._video_info_cache[video_id] = video_info
                            db.set_cached_video_info(video_id, video_info)
                            self.monitor_log(f"✓ Información obtenida y guardada en caché")
                
                if not video_info:
                    self.monitor_log(f"  ❌ No se pudo obtener información")
                    return
                
                title_from_info = video_info.get('title', title)
                description = video_info.get('description', '')
                
                # Verificar caché de metadatos (memoria y BD)
                metadata = None
                if video_id in self._metadata_cache:
                    metadata = self._metadata_cache[video_id]
                    self.monitor_log(f"📋 Usando metadatos desde caché (memoria)")
                else:
                    # Intentar desde base de datos
                    cached_meta = db.get_cached_metadata(video_id)
                    if cached_meta:
                        metadata = cached_meta
                        self._metadata_cache[video_id] = metadata  # Cargar en memoria también
                        self.monitor_log(f"📋 Usando metadatos desde caché (BD)")
                    else:
                        self.monitor_log(f"🔍 Extrayendo metadatos...")
                        metadata = extract_metadata_from_title(title_from_info, description, video_info)
                        self._metadata_cache[video_id] = metadata
                        db.set_cached_metadata(video_id, metadata)
                        self.monitor_log(f"✓ Metadatos extraídos y guardados en caché")
                
                self.monitor_log(f"  🎤 Artista: {metadata.get('artist', 'No detectado')}")
                self.monitor_log(f"  📅 Año: {metadata.get('year', 'No detectado')}")
                
                # Detectar género si no está
                if not metadata.get('genre') and metadata.get('artist'):
                    # Verificar caché de género (memoria y BD)
                    if video_id in self._genre_cache:
                        metadata['genre'] = self._genre_cache[video_id]
                        self.monitor_log(f"  📋 Género desde caché (memoria): {metadata['genre']}")
                    else:
                        # Intentar desde base de datos
                        cached_genre = db.get_cached_genre(video_id)
                        if cached_genre:
                            metadata['genre'] = cached_genre
                            self._genre_cache[video_id] = cached_genre  # Cargar en memoria también
                            self.monitor_log(f"  📋 Género desde caché (BD): {metadata['genre']}")
                        else:
                            self.monitor_log(f"  🔍 Detectando género...")
                            detected_genre = detect_genre_online(
                                metadata.get('artist'), 
                                metadata.get('title', title),
                                video_info=video_info,
                                title=title_from_info,
                                description=description
                            )
                            if detected_genre:
                                metadata['genre'] = detected_genre
                                self._genre_cache[video_id] = detected_genre
                                db.set_cached_genre(video_id, detected_genre)
                                self.monitor_log(f"  ✓ Género detectado: {detected_genre}")
                            else:
                                metadata['genre'] = 'Sin Clasificar'
                                self.monitor_log(f"  ⚠️  Género no detectado, usando 'Sin Clasificar'")
                else:
                    self.monitor_log(f"  🎵 Género: {metadata.get('genre', 'Sin Clasificar')}")
                
                # Usar año actual si no hay
                if not metadata.get('year'):
                    metadata['year'] = str(datetime.now().year)
                    self.monitor_log(f"  📅 Usando año actual: {metadata['year']}")
                
                # Obtener carpeta de salida
                output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))
                self.monitor_log(f"  📁 Carpeta de destino: {output_folder}")
                
                # Crear nombre de archivo
                if metadata.get('artist'):
                    filename = f"{metadata['artist']} - {metadata['title']}"
                else:
                    filename = metadata['title']
                
                filename = sanitize_filename(filename)
                output_path = output_folder / filename
                self.monitor_log(f"  📄 Nombre de archivo: {filename}")
                
                # Descargar
                self.monitor_log(f"  📥 Iniciando descarga de audio...")
                if download_audio(url, str(output_path), metadata):
                    mp3_file = Path(str(output_path) + '.mp3')
                    if not mp3_file.exists():
                        mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
                        if mp3_files:
                            mp3_file = mp3_files[0]
                        else:
                            self.monitor_log(f"  ❌ Archivo no encontrado")
                            return
                    
                    self.monitor_log(f"  ✓ Archivo descargado: {mp3_file.name}")
                    
                    # Verificar y normalizar volumen si es necesario
                    self.monitor_log(f"  🔊 Verificando volumen...")
                    check_and_normalize_audio(str(mp3_file))
                    
                    self.monitor_log(f"  🏷️  Añadiendo metadatos ID3...")
                    add_id3_tags(str(mp3_file), metadata, video_info)
                    
                    self.monitor_log(f"  💾 Registrando en base de datos...")
                    register_song_in_db(video_id, url, mp3_file, metadata, video_info, download_source='playlist')
                    
                    self.monitor_log(f"  ✅ DESCARGA COMPLETADA: {mp3_file.name}")
                    self.monitor_log(f"  📁 Ruta: {mp3_file}")
                    
                    # Actualizar estado visual
                    self.update_song_row_state(video_id, "completed")
                    
                    # Recargar la lista para actualizar el estado
                    self.root.after(500, self.load_liked_playlist)
                else:
                    self.monitor_log(f"  ❌ Error en la descarga")
                    # Actualizar estado visual a error
                    self.update_song_row_state(video_id, "error")
                    
            except Exception as e:
                self.monitor_log(f"  ❌ Error: {str(e)}")
                import traceback
                self.monitor_log(f"  📋 Detalles: {traceback.format_exc()}")
                # Actualizar estado visual a error
                self.update_song_row_state(video_id, "error")
        
        threading.Thread(target=download_thread, daemon=True).start()
    
    def download_selected_liked(self):
        """Descarga las canciones seleccionadas de 'me gusta'."""
        # Obtener canciones seleccionadas
        selected_videos = []
        for data in self.liked_videos_data:
            if data['checkbox_var'].get() and not data['is_rejected'] and not data['existing_song']:
                selected_videos.append(data)
        
        if not selected_videos:
            messagebox.showwarning("Sin selección", "No hay canciones seleccionadas para descargar.")
            return
        
        response = messagebox.askyesno("Confirmar descarga", 
                                      f"¿Descargar {len(selected_videos)} canción(es) seleccionada(s)?")
        if not response:
            return
        
        def download_thread():
            self.monitor_log(f"\n{'='*60}")
            self.monitor_log(f"📥 INICIANDO DESCARGA MASIVA")
            self.monitor_log(f"{'='*60}\n")
            self.monitor_log(f"📊 Total de canciones a descargar: {len(selected_videos)}\n")
            
            for i, data in enumerate(selected_videos, 1):
                try:
                    video = data['video']
                    video_id = data['video_id']
                    url = video['url']
                    title = video['title']
                    
                    self.monitor_log(f"\n[{i}/{len(selected_videos)}] {'='*50}")
                    self.monitor_log(f"📥 DESCARGANDO: {title}")
                    self.monitor_log(f"🔗 URL: {url}")
                    
                    # Verificar caché de video_info primero (memoria y BD)
                    video_info = None
                    if video_id in self._video_info_cache:
                        video_info = self._video_info_cache[video_id]
                        self.monitor_log(f"  📋 Usando información desde caché (memoria)")
                    else:
                        # Intentar desde base de datos
                        cached_data = db.get_cached_video_info(video_id)
                        if cached_data:
                            video_info = cached_data
                            self._video_info_cache[video_id] = video_info  # Cargar en memoria también
                            self.monitor_log(f"  📋 Usando información desde caché (BD)")
                        else:
                            self.monitor_log(f"  🔍 Obteniendo información del video...")
                            video_info = get_video_info(url)
                            if video_info:
                                self._video_info_cache[video_id] = video_info
                                db.set_cached_video_info(video_id, video_info)
                            self.monitor_log(f"  ✓ Información obtenida y guardada en caché")
                    
                    if not video_info:
                        self.monitor_log(f"  ❌ No se pudo obtener información")
                        continue
                    
                    title_from_info = video_info.get('title', title)
                    description = video_info.get('description', '')
                    
                    # Verificar caché de metadatos (memoria y BD)
                    metadata = None
                    if video_id in self._metadata_cache:
                        metadata = self._metadata_cache[video_id]
                        self.monitor_log(f"  📋 Usando metadatos desde caché (memoria)")
                    else:
                        # Intentar desde base de datos
                        cached_meta = db.get_cached_metadata(video_id)
                        if cached_meta:
                            metadata = cached_meta
                            self._metadata_cache[video_id] = metadata  # Cargar en memoria también
                            self.monitor_log(f"  📋 Usando metadatos desde caché (BD)")
                        else:
                            self.monitor_log(f"  🔍 Extrayendo metadatos...")
                            metadata = extract_metadata_from_title(title_from_info, description, video_info)
                            self._metadata_cache[video_id] = metadata
                            db.set_cached_metadata(video_id, metadata)
                            self.monitor_log(f"  ✓ Metadatos extraídos y guardados en caché")
                    
                    self.monitor_log(f"  🎤 Artista: {metadata.get('artist', 'No detectado')}")
                    self.monitor_log(f"  📅 Año: {metadata.get('year', 'No detectado')}")
                    
                    # Detectar género si no está
                    if not metadata.get('genre') and metadata.get('artist'):
                        # Verificar caché de género (memoria y BD)
                        if video_id in self._genre_cache:
                            metadata['genre'] = self._genre_cache[video_id]
                            self.monitor_log(f"  📋 Género desde caché (memoria): {metadata['genre']}")
                        else:
                            # Intentar desde base de datos
                            cached_genre = db.get_cached_genre(video_id)
                            if cached_genre:
                                metadata['genre'] = cached_genre
                                self._genre_cache[video_id] = cached_genre  # Cargar en memoria también
                                self.monitor_log(f"  📋 Género desde caché (BD): {metadata['genre']}")
                            else:
                                self.monitor_log(f"  🔍 Detectando género...")
                                detected_genre = detect_genre_online(
                                    metadata.get('artist'), 
                                    metadata.get('title', title),
                                    video_info=video_info,
                                    title=title_from_info,
                                    description=description
                                )
                                if detected_genre:
                                    metadata['genre'] = detected_genre
                                    self._genre_cache[video_id] = detected_genre
                                    db.set_cached_genre(video_id, detected_genre)
                                    self.monitor_log(f"  ✓ Género detectado: {detected_genre}")
                                else:
                                    metadata['genre'] = 'Sin Clasificar'
                                    self.monitor_log(f"  ⚠️  Género no detectado, usando 'Sin Clasificar'")
                    else:
                        self.monitor_log(f"  🎵 Género: {metadata.get('genre', 'Sin Clasificar')}")
                    
                    # Usar año actual si no hay
                    if not metadata.get('year'):
                        metadata['year'] = str(datetime.now().year)
                        self.monitor_log(f"  📅 Usando año actual: {metadata['year']}")
                    
                    # Obtener carpeta de salida
                    output_folder = get_output_folder(MUSIC_FOLDER, metadata.get('genre'), metadata.get('year'))
                    self.monitor_log(f"  📁 Carpeta de destino: {output_folder}")
                    
                    # Crear nombre de archivo
                    if metadata.get('artist'):
                        filename = f"{metadata['artist']} - {metadata['title']}"
                    else:
                        filename = metadata['title']
                    
                    filename = sanitize_filename(filename)
                    output_path = output_folder / filename
                    self.monitor_log(f"  📄 Nombre de archivo: {filename}")
                    
                    # Descargar
                    self.monitor_log(f"  📥 Iniciando descarga de audio...")
                    if download_audio(url, str(output_path), metadata):
                        mp3_file = Path(str(output_path) + '.mp3')
                        if not mp3_file.exists():
                            mp3_files = list(output_folder.glob(f"{filename}*.mp3"))
                            if mp3_files:
                                mp3_file = mp3_files[0]
                            else:
                                self.monitor_log(f"  ❌ Archivo no encontrado")
                                continue
                        
                        self.monitor_log(f"  ✓ Archivo descargado: {mp3_file.name}")
                        
                        # Verificar y normalizar volumen si es necesario
                        self.monitor_log(f"  🔊 Verificando volumen...")
                        check_and_normalize_audio(str(mp3_file))
                        
                        self.monitor_log(f"  🏷️  Añadiendo metadatos ID3...")
                        add_id3_tags(str(mp3_file), metadata, video_info)
                        
                        self.monitor_log(f"  💾 Registrando en base de datos...")
                        register_song_in_db(video_id, url, mp3_file, metadata, video_info, download_source='playlist')
                        
                        self.monitor_log(f"  ✅ COMPLETADA: {mp3_file.name}")
                    else:
                        self.monitor_log(f"  ❌ Error en la descarga")
                        
                except Exception as e:
                    self.monitor_log(f"  ❌ Error: {str(e)}")
                    import traceback
                    self.monitor_log(f"  📋 Detalles: {traceback.format_exc()}")
            
            self.monitor_log(f"\n{'='*60}")
            self.monitor_log(f"✅ PROCESO COMPLETADO")
            self.monitor_log(f"{'='*60}\n")
            self.monitor_log(f"📊 Total procesado: {len(selected_videos)} canción(es)")
            # No mostrar pop-up, solo escribir en logs
        
        threading.Thread(target=download_thread, daemon=True).start()
    
    # Funciones para pestaña de Importar
    def import_log(self, message):
        """Añade un mensaje al log de importación."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.import_log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.import_log_text.see(tk.END)
        self.root.update()
    
    def clear_import_log(self):
        """Limpia el área de log de importación."""
        self.import_log_text.delete(1.0, tk.END)
    
    def browse_import_folder(self):
        """Abre un diálogo para seleccionar una carpeta de canciones."""
        folder = filedialog.askdirectory(title="Seleccionar carpeta de canciones")
        if folder:
            self.import_folder_var.set(folder)
            self.import_log(f"✓ Carpeta seleccionada: {folder}")
    
    def import_folder_songs(self):
        """Importa canciones desde una carpeta seleccionada."""
        folder_path = self.import_folder_var.get().strip()
        
        if not folder_path:
            messagebox.showwarning("Sin carpeta", "Por favor, selecciona una carpeta para importar.")
            return
        
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            messagebox.showerror("Error", f"La carpeta no existe: {folder_path}")
            return
        
        def import_thread():
            try:
                self.import_log(f"\n{'='*60}")
                self.import_log(f"📁 INICIANDO IMPORTACIÓN DE CARPETA")
                self.import_log(f"{'='*60}\n")
                self.import_log(f"📂 Carpeta: {folder_path}\n")
                
                # Buscar todos los archivos MP3 en la carpeta (recursivo)
                mp3_files = list(folder.rglob("*.mp3"))
                
                if not mp3_files:
                    self.import_log("⚠️  No se encontraron archivos MP3 en la carpeta.")
                    messagebox.showinfo("Sin archivos", "No se encontraron archivos MP3 en la carpeta seleccionada.")
                    return
                
                self.import_log(f"📊 Se encontraron {len(mp3_files)} archivo(s) MP3\n")
                
                imported_count = 0
                skipped_count = 0
                error_count = 0
                imported_songs = []
                skipped_songs = []
                
                for i, mp3_file in enumerate(mp3_files, 1):
                    try:
                        self.import_log(f"\n[{i}/{len(mp3_files)}] 🔍 Procesando: {mp3_file.name}")
                        
                        # Leer metadatos existentes
                        self.import_log(f"  📋 Leyendo metadatos ID3...")
                        existing_metadata = read_id3_tags(str(mp3_file))
                        
                        artist = existing_metadata.get('artist', '')
                        title = existing_metadata.get('title', '')
                        genre = existing_metadata.get('genre', '')
                        year = existing_metadata.get('year', '')
                        
                        self.import_log(f"  🎤 Artista: {artist or 'No detectado'}")
                        self.import_log(f"  🎵 Título: {title or 'No detectado'}")
                        self.import_log(f"  🎵 Género: {genre or 'No detectado'}")
                        self.import_log(f"  📅 Año: {year or 'No detectado'}")
                        
                        # Intentar extraer video_id del nombre del archivo
                        video_info = None
                        video_id = None
                        filename = mp3_file.stem
                        
                        # Buscar video_id en formato [VIDEO_ID] o (VIDEO_ID)
                        video_id_pattern = r'\[([a-zA-Z0-9_-]{11})\]|\(([a-zA-Z0-9_-]{11})\)'
                        video_id_match = re.search(video_id_pattern, filename)
                        
                        if video_id_match:
                            video_id = video_id_match.group(1) or video_id_match.group(2)
                            self.import_log(f"  🎬 Video ID detectado en nombre: {video_id}")
                            
                            # Construir URL de YouTube
                            youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                            self.import_log(f"  🔗 URL de YouTube: {youtube_url}")
                            
                            # Intentar obtener información del video
                            try:
                                # Filtro para reducir logs de YouTube
                                def quiet_log(msg):
                                    if any(x in msg for x in ["Error", "Excepción", "⚠️", "❌"]):
                                        self.import_log(msg)
                                
                                video_info = get_video_info(youtube_url, log_callback=quiet_log)
                                if video_info and video_info.get('id'):
                                    # Reducir verbosidad: no mostrar detalles del video si se obtuvo correctamente
                                    # self.import_log(f"  ✅ Información de YouTube obtenida correctamente")
                                    # self.import_log(f"     📺 Título del video: {video_info.get('title', 'N/A')}")
                                    # self.import_log(f"     👤 Canal: {video_info.get('uploader', 'N/A')}")
                                    # self.import_log(f"     📊 Vistas: {video_info.get('view_count', 'N/A')}")
                                    
                                    # Extraer metadatos del video si no están en los ID3 tags
                                    if not artist or not title:
                                        video_title = video_info.get('title', '')
                                        video_description = video_info.get('description', '')
                                        extracted_metadata = extract_metadata_from_title(
                                            video_title, 
                                            video_description, 
                                            video_info
                                        )
                                        
                                        if not artist and extracted_metadata.get('artist'):
                                            artist = extracted_metadata['artist']
                                            existing_metadata['artist'] = artist
                                            self.import_log(f"  ✓ Artista extraído de YouTube: {artist}")
                                        
                                        if not title and extracted_metadata.get('title'):
                                            title = extracted_metadata['title']
                                            existing_metadata['title'] = title
                                            self.import_log(f"  ✓ Título extraído de YouTube: {title}")
                                        
                                        if not year and extracted_metadata.get('year'):
                                            year = extracted_metadata['year']
                                            existing_metadata['year'] = year
                                            self.import_log(f"  ✓ Año extraído de YouTube: {year}")
                                        
                                        # Intentar detectar género desde los tags del video
                                        if not genre and video_info:
                                            self.import_log(f"  🔍 Buscando género en tags de YouTube...")
                                            genre_from_tags = get_genre_from_video_tags(video_info)
                                            if genre_from_tags:
                                                genre = genre_from_tags
                                                existing_metadata['genre'] = genre
                                                self.import_log(f"  ✓ Género desde tags de YouTube: {genre}")
                                            else:
                                                # Intentar desde hashtags
                                                genre_from_hashtags = get_genre_from_hashtags(
                                                    video_description, 
                                                    video_info
                                                )
                                                if genre_from_hashtags:
                                                    genre = genre_from_hashtags
                                                    existing_metadata['genre'] = genre
                                                    self.import_log(f"  ✓ Género desde hashtags: {genre}")
                                else:
                                    # El error ya fue logueado en get_video_info, solo mostrar resumen
                                    self.import_log(f"  ⚠️  No se pudo obtener información de YouTube")
                                    self.import_log(f"     Revisa los mensajes anteriores para más detalles del error")
                                    video_info = None
                            except Exception as e:
                                self.import_log(f"  ❌ Excepción al obtener información de YouTube: {type(e).__name__}")
                                self.import_log(f"     Mensaje: {str(e)}")
                                import traceback
                                self.import_log(f"     Traceback completo:")
                                for line in traceback.format_exc().split('\n'):
                                    if line.strip():
                                        self.import_log(f"        {line}")
                                video_info = None
                        else:
                            self.import_log(f"  ℹ️  No se detectó video ID en el nombre del archivo")
                        
                        # Si falta información, intentar extraerla del nombre del archivo
                        if not artist or not title:
                            if ' - ' in filename:
                                # Limpiar el nombre del archivo removiendo el video_id si existe
                                clean_filename = re.sub(r'\[([a-zA-Z0-9_-]{11})\]|\(([a-zA-Z0-9_-]{11})\)', '', filename).strip()
                                if ' - ' in clean_filename:
                                    parts = clean_filename.split(' - ', 1)
                                    if not artist:
                                        artist = parts[0].strip()
                                        existing_metadata['artist'] = artist
                                        self.import_log(f"  ✓ Artista extraído del nombre: {artist}")
                                    if not title:
                                        title = parts[1].strip()
                                        existing_metadata['title'] = title
                                        self.import_log(f"  ✓ Título extraído del nombre: {title}")
                            else:
                                if not title:
                                    # Limpiar el nombre del archivo removiendo el video_id si existe
                                    clean_filename = re.sub(r'\[([a-zA-Z0-9_-]{11})\]|\(([a-zA-Z0-9_-]{11})\)', '', filename).strip()
                                    title = clean_filename
                                    existing_metadata['title'] = title
                                    self.import_log(f"  ✓ Título extraído del nombre: {title}")
                        
                        # Verificar si ya existe en la BD (usando video_id si está disponible)
                        song_name = f"{artist} - {title}" if artist and title else (title if title else mp3_file.name)
                        if video_id:
                            existing_song = check_file_exists(video_id=video_id)
                            if existing_song:
                                self.import_log(f"  ⏭️  Ya existe en BD (por video_id), se omite")
                                skipped_songs.append(song_name)
                                skipped_count += 1
                                continue
                        elif artist and title:
                            existing_song = check_file_exists(
                                artist=artist,
                                title=title
                            )
                            if existing_song:
                                self.import_log(f"  ⏭️  Ya existe en BD (por título/artista), se omite")
                                skipped_songs.append(song_name)
                                skipped_count += 1
                                continue
                        
                        # Detectar género si no existe
                        if not genre and artist:
                            # Generar un video_id temporal para usar la caché
                            file_hash = abs(hash(str(mp3_file)))
                            temp_video_id = f"imported_{file_hash}"
                            
                            # Verificar caché de género primero
                            cached_genre = db.get_cached_genre(temp_video_id)
                            if cached_genre:
                                genre = cached_genre
                                existing_metadata['genre'] = genre
                                self.import_log(f"  📋 Género desde caché: {genre}")
                            else:
                                self.import_log(f"  🔍 Detectando género online...")
                                detected_genre = detect_genre_online(
                                    artist,
                                    title,
                                    video_info=video_info,
                                    title=title,
                                    description=video_info.get('description', '') if video_info else ""
                                )
                                if detected_genre:
                                    genre = detected_genre
                                    existing_metadata['genre'] = genre
                                    # Guardar en caché
                                    db.set_cached_genre(temp_video_id, genre)
                                    self.import_log(f"  ✓ Género detectado: {genre}")
                                else:
                                    genre = 'Sin Clasificar'
                                    existing_metadata['genre'] = genre
                                    self.import_log(f"  ⚠️  Género no detectado, usando 'Sin Clasificar'")
                        elif not genre:
                            # Si no hay artista, intentar usar Essentia (análisis de audio)
                            self.import_log(f"  ⚠️  Sin artista, intentando análisis de audio con Essentia...")
                            detected_genre = detect_genre_from_audio_file(str(mp3_file), log_callback=self.import_log)
                            if detected_genre:
                                genre = detected_genre
                                existing_metadata['genre'] = genre
                            else:
                                genre = 'Sin Clasificar'
                                existing_metadata['genre'] = genre
                                self.import_log(f"  ⚠️  No se pudo detectar género, usando 'Sin Clasificar'")
                        
                        # Si no hay año, usar año actual
                        if not year:
                            year = str(datetime.now().year)
                            existing_metadata['year'] = year
                            self.import_log(f"  📅 Usando año actual: {year}")
                        
                        # Procesar el archivo
                        self.import_log(f"  📥 Importando y organizando...")
                        result = process_imported_mp3(
                            mp3_file,
                            MUSIC_FOLDER,
                            existing_metadata=existing_metadata,
                            video_info=video_info,
                            log_callback=self.import_log
                        )
                        
                        # Actualizar song_name con los valores finales
                        song_name = f"{artist} - {title}" if artist and title else (title if title else mp3_file.name)
                        
                        if result is True:
                            self.import_log(f"  ✅ Importado correctamente")
                            self.import_log(f"  📁 Organizado en: {genre}/{get_decade_from_year(year)}")
                            imported_songs.append(song_name)
                            imported_count += 1
                        elif result is None:
                            self.import_log(f"  ⏭️  Ya existe en destino, se omite")
                            skipped_songs.append(song_name)
                            skipped_count += 1
                        else:
                            self.import_log(f"  ❌ Error al importar")
                            error_count += 1
                            
                    except Exception as e:
                        self.import_log(f"  ❌ Error: {str(e)}")
                        error_count += 1
                        import traceback
                        self.import_log(f"  📋 Detalles: {traceback.format_exc()}")
                
                # Resumen final
                self.import_log(f"\n{'='*60}")
                self.import_log(f"✅ IMPORTACIÓN COMPLETADA")
                self.import_log(f"{'='*60}\n")
                self.import_log(f"📊 Resumen:")
                self.import_log(f"  • Total de archivos: {len(mp3_files)}")
                self.import_log(f"  • Importados: {imported_count}")
                self.import_log(f"  • Omitidos (ya existían): {skipped_count}")
                self.import_log(f"  • Errores: {error_count}")
                
                # Mostrar listado de canciones importadas
                if imported_songs:
                    self.import_log(f"\n{'='*60}")
                    self.import_log(f"✅ CANCIONES IMPORTADAS ({len(imported_songs)}):")
                    self.import_log(f"{'='*60}")
                    for song in imported_songs:
                        self.import_log(f"  • {song}")
                
                # Mostrar listado de canciones ignoradas
                if skipped_songs:
                    self.import_log(f"\n{'='*60}")
                    self.import_log(f"⏭️  CANCIONES IGNORADAS ({len(skipped_songs)}):")
                    self.import_log(f"{'='*60}")
                    for song in skipped_songs:
                        self.import_log(f"  • {song}")
                
                messagebox.showinfo("Importación completada", 
                                  f"Importación finalizada.\n\n"
                                  f"Total: {len(mp3_files)}\n"
                                  f"Importados: {imported_count}\n"
                                  f"Omitidos: {skipped_count}\n"
                                  f"Errores: {error_count}")
                
            except Exception as e:
                self.import_log(f"❌ Error general: {str(e)}")
                import traceback
                self.import_log(f"📋 Detalles: {traceback.format_exc()}")
                messagebox.showerror("Error", f"Error durante la importación: {str(e)}")
        
        threading.Thread(target=import_thread, daemon=True).start()


def main():
    """Función principal."""
    root = tk.Tk()
    app = MusicDownloaderGUI(root)
    
    # Función para cerrar cuando se cierre la ventana
    def on_closing():
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
    
    # Cerrar base de datos al salir
    db.close()


if __name__ == '__main__':
    main()
