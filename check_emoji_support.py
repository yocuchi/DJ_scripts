#!/usr/bin/env python3
"""
Script para verificar qué emojis se pueden mostrar correctamente.
"""

import tkinter as tk
from tkinter import ttk
import subprocess

def get_available_fonts():
    """Obtiene las fuentes disponibles en el sistema."""
    try:
        result = subprocess.run(['fc-list', ':', 'family'], 
                               capture_output=True, text=True, timeout=2)
        fonts = set()
        for line in result.stdout.split('\n'):
            if line.strip():
                # Puede haber múltiples fuentes en una línea separadas por coma
                for font in line.split(','):
                    fonts.add(font.strip())
        return sorted(fonts)
    except:
        return []

def test_emoji_display():
    """Crea una ventana para probar emojis."""
    root = tk.Tk()
    root.title("Prueba de Emojis")
    root.geometry("800x600")
    
    # Obtener fuentes disponibles
    fonts = get_available_fonts()
    
    # Emojis a probar
    test_emojis = [
        ("🎵", "Música"),
        ("📋", "Portapapeles"),
        ("📥", "Descargar"),
        ("⚡", "Rápido"),
        ("🎵", "Info"),
        ("👀", "Monitorear"),
        ("🔍", "Buscar"),
        ("📊", "Estadísticas"),
        ("🗑️", "Limpiar"),
        ("✓", "OK"),
        ("❌", "Error"),
        ("⚠️", "Advertencia"),
        ("📝", "Metadatos"),
        ("📁", "Carpeta"),
        ("🏷️", "Tags"),
        ("💾", "Guardar"),
        ("✅", "Completado"),
    ]
    
    # Frame principal
    main_frame = ttk.Frame(root, padding="20")
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Título
    title = ttk.Label(main_frame, text="Prueba de Soporte de Emojis", 
                     font=('Arial', 16, 'bold'))
    title.pack(pady=10)
    
    # Información de fuentes
    info_text = f"Fuentes disponibles: {len(fonts)}\n"
    info_text += "Fuentes con 'emoji' o 'noto':\n"
    emoji_fonts = [f for f in fonts if 'emoji' in f.lower() or 'noto' in f.lower()]
    if emoji_fonts:
        for font in emoji_fonts[:5]:
            info_text += f"  - {font}\n"
    else:
        info_text += "  (Ninguna encontrada)\n"
        info_text += "\n💡 Instala: sudo apt-get install fonts-noto-color-emoji"
    
    info_label = ttk.Label(main_frame, text=info_text, justify=tk.LEFT)
    info_label.pack(pady=10)
    
    # Probar diferentes fuentes
    test_fonts = ['Arial', 'DejaVu Sans', 'Liberation Sans']
    for font_name in test_fonts:
        if font_name in fonts or any(font_name.lower() in f.lower() for f in fonts):
            frame = ttk.LabelFrame(main_frame, text=f"Fuente: {font_name}", padding="10")
            frame.pack(fill=tk.X, pady=5)
            
            emoji_text = " ".join([f"{emoji} {name}" for emoji, name in test_emojis])
            label = ttk.Label(frame, text=emoji_text, font=(font_name, 14))
            label.pack()
    
    # Probar con Noto si está disponible
    noto_fonts = [f for f in fonts if 'noto' in f.lower()]
    if noto_fonts:
        for font_name in noto_fonts[:2]:  # Probar máximo 2 fuentes Noto
            frame = ttk.LabelFrame(main_frame, text=f"Fuente: {font_name}", padding="10")
            frame.pack(fill=tk.X, pady=5)
            
            emoji_text = " ".join([f"{emoji} {name}" for emoji, name in test_emojis])
            label = ttk.Label(frame, text=emoji_text, font=(font_name, 14))
            label.pack()
    
    root.mainloop()

if __name__ == '__main__':
    test_emoji_display()

