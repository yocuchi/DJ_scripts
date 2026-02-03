# 🚀 Guía Rápida de Releases

## Crear una nueva release automáticamente

### Opción 1: Usando el script (Recomendado)

#### Linux/macOS:
```bash
./create_release.sh
```

#### Windows (PowerShell):
```powershell
.\create_release.ps1
```

El script te guiará paso a paso para crear el tag y subirlo a GitHub.

### Opción 2: Manualmente

1. **Asegúrate de que todos los cambios estén commiteados:**
   ```bash
   git add .
   git commit -m "Preparar release v1.0.0"
   git push
   ```

2. **Crea y sube el tag:**
   ```bash
   git tag -a v1.0.0 -m "Release v1.0.0"
   git push origin v1.0.0
   ```

3. **GitHub Actions compilará automáticamente:**
   - Ve a: https://github.com/yocuchi/DJ_scripts/actions
   - Espera a que termine la compilación (10-20 minutos)
   - Los ejecutables se subirán automáticamente a la release

### Opción 3: Desde GitHub UI

1. Ve a: https://github.com/yocuchi/DJ_scripts/releases/new
2. Crea un nuevo tag (ej: `v1.0.0`)
3. Añade notas de la release
4. Publica el release
5. GitHub Actions construirá automáticamente los ejecutables

## ¿Qué se compila?

El workflow compila automáticamente:

- ✅ **download_youtube** - Descargador principal
- ✅ **download_quick** - Descarga rápida
- ✅ **app** - Aplicación web Flask
- ✅ **ide** - Interfaz gráfica (solo Windows)

Para **Windows, Linux y macOS** (excepto `ide` que solo se compila para Windows).

## Verificar el progreso

- **Actions**: https://github.com/yocuchi/DJ_scripts/actions
- **Releases**: https://github.com/yocuchi/DJ_scripts/releases

## Notas importantes

- ⏱️ La compilación tarda aproximadamente 10-20 minutos
- 📦 Cada ejecutable incluye todas las dependencias
- 🔐 Se generan checksums SHA256 automáticamente
- 🎯 Los ejecutables son independientes (no requieren Python)

## Solución de problemas

### El workflow falla

1. Revisa los logs en: https://github.com/yocuchi/DJ_scripts/actions
2. Verifica que todos los archivos necesarios estén en el repositorio
3. Asegúrate de que el tag empiece con `v` (ej: `v1.0.0`)

### Los ejecutables no aparecen en la release

- Espera a que termine la compilación
- Verifica que el tag empiece con `v`
- Revisa los logs del workflow para errores

### Compilar localmente

Si necesitas compilar localmente para pruebas:

```bash
# Instalar dependencias
pip install -r requirements.txt
pip install pyinstaller

# Compilar un script específico
pyinstaller --clean build_exe.spec          # download_youtube
pyinstaller --clean build_download_quick.spec
pyinstaller --clean build_app.spec
pyinstaller --clean build_ide.spec
```

Los ejecutables estarán en la carpeta `dist/`.
