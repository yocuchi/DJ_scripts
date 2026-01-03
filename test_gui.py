#!/usr/bin/env python3
"""
Script de prueba para verificar que la GUI funciona en WSL.
"""

import sys
import os

# Configurar DISPLAY si no está configurado
if not os.getenv('DISPLAY'):
    # Intentar WSLg
    if os.path.exists('/tmp/.X11-unix/X0'):
        os.environ['DISPLAY'] = ':0'
        print("✓ DISPLAY configurado para WSLg: :0")
    else:
        # Intentar con IP de Windows
        import subprocess
        try:
            result = subprocess.run(['ip', 'route'], capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if 'default' in line:
                    windows_ip = line.split()[2]
                    os.environ['DISPLAY'] = f'{windows_ip}:0.0'
                    print(f"✓ DISPLAY configurado para servidor X11: {os.environ['DISPLAY']}")
                    break
        except:
            print("⚠️  No se pudo configurar DISPLAY automáticamente")
            print("💡 Ejecuta: export DISPLAY=:0 (para WSLg) o export DISPLAY=<IP_WINDOWS>:0.0 (para VcXsrv)")

try:
    import tkinter as tk
    from tkinter import messagebox
    
    print("✓ tkinter importado correctamente")
    
    # Crear ventana de prueba
    root = tk.Tk()
    root.title("Prueba de GUI en WSL")
    root.geometry("400x200")
    
    label = tk.Label(root, text="✅ ¡La GUI funciona correctamente en WSL!", 
                     font=('Arial', 14), pady=50)
    label.pack()
    
    def close_test():
        root.destroy()
        print("✓ Prueba completada exitosamente")
    
    button = tk.Button(root, text="Cerrar", command=close_test, 
                      font=('Arial', 12), padx=20, pady=10)
    button.pack()
    
    print("✓ Ventana de prueba creada")
    print("💡 Si ves una ventana, ¡todo funciona!")
    
    root.mainloop()
    
except ImportError as e:
    print(f"❌ Error: tkinter no está instalado")
    print("💡 Instala con: sudo apt-get install python3-tk")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error al crear la ventana: {e}")
    print("💡 Verifica que DISPLAY esté configurado correctamente")
    sys.exit(1)

