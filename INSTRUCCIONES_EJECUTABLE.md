# 📦 Instrucciones para Empaquetar la Aplicación Flask

Este documento explica cómo empaquetar la aplicación Flask en un ejecutable que se puede lanzar desde la línea de comandos y que abre automáticamente el navegador.

## 🎯 Características del Ejecutable

- ✅ Se puede lanzar desde la línea de comandos
- ✅ Abre automáticamente el navegador en `http://127.0.0.1:5000`
- ✅ Muestra una consola con los logs del servidor
- ✅ Incluye todas las dependencias necesarias

## 📋 Requisitos Previos

1. **Python 3.8+** instalado
2. **PyInstaller** instalado:
   ```bash
   pip install pyinstaller
   ```
3. **Dependencias del proyecto** instaladas:
   ```bash
   pip install -r requirements.txt
   ```

## 🚀 Método 1: Usar el Script Automático (Recomendado)

El método más sencillo es usar el script proporcionado:

```bash
./build_executable.sh
```

Este script:
- Verifica que PyInstaller esté instalado
- Limpia builds anteriores
- Crea el ejecutable
- Muestra la ubicación del ejecutable creado

## 🔧 Método 2: Usar PyInstaller Directamente

Si prefieres ejecutar PyInstaller manualmente:

```bash
# Limpiar builds anteriores (opcional)
rm -rf build/ dist/ __pycache__/

# Crear el ejecutable
pyinstaller build_app.spec
```

## 🪟 Windows / PowerShell

La app funciona desde **PowerShell** igual que desde CMD o desde Linux/macOS.

### Ejecutar con Python (sin empaquetar)

```powershell
python app.py
```

### Empaquetar en Windows

```powershell
# Instalar dependencias (si no lo has hecho)
pip install -r requirements.txt
pip install pyinstaller

# Opción A: script automático
.\build_executable.ps1

# Opción B: PyInstaller directo
pyinstaller build_app.spec
```

En Windows el ejecutable se genera como **`dist\DJ_CUCHI_app.exe`**.

### Ejecutar el ejecutable desde PowerShell

```powershell
.\dist\DJ_CUCHI_app.exe
```

O con ruta completa:

```powershell
& "C:\ruta\al\proyecto\dist\DJ_CUCHI_app.exe"
```

Se abrirá una ventana de consola y, tras ~1.5 s, el navegador en `http://127.0.0.1:5000`. Para parar: `Ctrl+C` en la consola.

---

## 📁 Ubicación del Ejecutable

Después de empaquetar:

- **Linux / macOS:** `dist/DJ_CUCHI_app`
- **Windows:** `dist/DJ_CUCHI_app.exe`

## ▶️ Ejecutar el Ejecutable

**Linux / macOS:**

```bash
./dist/DJ_CUCHI_app
```

**Windows (PowerShell o CMD):**

```powershell
.\dist\DJ_CUCHI_app.exe
```

O desde cualquier ubicación (Linux/macOS):

```bash
/path/to/DJ_scripts/dist/DJ_CUCHI_app
```

### Comportamiento al Ejecutar

1. Se abrirá una ventana de consola mostrando los logs del servidor
2. Después de ~1.5 segundos, se abrirá automáticamente tu navegador predeterminado en `http://127.0.0.1:5000`
3. El servidor Flask estará disponible en todas las interfaces de red (`0.0.0.0:5000`)
4. Para detener el servidor, presiona `Ctrl+C` en la consola

## ⚙️ Configuración

El ejecutable buscará el archivo `.env` en el mismo directorio donde se ejecuta. Asegúrate de tener:

- Un archivo `.env` con las configuraciones necesarias (o copia `env_example.txt` y renómbralo)
- El archivo `youtube_cookies.txt` si lo necesitas (ya está incluido en el ejecutable)

## 🔍 Solución de Problemas

### El ejecutable no se crea

- Verifica que PyInstaller esté instalado: `pip install pyinstaller`
- Verifica que todas las dependencias estén instaladas: `pip install -r requirements.txt`
- Revisa los mensajes de error en la consola

### El navegador no se abre automáticamente

- Verifica que tengas un navegador predeterminado configurado en tu sistema
- El navegador se abre después de ~1.5 segundos, dale tiempo
- Puedes abrir manualmente `http://127.0.0.1:5000` en tu navegador

### Errores de módulos no encontrados

Si obtienes errores sobre módulos faltantes, edita `build_app.spec` y añade el módulo a la lista de `hiddenimports`.

### El ejecutable es muy grande

- Esto es normal, PyInstaller incluye Python y todas las dependencias
- El tamaño típico es de 100-300 MB dependiendo de las dependencias
- Puedes reducir el tamaño desactivando UPX en `build_app.spec` (cambia `upx=True` a `upx=False`), pero esto aumentará el tamaño

## 📝 Personalización

### Cambiar el nombre del ejecutable

Edita `build_app.spec` y cambia la línea:
```python
name='DJ_CUCHI_app',
```

### Añadir un icono

1. Crea o descarga un archivo `.ico` (Windows) o `.png` (Linux/macOS)
2. Edita `build_app.spec` y cambia:
   ```python
   icon=None,
   ```
   por:
   ```python
   icon='ruta/al/icono.ico',
   ```

### Desactivar la consola

Si no quieres ver la consola (no recomendado para depuración), edita `build_app.spec`:
```python
console=False,
```

## 🔄 Actualizar el Ejecutable

Si haces cambios en el código:

1. Ejecuta nuevamente el script de empaquetado:
   ```bash
   ./build_executable.sh
   ```
2. O ejecuta PyInstaller directamente:
   ```bash
   pyinstaller build_app.spec --clean
   ```

El flag `--clean` limpia automáticamente los builds anteriores.

## 📦 Distribuir el Ejecutable

Para distribuir el ejecutable a otros usuarios:

1. Copia el archivo `dist/DJ_CUCHI_app` a la máquina destino
2. Asegúrate de que el ejecutable tenga permisos de ejecución:
   ```bash
   chmod +x DJ_CUCHI_app
   ```
3. El usuario solo necesita ejecutar el archivo, no necesita Python instalado

**Nota**: El ejecutable es específico del sistema operativo y arquitectura donde se creó. Si creas el ejecutable en Linux, solo funcionará en Linux (y posiblemente solo en la misma distribución).
