#!/usr/bin/env python3
"""
EJEMPLO: Versión de la IDE usando process_interface (separación de procesos)

Este es un ejemplo de cómo modificar ide.py para usar la interfaz separada.
Solo muestra la función de descarga rápida como ejemplo.
"""

import sys
import os
import threading
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Configurar DISPLAY para WSL si no está configurado
if not os.getenv('DISPLAY'):
    if os.path.exists('/tmp/.X11-unix/X0'):
        os.environ['DISPLAY'] = ':0'
    else:
        try:
            import subprocess
            result = subprocess.run(['ip', 'route'], capture_output=True, text=True, timeout=2)
            for line in result.stdout.split('\n'):
                if 'default' in line:
                    windows_ip = line.split()[2]
                    os.environ['DISPLAY'] = f'{windows_ip}:0.0'
                    break
        except:
            os.environ['DISPLAY'] = ':0'

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# IMPORTANTE: En lugar de importar directamente, usamos la interfaz
from process_interface import get_interface

# Cargar variables de entorno
load_dotenv()

# Configuración
MUSIC_FOLDER = os.getenv('MUSIC_FOLDER', os.path.expanduser('~/Music'))

# Obtener interfaz (modo separado = False, modo directo = True)
# Cambia esto según tus necesidades:
USE_SEPARATED_MODE = True  # True = procesos separados, False = imports directos
interface = get_interface(use_direct_imports=not USE_SEPARATED_MODE)


class MusicDownloaderGUIExample:
    """Ejemplo de IDE usando la interfaz separada."""
    
    def __init__(self, root):
        self.root = root
        self.root.title("🎵 Gestor de Música para DJ (Ejemplo Separado)")
        self.root.geometry("800x600")
        
        self.url_var = tk.StringVar()
        self.log_text = None
        
        self.setup_ui()
    
    def setup_ui(self):
        """Configura la interfaz de usuario."""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Título
        title_label = ttk.Label(main_frame, text="🎵 Ejemplo: IDE Separada de Procesos", 
                               font=('Arial', 16, 'bold'))
        title_label.pack(pady=10)
        
        # Información
        info_label = ttk.Label(main_frame, 
                              text="Modo: " + ("Separado (subprocesos)" if USE_SEPARATED_MODE else "Directo (imports)"),
                              font=('Arial', 10))
        info_label.pack(pady=5)
        
        # URL
        url_frame = ttk.LabelFrame(main_frame, text="URL de YouTube", padding="10")
        url_frame.pack(fill=tk.X, pady=10)
        
        url_entry = ttk.Entry(url_frame, textvariable=self.url_var, width=60)
        url_entry.pack(side=tk.LEFT, padx=5)
        
        download_btn = ttk.Button(url_frame, text="📥 Descarga Rápida", 
                                  command=self.quick_download)
        download_btn.pack(side=tk.LEFT, padx=5)
        
        # Log
        log_frame = ttk.LabelFrame(main_frame, text="Log", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, width=80, 
                                                   font=('Consolas', 10))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        clear_btn = ttk.Button(log_frame, text="🗑️ Limpiar", command=self.clear_log)
        clear_btn.pack(pady=5)
    
    def log(self, message):
        """Añade un mensaje al log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update()
    
    def clear_log(self):
        """Limpia el log."""
        self.log_text.delete(1.0, tk.END)
    
    def quick_download(self):
        """
        EJEMPLO: Descarga rápida usando la interfaz separada.
        
        Esta función muestra cómo usar process_interface en lugar de
        importar directamente download_quick.
        """
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL vacía", "Por favor, ingresa una URL de YouTube")
            return
        
        def download_thread():
            try:
                self.log(f"\n{'='*60}")
                self.log("⚡ INICIANDO DESCARGA RÁPIDA (Modo Separado)")
                self.log(f"{'='*60}\n")
                self.log(f"📥 URL: {url}")
                self.log(f"🔧 Modo: {'Separado (subproceso)' if USE_SEPARATED_MODE else 'Directo (import)'}\n")
                
                # USAR LA INTERFAZ EN LUGAR DE IMPORTAR DIRECTAMENTE
                # Antes: download_quick(url)
                # Ahora:
                result = interface.download_quick(url)
                
                if result['success']:
                    self.log("✅ Descarga completada!")
                    if result['output']:
                        self.log(f"Salida: {result['output']}")
                else:
                    self.log(f"❌ Error en la descarga")
                    if result['error']:
                        self.log(f"Error: {result['error']}")
                    if result['output']:
                        self.log(f"Salida: {result['output']}")
                
            except Exception as e:
                self.log(f"❌ Excepción: {str(e)}")
                messagebox.showerror("Error", f"Error durante la descarga: {str(e)}")
        
        threading.Thread(target=download_thread, daemon=True).start()


def main():
    """Función principal."""
    root = tk.Tk()
    app = MusicDownloaderGUIExample(root)
    root.mainloop()


if __name__ == '__main__':
    main()

