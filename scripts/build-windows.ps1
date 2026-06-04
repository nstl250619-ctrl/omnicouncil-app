# OmniCouncil Windows Build Script
# Run this in PowerShell on Windows

param(
    [switch]$SkipPython,
    [switch]$SkipFrontend,
    [switch]$SkipTauri
)

$ErrorActionPreference = "Stop"

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "  OmniCouncil Windows Build Script" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Check prerequisites
function Check-Prereq {
    param($Name, $Command)
    try {
        Invoke-Expression $Command | Out-Null
        Write-Host "  ✅ $Name" -ForegroundColor Green
    } catch {
        Write-Host "  ❌ $Name not found" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Checking prerequisites..." -ForegroundColor Yellow
Check-Prereq "Node.js" "node --version"
Check-Prereq "npm" "npm --version"
Check-Prereq "Rust" "rustc --version"
Check-Prereq "Cargo" "cargo --version"
Write-Host ""

# Step 1: Build Frontend
if (-not $SkipFrontend) {
    Write-Host "Step 1: Building frontend..." -ForegroundColor Yellow
    npm install
    npm run build
    Write-Host "  ✅ Frontend built" -ForegroundColor Green
    Write-Host ""
}

# Step 2: Prepare Python Sidecar
if (-not $SkipPython) {
    Write-Host "Step 2: Preparing Python sidecar..." -ForegroundColor Yellow

    # Create sidecar directory
    $SidecarDir = "src-tauri\python-runtime"
    if (Test-Path $SidecarDir) {
        Remove-Item -Recurse -Force $SidecarDir
    }
    New-Item -ItemType Directory -Path $SidecarDir -Force | Out-Null

    # Download python-build-standalone
    $PythonVersion = "3.12.8"
    $PythonUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/20241219/cpython-$PythonVersion+20241219-x86_64-pc-windows-msvc-shared-install_only.tar.gz"
    $PythonArchive = "$env:TEMP\python-standalone.tar.gz"

    Write-Host "  Downloading Python $PythonVersion..." -ForegroundColor Gray
    if (-not (Test-Path $PythonArchive)) {
        Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonArchive
    }

    Write-Host "  Extracting Python..." -ForegroundColor Gray
    tar -xzf $PythonArchive -C $SidecarDir

    # Install dependencies
    Write-Host "  Installing Python dependencies..." -ForegroundColor Gray
    $PythonExe = "$SidecarDir\python\python.exe"
    & $PythonExe -m pip install --quiet -r backend\requirements.txt

    Write-Host "  ✅ Python sidecar prepared" -ForegroundColor Green
    Write-Host ""
}

# Step 3: Build Tauri
if (-not $SkipTauri) {
    Write-Host "Step 3: Building Tauri application..." -ForegroundColor Yellow
    npm run tauri build
    Write-Host "  ✅ Tauri build complete" -ForegroundColor Green
    Write-Host ""
}

# Output
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Output locations:" -ForegroundColor Yellow
Write-Host "  EXE: src-tauri\target\release\OmniCouncil.exe"
Write-Host "  MSI: src-tauri\target\release\bundle\msi\"
Write-Host ""
