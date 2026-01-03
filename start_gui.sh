#!/bin/bash
# Script para iniciar la GUI con X11 configurado

# Configurar DISPLAY para WSLg
if [ -z "$DISPLAY" ]; then
    # Intentar WSLg primero
    if [ -S /tmp/.X11-unix/X0 ]; then
        export DISPLAY=:0
        echo "✓ WSLg detectado, usando DISPLAY=:0"
    else
        # Intentar con IP de Windows (para VcXsrv/X410)
        WINDOWS_IP=$(ip route | grep default | awk '{print $3}' | head -1)
        if [ -n "$WINDOWS_IP" ]; then
            export DISPLAY=$WINDOWS_IP:0.0
            echo "✓ Usando servidor X11 en Windows: $DISPLAY"
        else
            echo "⚠️  No se pudo detectar DISPLAY automáticamente"
            echo "💡 Intentando con DISPLAY=:0 (WSLg por defecto)..."
            export DISPLAY=:0
        fi
    fi
else
    echo "✓ DISPLAY ya configurado: $DISPLAY"
fi

# Verificar que X11 funciona
if ! xset q &>/dev/null; then
    echo "⚠️  Advertencia: X11 no responde. La GUI puede no funcionar."
    echo "💡 Intenta:"
    echo "   1. Reiniciar WSL: wsl --shutdown (desde PowerShell de Windows)"
    echo "   2. O instalar un servidor X11 como VcXsrv"
fi

# Cambiar al directorio del script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ejecutar la GUI
echo "🚀 Iniciando interfaz gráfica..."
python3 ide.py

