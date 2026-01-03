#!/bin/bash
# Script para instalar fuentes con soporte de emojis en WSL/Linux

echo "🔧 Instalando fuentes con soporte de emojis..."

# Detectar distribución
if [ -f /etc/debian_version ]; then
    # Debian/Ubuntu
    echo "📦 Detectado: Debian/Ubuntu"
    
    # Actualizar repositorios
    sudo apt-get update
    
    # Instalar fuentes Noto con emojis
    echo "📥 Instalando fuentes Noto Color Emoji..."
    sudo apt-get install -y fonts-noto-color-emoji fonts-noto-emoji
    
    # Instalar fuentes adicionales
    echo "📥 Instalando fuentes adicionales..."
    sudo apt-get install -y fonts-dejavu fonts-liberation
    
    echo "✅ Fuentes instaladas correctamente"
    echo ""
    echo "💡 Reinicia la aplicación para que los cambios surtan efecto"
    
elif [ -f /etc/redhat-release ]; then
    # RedHat/CentOS/Fedora
    echo "📦 Detectado: RedHat/CentOS/Fedora"
    
    # Instalar fuentes Noto
    sudo dnf install -y google-noto-emoji-fonts google-noto-color-emoji-fonts
    
    echo "✅ Fuentes instaladas correctamente"
    echo ""
    echo "💡 Reinicia la aplicación para que los cambios surtan efecto"
    
else
    echo "⚠️  Distribución no reconocida"
    echo ""
    echo "💡 Instala manualmente:"
    echo "   - fonts-noto-color-emoji (Debian/Ubuntu)"
    echo "   - google-noto-emoji-fonts (Fedora/RHEL)"
fi

# Actualizar caché de fuentes
echo ""
echo "🔄 Actualizando caché de fuentes..."
fc-cache -f -v

echo ""
echo "✅ Proceso completado!"

