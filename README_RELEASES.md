# Releases de Windows

Este proyecto incluye releases automáticas que generan ejecutables para Windows.

## 🚀 Cómo usar las releases

### Descargar la última release

1. Ve a la sección [Releases](https://github.com/TU_USUARIO/TU_REPO/releases) del repositorio
2. Descarga el archivo `DJ_CUCHIDownloader.exe` de la última release
3. Ejecuta el archivo directamente - no necesitas instalar Python ni dependencias

### Uso del ejecutable

El ejecutable funciona igual que el script de Python:

```bash
DJ_CUCHIDownloader.exe "URL_DE_YOUTUBE"
```

O simplemente haz doble clic en el archivo y sigue las instrucciones.

## 📋 Requisitos

- **Windows 10 o superior**
- Conexión a Internet
- Espacio en disco para las descargas

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

### Automático (recomendado)

1. Crea un nuevo release en GitHub:
   - Ve a tu repositorio → Releases → "Draft a new release"
   - Crea un nuevo tag (ej: `v1.0.0`)
   - Añade notas de la release
   - Publica el release

2. GitHub Actions construirá automáticamente el ejecutable y lo subirá al release.

### Manual (para pruebas locales)

Si quieres construir el ejecutable localmente en Windows:

```bash
# Instalar dependencias
pip install -r requirements.txt
pip install pyinstaller

# Construir ejecutable
pyinstaller --clean build_exe.spec

# El ejecutable estará en dist/DJ_CUCHIDownloader.exe
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

- El ejecutable es independiente y no requiere Python instalado
- La primera ejecución puede ser más lenta (desempaquetado)
- Los archivos de cookies (`youtube_cookies.txt`) deben estar en el mismo directorio que el ejecutable si los necesitas

