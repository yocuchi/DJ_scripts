#!/bin/bash
# Script para empaquetar la aplicación Flask en un ejecutable

set -e

echo "🔨 Empaquetando aplicación Flask en ejecutable..."
echo ""

# Verificar que PyInstaller está instalado
if ! command -v pyinstaller &> /dev/null; then
    echo "❌ PyInstaller no está instalado."
    echo "   Instálalo con: pip install pyinstaller"
    exit 1
fi

# Verificar que las dependencias están instaladas
if ! python3 -c "import flask" 2>/dev/null; then
    echo "❌ Flask no está instalado."
    echo "   Instala las dependencias con: pip install -r requirements.txt"
    exit 1
fi

# Limpiar builds anteriores
echo "🧹 Limpiando builds anteriores..."
rm -rf build/ dist/ __pycache__/
find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Crear el ejecutable
echo "📦 Creando ejecutable con PyInstaller..."
pyinstaller build_app.spec

# Verificar que el ejecutable se creó
if [ -f "dist/DJ_CUCHI_app" ]; then
    echo ""
    echo "✅ ¡Ejecutable creado exitosamente!"
    echo ""
    echo "📁 Ubicación: $(pwd)/dist/DJ_CUCHI_app"
    echo ""
    echo "🚀 Para ejecutar:"
    echo "   ./dist/DJ_CUCHI_app"
    echo ""
    echo "💡 El ejecutable abrirá automáticamente el navegador en http://127.0.0.1:5000"
    echo ""
else
    echo "❌ Error: No se pudo crear el ejecutable"
    exit 1
fi
