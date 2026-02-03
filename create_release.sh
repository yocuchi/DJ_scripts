#!/bin/bash
# Script de ayuda para crear releases en GitHub

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Creador de Releases para DJ_scripts${NC}"
echo ""

# Verificar que estamos en un repositorio git
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "${RED}❌ Error: No estás en un repositorio git${NC}"
    exit 1
fi

# Verificar que no hay cambios sin commitear
if ! git diff-index --quiet HEAD --; then
    echo -e "${YELLOW}⚠️  Advertencia: Tienes cambios sin commitear${NC}"
    read -p "¿Quieres continuar de todas formas? (s/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Ss]$ ]]; then
        echo "Cancelado."
        exit 1
    fi
fi

# Pedir versión
read -p "Versión de la release (ej: 1.0.0): " VERSION
if [ -z "$VERSION" ]; then
    echo -e "${RED}❌ Error: Debes proporcionar una versión${NC}"
    exit 1
fi

# Validar formato de versión
if [[ ! $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo -e "${YELLOW}⚠️  Advertencia: El formato de versión no es estándar (X.Y.Z)${NC}"
    read -p "¿Continuar de todas formas? (s/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Ss]$ ]]; then
        echo "Cancelado."
        exit 1
    fi
fi

TAG="v${VERSION}"

# Verificar que el tag no existe
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo -e "${RED}❌ Error: El tag $TAG ya existe${NC}"
    exit 1
fi

# Pedir mensaje de release
echo ""
echo "Mensaje de la release (presiona Enter para usar el mensaje por defecto):"
read -p "> " RELEASE_MESSAGE
if [ -z "$RELEASE_MESSAGE" ]; then
    RELEASE_MESSAGE="Release $TAG"
fi

# Confirmar
echo ""
echo -e "${YELLOW}Resumen:${NC}"
echo "  Tag: $TAG"
echo "  Mensaje: $RELEASE_MESSAGE"
echo "  Branch actual: $(git branch --show-current)"
echo ""
read -p "¿Crear release? (s/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Ss]$ ]]; then
    echo "Cancelado."
    exit 1
fi

# Crear tag
echo ""
echo -e "${GREEN}📌 Creando tag $TAG...${NC}"
git tag -a "$TAG" -m "$RELEASE_MESSAGE"

# Push tag
echo -e "${GREEN}📤 Subiendo tag a GitHub...${NC}"
git push origin "$TAG"

echo ""
echo -e "${GREEN}✅ Tag $TAG creado y subido${NC}"
echo ""
echo -e "${YELLOW}⏳ GitHub Actions está compilando los ejecutables...${NC}"
echo "   Puedes ver el progreso en:"
echo "   https://github.com/yocuchi/DJ_scripts/actions"
echo ""
echo -e "${YELLOW}💡 Nota:${NC} Los ejecutables se subirán automáticamente a la release"
echo "   cuando termine la compilación (típicamente 10-20 minutos)."
echo ""
echo "   Para crear la release en GitHub UI:"
echo "   https://github.com/yocuchi/DJ_scripts/releases/new?tag=$TAG"
