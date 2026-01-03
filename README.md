# Scripts de Descarga de Música de YouTube para DJ

Scripts de Python para descargar canciones de YouTube a MP3 con metadatos completos (artista, año, género) para uso como DJ.

## Características

- ✅ **Interfaz gráfica (IDE)** - La forma más cómoda de usar el programa
- ✅ Descarga de YouTube a MP3 en la mejor calidad disponible
- ✅ Base de datos SQLite para gestionar todas las descargas
- ✅ Detección automática de género mediante APIs y búsqueda web
- ✅ Extracción automática de metadatos (artista, año, género)
- ✅ Organización automática por género y década
- ✅ Tags ID3 completos en los archivos MP3
- ✅ Verificación de archivos duplicados

## Requisitos

- Python 3.7 o superior
- Git
- FFmpeg

## Instalación de Requisitos

### 1. Instalar Python

#### Windows

**Opción A: Instalador oficial (Recomendado)**

1. Ve a [python.org/downloads](https://www.python.org/downloads/)
2. Descarga la última versión de Python 3.x
3. Ejecuta el instalador
4. **IMPORTANTE:** Marca la casilla "Add Python to PATH" durante la instalación
5. Haz clic en "Install Now"

**Opción B: Microsoft Store**

1. Abre Microsoft Store
2. Busca "Python 3.11" (o la versión más reciente)
3. Haz clic en "Obtener" o "Instalar"

**Verificar instalación:**
Abre PowerShell o CMD y ejecuta:
```powershell
python --version
```
Deberías ver algo como: `Python 3.11.x`

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3 python3-pip
```

**Verificar instalación:**
```bash
python3 --version
```

#### Mac

**Opción A: Homebrew (Recomendado)**
```bash
brew install python3
```

**Opción B: Instalador oficial**
1. Ve a [python.org/downloads](https://www.python.org/downloads/)
2. Descarga el instalador para macOS
3. Ejecuta el instalador

**Verificar instalación:**
```bash
python3 --version
```

### 2. Instalar Git

#### Windows

**Opción A: Instalador oficial (Recomendado)**

1. Ve a [git-scm.com/download/win](https://git-scm.com/download/win)
2. Descarga el instalador
3. Ejecuta el instalador con las opciones por defecto (recomendado)
4. Durante la instalación, selecciona "Git from the command line and also from 3rd-party software"

**Opción B: GitHub Desktop**

1. Descarga [GitHub Desktop](https://desktop.github.com/)
2. Se instala Git automáticamente

**Verificar instalación:**
Abre PowerShell o CMD y ejecuta:
```powershell
git --version
```
Deberías ver algo como: `git version 2.x.x`

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install git
```

**Verificar instalación:**
```bash
git --version
```

#### Mac

**Opción A: Homebrew**
```bash
brew install git
```

**Opción B: Xcode Command Line Tools**
```bash
xcode-select --install
```

**Verificar instalación:**
```bash
git --version
```

### 3. Instalar FFmpeg

#### Windows

**Opción A: Chocolatey (Recomendado si tienes Chocolatey)**
```powershell
choco install ffmpeg
```

**Opción B: Instalador manual**
1. Ve a [ffmpeg.org/download.html](https://ffmpeg.org/download.html)
2. Descarga la versión para Windows
3. Extrae el archivo ZIP
4. Añade la carpeta `bin` al PATH de Windows:
   - Busca "Variables de entorno" en el menú de inicio
   - Edita la variable "Path"
   - Añade la ruta a la carpeta `bin` de FFmpeg (ej: `C:\ffmpeg\bin`)

**Verificar instalación:**
```powershell
ffmpeg -version
```

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install ffmpeg
```

**Verificar instalación:**
```bash
ffmpeg -version
```

#### Mac

```bash
brew install ffmpeg
```

**Verificar instalación:**
```bash
ffmpeg -version
```

## Instalación del Proyecto

### 1. Clonar el repositorio

**Windows (PowerShell/CMD):**
```powershell
git clone https://github.com/tu-usuario/DJ_scripts.git
cd DJ_scripts
```

**Linux/Mac:**
```bash
git clone https://github.com/tu-usuario/DJ_scripts.git
cd DJ_scripts
```

> **Nota:** Si no tienes Git instalado, también puedes descargar el proyecto como ZIP desde GitHub y extraerlo.

### 2. Instalar dependencias de Python

**Windows:**
```powershell
pip install -r requirements.txt
```

**Linux/Mac:**
```bash
pip3 install -r requirements.txt
```

> **Nota:** Si tienes problemas de permisos en Linux/Mac, usa `pip3 install --user -r requirements.txt`

### 3. Configurar variables de entorno

**Windows (PowerShell):**
```powershell
Copy-Item env_example.txt .env
notepad .env
```

**Linux/Mac:**
```bash
cp env_example.txt .env
nano .env
# o usa tu editor preferido: code .env, vim .env, etc.
```

Edita el archivo `.env` y especifica la carpeta donde quieres guardar tu música:

**Windows:**
```
MUSIC_FOLDER=C:\Users\TuUsuario\Music
```

**Linux/Mac:**
```
MUSIC_FOLDER=/home/tu-usuario/Music
```

**Opcional - API key de Last.fm:**
```
# Opcional: API key de Last.fm para mejor detección de géneros
# Obtén una gratis en: https://www.last.fm/api/account/create
LASTFM_API_KEY=tu_api_key_aqui
```

## Uso

### 🖥️ Interfaz Gráfica (IDE) - RECOMENDADO

La forma más cómoda de usar el programa es mediante la interfaz gráfica:

![Interfaz Gráfica - Gestor de Música para DJ](screenshot.png)

**Windows (PowerShell/CMD):**
```powershell
python ide.py
```

**Linux/Mac:**
```bash
python3 ide.py
```

La interfaz gráfica te permite:
- Pegar URLs de YouTube fácilmente
- Ver y editar metadatos antes de descargar
- Ver el historial de descargas
- Consultar la base de datos
- Gestionar todo de forma visual

### 📝 Uso desde Línea de Comandos

Si prefieres usar la línea de comandos:

**Windows (PowerShell/CMD):**
```powershell
# Descarga básica
python download_youtube.py <URL_YOUTUBE>

# Especificar metadatos manualmente
python download_youtube.py <URL_YOUTUBE> --artist "Nombre del Artista" --year 2023 --genre "House"

# Descarga rápida (sin metadatos)
python download_quick.py <URL_YOUTUBE>
```

**Linux/Mac:**
```bash
# Descarga básica
python3 download_youtube.py <URL_YOUTUBE>

# Especificar metadatos manualmente
python3 download_youtube.py <URL_YOUTUBE> --artist "Nombre del Artista" --year 2023 --genre "House"

# Descarga rápida (sin metadatos)
python3 download_quick.py <URL_YOUTUBE>
```

## Organización de Archivos

Las canciones se organizan automáticamente en:
```
MUSIC_FOLDER/
├── House/
│   ├── 2020s/
│   └── 2010s/
├── Techno/
│   └── 2020s/
└── Sin Clasificar/
    └── Unknown/
```

## Scripts Disponibles

- `ide.py`: **Interfaz gráfica (IDE)** - La forma más cómoda de usar el programa
- `download_youtube.py`: Script completo con extracción de metadatos y verificación de duplicados
- `download_quick.py`: Script rápido para descargas simples
- `query_db.py`: Script para consultar y buscar en la base de datos

## Consultar la Base de Datos

**Windows:**
```powershell
# Ver estadísticas
python query_db.py stats

# Buscar canciones
python query_db.py search --artist "Deadmau5"
python query_db.py search --genre "House" --decade "2020s"
```

**Linux/Mac:**
```bash
# Ver estadísticas
python3 query_db.py stats

# Buscar canciones
python3 query_db.py search --artist "Deadmau5"
python3 query_db.py search --genre "House" --decade "2020s"
```

## Verificación Rápida

Antes de usar el programa, verifica que todo está instalado correctamente:

**Windows (PowerShell):**
```powershell
python --version    # Debe mostrar Python 3.7 o superior
git --version       # Debe mostrar la versión de Git
ffmpeg -version     # Debe mostrar la versión de FFmpeg
pip --version       # Debe mostrar la versión de pip
```

**Linux/Mac:**
```bash
python3 --version   # Debe mostrar Python 3.7 o superior
git --version       # Debe mostrar la versión de Git
ffmpeg -version     # Debe mostrar la versión de FFmpeg
pip3 --version      # Debe mostrar la versión de pip
```

Si alguno de estos comandos no funciona, vuelve a la sección de [Instalación de Requisitos](#instalación-de-requisitos) y sigue las instrucciones.

## Solución de Problemas

### Error: "python no se reconoce como comando" (Windows)

- Asegúrate de haber marcado "Add Python to PATH" durante la instalación
- Reinicia PowerShell/CMD después de instalar Python
- O reinstala Python marcando la opción de PATH

### Error: "git no se reconoce como comando" (Windows)

- Reinicia PowerShell/CMD después de instalar Git
- Verifica que Git está en el PATH: `$env:Path` en PowerShell

### Error: "FFmpeg not found"

- Asegúrate de tener FFmpeg instalado y en el PATH
- En Windows, verifica que añadiste la carpeta `bin` de FFmpeg al PATH del sistema

### Error: "No module named 'yt_dlp'" o similar

- Asegúrate de haber instalado las dependencias: `pip install -r requirements.txt`
- En Linux/Mac, usa `pip3` en lugar de `pip`

### La interfaz gráfica no se abre

- Asegúrate de tener Python y tkinter instalados
- En Linux, instala tkinter: `sudo apt install python3-tk`
- Verifica que puedes ejecutar: `python3 -c "import tkinter; print('OK')"`

## Notas

- Los archivos se descargan en la mejor calidad disponible
- Los tags ID3 incluyen: título, artista, año, género y portada del video
- El script crea automáticamente la carpeta de música si no existe

## Licencia

Este script es de uso libre. Asegúrate de respetar los derechos de autor y las políticas de YouTube al descargar contenido.
