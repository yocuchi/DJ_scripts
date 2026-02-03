# Script para empaquetar la aplicación Flask en un ejecutable (Windows / PowerShell)

$ErrorActionPreference = "Stop"

Write-Host "Empaquetando aplicación Flask en ejecutable..." -ForegroundColor Green
Write-Host ""

# Verificar que PyInstaller está instalado
try {
    $null = pyinstaller --version
} catch {
    Write-Host "PyInstaller no está instalado." -ForegroundColor Red
    Write-Host "   Instálalo con: pip install pyinstaller" -ForegroundColor Yellow
    exit 1
}

# Verificar que Flask está instalado
try {
    python -c "import flask" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Flask no instalado" }
} catch {
    Write-Host "Flask no está instalado." -ForegroundColor Red
    Write-Host "   Instala las dependencias con: pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# Limpiar builds anteriores
Write-Host "Limpiando builds anteriores..." -ForegroundColor Yellow
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
Get-ChildItem -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

# Crear el ejecutable
Write-Host "Creando ejecutable con PyInstaller..." -ForegroundColor Yellow
pyinstaller build_app.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error al crear el ejecutable." -ForegroundColor Red
    exit 1
}

# En Windows el ejecutable tiene extensión .exe
$exeName = "DJ_CUCHI_app.exe"
$exePath = Join-Path "dist" $exeName

if (Test-Path $exePath) {
    Write-Host ""
    Write-Host "Ejecutable creado correctamente." -ForegroundColor Green
    Write-Host ""
    Write-Host "Ubicación: $(Resolve-Path $exePath)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Para ejecutar desde PowerShell:" -ForegroundColor Yellow
    Write-Host "   .\dist\$exeName" -ForegroundColor White
    Write-Host ""
    Write-Host "El ejecutable abrirá automáticamente el navegador en http://127.0.0.1:5000" -ForegroundColor Gray
    Write-Host ""
} else {
    Write-Host "Error: No se pudo crear el ejecutable." -ForegroundColor Red
    exit 1
}
