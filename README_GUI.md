# 🖥️ Guía para usar la GUI en WSL

## Opción 1: WSLg (Windows 11) - RECOMENDADO

Si tienes **Windows 11**, WSLg debería funcionar automáticamente.

### Pasos:

1. **Verificar que WSLg está disponible:**
   ```bash
   ls -la /tmp/.X11-unix
   ```
   Si ves un archivo `X0`, WSLg está disponible.

2. **Configurar DISPLAY (añadir a ~/.bashrc):**
   ```bash
   echo 'export DISPLAY=:0' >> ~/.bashrc
   source ~/.bashrc
   ```

3. **Ejecutar la GUI:**
   ```bash
   ./start_gui.sh
   ```
   O directamente:
   ```bash
   export DISPLAY=:0
   python3 ide.py
   ```

## Opción 2: VcXsrv (Windows 10/11)

Si WSLg no funciona o estás en Windows 10:

### Instalación:

1. **Descargar VcXsrv:**
   - Ve a: https://sourceforge.net/projects/vcxsrv/
   - Descarga e instala VcXsrv Windows X Server

2. **Configurar VcXsrv:**
   - Ejecuta **XLaunch** desde el menú de inicio
   - Configuración:
     - **Display number**: 0
     - **Start no client**: ✓ (marcado)
     - **Disable access control**: ✓ (marcado)
   - Guarda la configuración y ejecuta

3. **Configurar WSL:**
   ```bash
   # Añadir a ~/.bashrc
   export DISPLAY=$(ip route | grep default | awk '{print $3}'):0.0
   source ~/.bashrc
   ```

4. **Ejecutar la GUI:**
   ```bash
   python3 ide.py
   ```

## Opción 3: Ejecutar desde Windows directamente

Si prefieres evitar X11, puedes ejecutar la GUI directamente en Windows:

1. **Instalar Python en Windows** (si no lo tienes)
2. **Instalar dependencias:**
   ```powershell
   pip install -r requirements.txt
   ```
3. **Ejecutar:**
   ```powershell
   python ide.py
   ```

## Solución de problemas

### La ventana no aparece:

1. **Verificar DISPLAY:**
   ```bash
   echo $DISPLAY
   xset q
   ```

2. **Reiniciar WSL:**
   ```powershell
   # Desde PowerShell de Windows
   wsl --shutdown
   # Luego reinicia WSL
   ```

3. **Verificar que tkinter está instalado:**
   ```bash
   python3 -c "import tkinter; print('✓ tkinter disponible')"
   ```

### Error "No module named '_tkinter'":

```bash
# Ubuntu/Debian
sudo apt-get install python3-tk

# Fedora
sudo dnf install python3-tkinter
```

## Abrir terminal de WSL desde Cursor

Cursor puede ejecutar comandos en WSL automáticamente. También puedes:

1. **Abrir terminal integrado de Cursor:**
   - Presiona `` Ctrl+` `` (backtick)
   - O ve a: Terminal → New Terminal

2. **Abrir terminal externo de WSL:**
   - Presiona `Win + R`
   - Escribe: `wsl`
   - O busca "Ubuntu" / "WSL" en el menú de inicio

3. **Desde PowerShell de Windows:**
   ```powershell
   wsl
   ```

## Scripts útiles

- `start_gui.sh` - Inicia la GUI con X11 configurado automáticamente
- `setup_x11.sh` - Ayuda a configurar X11

