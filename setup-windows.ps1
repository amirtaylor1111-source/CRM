# One-time setup. Run from this folder:
#
#     powershell -ExecutionPolicy Bypass -File setup-windows.ps1
#
# Installs into a local virtual environment. Needs no admin rights and
# touches nothing outside this folder.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Say($msg)  { Write-Host "  $msg" }
function Ok($msg)   { Write-Host "  OK    $msg" -ForegroundColor Green }
function Bad($msg)  { Write-Host "  FAIL  $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  Meeting notetaker setup" -ForegroundColor Cyan
Write-Host ""

# --- Python ---------------------------------------------------------------
$python = $null
foreach ($candidate in @("py -3.12", "py -3.11", "python", "python3")) {
    $parts = $candidate.Split(" ")
    $exe = $parts[0]
    try {
        $version = & $exe $parts[1..($parts.Length-1)] --version 2>&1
        if ($version -match "Python 3\.(1[1-9]|[2-9][0-9])") { $python = $candidate; break }
    } catch { }
}

if (-not $python) {
    Bad "Python 3.11 or newer was not found."
    Say ""
    Say "Install it from https://www.python.org/downloads/"
    Say "On the first screen, tick 'Add python.exe to PATH'."
    Say "Then run this script again."
    exit 2
}
Ok "Found $python"

# --- virtual environment --------------------------------------------------
if (Test-Path ".venv") {
    Ok "Virtual environment already exists"
} else {
    Say "Creating a virtual environment ..."
    $parts = $python.Split(" ")
    & $parts[0] $parts[1..($parts.Length-1)] -m venv .venv
    if ($LASTEXITCODE -ne 0) { Bad "Could not create the virtual environment."; exit 2 }
    Ok "Virtual environment created"
}

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { Bad "Virtual environment looks broken. Delete .venv and rerun."; exit 2 }

# --- dependencies ---------------------------------------------------------
Say ""
Say "Installing dependencies. This takes a few minutes the first time."
Say ""

& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install --quiet soundcard numpy onnx-asr
if ($LASTEXITCODE -ne 0) {
    Bad "Dependency install failed."
    Say "Try running it directly to see the error:"
    Say "  .venv\Scripts\python.exe -m pip install soundcard numpy onnx-asr"
    exit 2
}
Ok "Dependencies installed"

# --- speech model ---------------------------------------------------------
Say ""
Say "Downloading the speech model (about 670 MB, once) ..."
& $venvPy -c @"
import sys
try:
    import onnx_asr
    onnx_asr.load_model('nemo-parakeet-tdt-0.6b-v3')
    print('  OK    Speech model ready')
except Exception as exc:
    print(f'  NOTE  Model will download on first use ({exc})')
"@

# --- verify ---------------------------------------------------------------
Write-Host ""
& $venvPy -m notetaker.cli doctor

Write-Host ""
Write-Host "  Setup done." -ForegroundColor Cyan
Write-Host ""
Say "Start a meeting with:   .\mtg.cmd start"
Say "Wear headphones, or both voices land on both tracks."
Write-Host ""
