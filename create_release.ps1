# Script de ayuda para crear releases en GitHub (PowerShell)

Write-Host "🚀 Creador de Releases para DJ_scripts" -ForegroundColor Green
Write-Host ""

# Verificar que estamos en un repositorio git
try {
    $null = git rev-parse --git-dir 2>$null
} catch {
    Write-Host "❌ Error: No estás en un repositorio git" -ForegroundColor Red
    exit 1
}

# Verificar que no hay cambios sin commitear
$status = git status --porcelain
if ($status) {
    Write-Host "⚠️  Advertencia: Tienes cambios sin commitear" -ForegroundColor Yellow
    $response = Read-Host "¿Quieres continuar de todas formas? (s/N)"
    if ($response -notmatch "^[Ss]$") {
        Write-Host "Cancelado."
        exit 1
    }
}

# Pedir versión
$VERSION = Read-Host "Versión de la release (ej: 1.0.0)"
if ([string]::IsNullOrWhiteSpace($VERSION)) {
    Write-Host "❌ Error: Debes proporcionar una versión" -ForegroundColor Red
    exit 1
}

# Validar formato de versión
if ($VERSION -notmatch '^\d+\.\d+\.\d+$') {
    Write-Host "⚠️  Advertencia: El formato de versión no es estándar (X.Y.Z)" -ForegroundColor Yellow
    $response = Read-Host "¿Continuar de todas formas? (s/N)"
    if ($response -notmatch "^[Ss]$") {
        Write-Host "Cancelado."
        exit 1
    }
}

$TAG = "v$VERSION"

# Verificar que el tag no existe
$existingTag = git tag -l $TAG
if ($existingTag) {
    Write-Host "❌ Error: El tag $TAG ya existe" -ForegroundColor Red
    exit 1
}

# Pedir mensaje de release
Write-Host ""
Write-Host "Mensaje de la release (presiona Enter para usar el mensaje por defecto):"
$RELEASE_MESSAGE = Read-Host "> "
if ([string]::IsNullOrWhiteSpace($RELEASE_MESSAGE)) {
    $RELEASE_MESSAGE = "Release $TAG"
}

# Confirmar
Write-Host ""
Write-Host "Resumen:" -ForegroundColor Yellow
Write-Host "  Tag: $TAG"
Write-Host "  Mensaje: $RELEASE_MESSAGE"
$currentBranch = git branch --show-current
Write-Host "  Branch actual: $currentBranch"
Write-Host ""
$response = Read-Host "¿Crear release? (s/N)"
if ($response -notmatch "^[Ss]$") {
    Write-Host "Cancelado."
    exit 1
}

# Crear tag
Write-Host ""
Write-Host "📌 Creando tag $TAG..." -ForegroundColor Green
git tag -a $TAG -m $RELEASE_MESSAGE

# Push tag
Write-Host "📤 Subiendo tag a GitHub..." -ForegroundColor Green
git push origin $TAG

Write-Host ""
Write-Host "✅ Tag $TAG creado y subido" -ForegroundColor Green
Write-Host ""
Write-Host "⏳ GitHub Actions está compilando los ejecutables..." -ForegroundColor Yellow
Write-Host "   Puedes ver el progreso en:"
Write-Host "   https://github.com/yocuchi/DJ_scripts/actions"
Write-Host ""
Write-Host "💡 Nota: Los ejecutables se subirán automáticamente a la release" -ForegroundColor Yellow
Write-Host "   cuando termine la compilación (típicamente 10-20 minutos)."
Write-Host ""
Write-Host "   Para crear la release en GitHub UI:"
Write-Host "   https://github.com/yocuchi/DJ_scripts/releases/new?tag=$TAG"
