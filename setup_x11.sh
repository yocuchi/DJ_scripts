#!/bin/bash
# Script para configurar X11 forwarding en WSL

echo "🔧 Configurando X11 para WSL..."

# Detectar si estamos en WSL
if ! grep -qEi "(Microsoft|WSL)" /proc/version &> /dev/null ; then
    echo "⚠️  No parece que estés en WSL"
    exit 1
fi

# Verificar si WSLg está disponible (Windows 11)
if [ -n "$WAYLAND_DISPLAY" ] || [ -n "$DISPLAY" ]; then
    echo "✓ WSLg parece estar disponible"
    echo "DISPLAY actual: $DISPLAY"
    echo "WAYLAND_DISPLAY: $WAYLAND_DISPLAY"
    exit 0
fi

# Intentar detectar la IP de Windows
WINDOWS_IP=$(ip route | grep default | awk '{print $3}' | head -1)

if [ -z "$WINDOWS_IP" ]; then
    echo "❌ No se pudo detectar la IP de Windows"
    echo ""
    echo "💡 OPCIONES:"
    echo ""
    echo "1. Usar WSLg (Windows 11):"
    echo "   - Asegúrate de tener Windows 11 con WSLg habilitado"
    echo "   - Reinicia WSL: wsl --shutdown"
    echo ""
    echo "2. Usar VcXsrv (Windows 10/11):"
    echo "   a) Descarga VcXsrv desde: https://sourceforge.net/projects/vcxsrv/"
    echo "   b) Instálalo en Windows"
    echo "   c) Ejecuta XLaunch con estas opciones:"
    echo "      - Display number: 0"
    echo "      - Start no client: ✓"
    echo "      - Disable access control: ✓"
    echo "   d) Ejecuta este comando en WSL:"
    echo "      export DISPLAY=\$(ip route | grep default | awk '{print \$3}'):0.0"
    echo ""
    echo "3. Usar X410 (de pago pero fácil):"
    echo "   - Instala X410 desde Microsoft Store"
    echo "   - Sigue las instrucciones de configuración"
    exit 1
fi

echo "📡 IP de Windows detectada: $WINDOWS_IP"
echo ""
echo "Para usar VcXsrv o X410, ejecuta:"
echo "  export DISPLAY=$WINDOWS_IP:0.0"
echo ""
echo "O añade esto a tu ~/.bashrc:"
echo "  export DISPLAY=\$(ip route | grep default | awk '{print \$3}'):0.0"

