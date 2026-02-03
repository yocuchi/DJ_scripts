# Releases Multi-plataforma

Este proyecto incluye releases automáticas que generan ejecutables para **Windows, Linux y macOS**.

## 🚀 Cómo usar las releases

### Descargar la última release

1. Ve a la sección [Releases](https://github.com/yocuchi/DJ_scripts/releases) del repositorio
2. Descarga el ejecutable correspondiente a tu sistema operativo:
   - **Windows**: `DJ_CUCHI_*_Windows.exe`
   - **Linux**: `DJ_CUCHI_*_Linux` (dar permisos de ejecución: `chmod +x`)
   - **macOS**: `DJ_CUCHI_*_macOS` (dar permisos de ejecución: `chmod +x`)
3. Ejecuta el archivo directamente - no necesitas instalar Python ni dependencias

### Scripts disponibles

- **download_youtube**: Descargador principal de YouTube
- **download_quick**: Descarga rápida sin interfaz
- **app**: Aplicación web Flask
- **ide**: Interfaz gráfica (GUI) - solo Windows

### Uso del ejecutable

#### Windows
```bash
DJ_CUCHI_download_youtube_Windows.exe "URL_DE_YOUTUBE"
```

#### Linux/macOS
```bash
chmod +x DJ_CUCHI_download_youtube_Linux
./DJ_CUCHI_download_youtube_Linux "URL_DE_YOUTUBE"
```

O simplemente haz doble clic en el archivo (Windows) y sigue las instrucciones.

## 📋 Requisitos

- **Windows 10/11**, **Linux** (Ubuntu/Debian recomendado), o **macOS 10.15+**
- Conexión a Internet
- Espacio en disco para las descargas
- **FFmpeg** (ya incluido en los ejecutables)

## ⚙️ Configuración (opcional)

El ejecutable buscará un archivo `.env` en el mismo directorio con las siguientes variables opcionales:

```env
MUSIC_FOLDER=C:\Users\TuUsuario\Music
DB_PATH=C:\Users\TuUsuario\.youtube_music.db
LASTFM_API_KEY=tu_api_key_opcional
```

Si no existe el archivo `.env`, usará valores por defecto:
- Carpeta de música: `~/Music` (o `%USERPROFILE%\Music` en Windows)
- Base de datos: `~/.youtube_music.db`

## 🔧 Crear una nueva release

### Automático (recomendado) - GitHub Actions

El workflow se activa automáticamente cuando creas un tag que empieza con `v`:

1. **Preparar el código**:
   ```bash
   git add .
   git commit -m "Preparar release v1.0.0"
   git push
   ```

2. **Crear un tag y push**:
   ```bash
   git tag -a v1.0.0 -m "Release v1.0.0"
   git push origin v1.0.0
   ```

3. **GitHub Actions compilará automáticamente**:
   - Ejecutables para Windows, Linux y macOS
   - Todos los scripts principales
   - Los subirá automáticamente a la release

4. **O crear release desde GitHub UI**:
   - Ve a tu repositorio → Releases → "Draft a new release"
   - Crea un nuevo tag (ej: `v1.0.0`)
   - Añade notas de la release
   - Publica el release
   - GitHub Actions construirá automáticamente los ejecutables

### Manual (para pruebas locales)

Si quieres construir el ejecutable localmente:

#### Windows
```bash
# Instalar dependencias
pip install -r requirements.txt
pip install pyinstaller

# Construir ejecutable
pyinstaller --clean build_exe.spec

# El ejecutable estará en dist/DJ_CUCHI_download_youtube.exe
```

#### Linux/macOS
```bash
# Instalar dependencias
pip install -r requirements.txt
pip install pyinstaller

# Construir ejecutable
pyinstaller --clean build_exe.spec

# El ejecutable estará en dist/DJ_CUCHI_download_youtube
chmod +x dist/DJ_CUCHI_download_youtube
```

## 🐛 Solución de problemas

### El ejecutable no se ejecuta

- Verifica que tu antivirus no esté bloqueando el archivo
- Asegúrate de tener permisos de ejecución
- Ejecuta desde la línea de comandos para ver mensajes de error

### Error de dependencias faltantes

Si encuentras errores sobre módulos faltantes, edita `build_exe.spec` y añade el módulo a `hiddenimports`.

### El ejecutable es muy grande

Esto es normal - PyInstaller incluye Python y todas las dependencias. El tamaño típico es de 50-100 MB.

## 📝 Notas

- Los ejecutables son independientes y no requieren Python instalado
- La primera ejecución puede ser más lenta (desempaquetado)
- Los archivos de cookies (`youtube_cookies.txt`) deben estar en el mismo directorio que el ejecutable si los necesitas
- Los ejecutables incluyen todas las dependencias necesarias
- El tamaño típico es de 50-150 MB por ejecutable (dependiendo del script)
- Se incluyen checksums SHA256 en cada release para verificar la integridad

## 🔐 Verificar integridad

Cada release incluye un archivo `checksums.txt` con los hashes SHA256 de todos los ejecutables:

```bash
# Verificar en Linux/macOS
sha256sum -c checksums.txt

# Verificar en Windows (PowerShell)
Get-FileHash DJ_CUCHI_*_Windows.exe | Format-List
```

