# Scripts de Descarga de Música de YouTube para DJ

Scripts de Python para descargar canciones de YouTube a MP3 con metadatos completos (artista, año, género) para uso como DJ.

## Características

- ✅ Descarga de YouTube a MP3 en la mejor calidad disponible
- ✅ Base de datos SQLite para gestionar todas las descargas
- ✅ Detección automática de género mediante APIs y búsqueda web
- ✅ Extracción automática de metadatos (artista, año, género)
- ✅ Organización automática por género y década
- ✅ Tags ID3 completos en los archivos MP3
- ✅ Verificación de archivos duplicados

## Requisitos

- Python 3.7 o superior
- FFmpeg

### Instalación de FFmpeg

**Linux (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install ffmpeg
```

**Windows:**
```bash
choco install ffmpeg
```

**Mac:**
```bash
brew install ffmpeg
```

## Instalación

1. Clona el repositorio:
```bash
git clone <url-del-repositorio>
cd DJ_scripts
```

2. Instala las dependencias:
```bash
pip install -r requirements.txt
```

3. Configura las variables de entorno:
```bash
cp env_example.txt .env
```

Edita el archivo `.env` y especifica la carpeta donde quieres guardar tu música:
```
MUSIC_FOLDER=/ruta/a/tu/carpeta/de/musica

# Opcional: API key de Last.fm para mejor detección de géneros
LASTFM_API_KEY=tu_api_key_aqui
```

## Uso

### Descarga básica
```bash
python download_youtube.py <URL_YOUTUBE>
```

### Especificar metadatos manualmente
```bash
python download_youtube.py <URL_YOUTUBE> --artist "Nombre del Artista" --year 2023 --genre "House"
```

### Descarga rápida (sin metadatos)
```bash
python download_quick.py <URL_YOUTUBE>
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

- `download_youtube.py`: Script completo con extracción de metadatos y verificación de duplicados
- `download_quick.py`: Script rápido para descargas simples
- `query_db.py`: Script para consultar y buscar en la base de datos

## Consultar la Base de Datos

```bash
# Ver estadísticas
python query_db.py stats

# Buscar canciones
python query_db.py search --artist "Deadmau5"
python query_db.py search --genre "House" --decade "2020s"
```

## Notas

- Los archivos se descargan en la mejor calidad disponible
- Los tags ID3 incluyen: título, artista, año, género y portada del video
- El script crea automáticamente la carpeta de música si no existe

## Licencia

Este script es de uso libre. Asegúrate de respetar los derechos de autor y las políticas de YouTube al descargar contenido.
