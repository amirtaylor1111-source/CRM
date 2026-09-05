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
# Windows ships a placeholder python.exe in WindowsApps that opens the
# Microsoft Store instead of running anything. It is on PATH and it answers
# to `python`, so it fools naive detection. Reject it by path before we ever
# invoke it.

function Test-StoreStub($path) {
    return ($path -and $path -like "*\WindowsApps\*")
}

$python = $null
foreach ($candidate in @("py -3.13", "py -3.12", "py -3.11", "python3", "python")) {
    $parts = $candidate.Split(" ")
    $exe   = $parts[0]

    $resolved = Get-Command $exe -ErrorAction SilentlyContinue
    if (-not $resolved) { continue }
    if (Test-StoreStub $resolved.Source) {
        Say "Skipping the Microsoft Store placeholder at $($resolved.Source)"
        continue
    }

    try {
        if ($parts.Length -gt 1) {
            $version = & $exe $parts[1] --version 2>&1
        } else {
            $version = & $exe --version 2>&1
        }
        if ($version -match "Python 3\.(1[1-9]|[2-9][0-9])") {
            $python = $candidate
            break
        }
    } catch { }
}

if (-not $python) {
    Bad "No usable Python 3.11 or newer was found."
    Say ""
    Say "If typing 'python' opens the Microsoft Store, that is a placeholder,"
    Say "not a real install. The cleanest fix on Windows 11:"
    Say ""
    Say "    winget install Python.Python.3.12"
    Say ""
    Say "Then CLOSE this window, open a new PowerShell, and run this script"
    Say "again. PATH changes do not reach a window that is already open."
    Say ""
    Say "If winget is unavailable, download it from python.org/downloads and"
    Say "tick 'Add python.exe to PATH' on the installer's first screen."
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

# --- desktop shortcut -----------------------------------------------------
Say ""
Say "Creating a desktop shortcut ..."
try {
    $desktop  = [Environment]::GetFolderPath("Desktop")
    $lnk      = Join-Path $desktop "Meeting Notetaker.lnk"
    $pythonw  = Join-Path $root ".venv\Scripts\pythonw.exe"

    $shell    = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($lnk)
    $shortcut.TargetPath       = $pythonw
    $shortcut.Arguments        = "-m notetaker.app"
    $shortcut.WorkingDirectory = $root
    $shortcut.Description      = "Record a meeting and hand it to Claude"
    $shortcut.IconLocation     = "$env:SystemRoot\System32\SndVol.exe,0"
    $shortcut.Save()
    Ok "Shortcut on your desktop: Meeting Notetaker"
} catch {
    Say "  (could not create the shortcut - use Notetaker.cmd in this folder)"
}

# --- verify ---------------------------------------------------------------
Write-Host ""
& $venvPy -m notetaker.cli doctor

Write-Host ""
Write-Host "  Setup done." -ForegroundColor Cyan
Write-Host ""
Say "Double-click 'Meeting Notetaker' on your desktop to record."
Say "Wear headphones, or both voices land on both tracks."
Write-Host ""
