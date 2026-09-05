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
# Windows ships a placeholder python.exe under WindowsApps that opens the
# Microsoft Store instead of running anything. It answers to `python`, so it
# fools version probing. Reject it by path, and if no real Python is found,
# install one rather than sending the user away to do it by hand.

function Test-StoreStub($path) { return ($path -and $path -like "*\WindowsApps\*") }

function Find-Python {
    # Ordered: the launcher first (it never resolves to the Store stub),
    # then PATH, then the standard install locations winget and python.org
    # use, which is where a just-installed Python lives before PATH updates.
    $candidates = @()
    foreach ($v in "3.13", "3.12", "3.11") { $candidates += ,@("py", "-$v") }
    $candidates += ,@("python3", $null)
    $candidates += ,@("python", $null)

    foreach ($c in $candidates) {
        $resolved = Get-Command $c[0] -ErrorAction SilentlyContinue
        if (-not $resolved) { continue }
        if (Test-StoreStub $resolved.Source) { continue }
        try {
            $version = if ($c[1]) { & $c[0] $c[1] --version 2>&1 } else { & $c[0] --version 2>&1 }
            if ($version -match "Python 3\.(1[1-9]|[2-9][0-9])") {
                return @{ Exe = $resolved.Source; Args = $c[1]; Version = "$version" }
            }
        } catch { }
    }

    # Direct paths, for a Python that exists but is not yet on PATH.
    $roots = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles\Python313", "$env:ProgramFiles\Python312", "$env:ProgramFiles\Python311"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        $exes = Get-ChildItem -Path $root -Filter python.exe -Recurse -Depth 2 -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending
        foreach ($exe in $exes) {
            if (Test-StoreStub $exe.FullName) { continue }
            try {
                $version = & $exe.FullName --version 2>&1
                if ($version -match "Python 3\.(1[1-9]|[2-9][0-9])") {
                    return @{ Exe = $exe.FullName; Args = $null; Version = "$version" }
                }
            } catch { }
        }
    }
    return $null
}

$py = Find-Python

if (-not $py) {
    Say ""
    Say "No real Python found — only the Microsoft Store placeholder."
    Say "Installing Python 3.12. This takes a couple of minutes."
    Say ""

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Bad "winget is not available on this machine."
        Say ""
        Say "Install Python by hand from https://www.python.org/downloads/"
        Say "and tick 'Add python.exe to PATH' on the first screen, then run"
        Say "this script again."
        exit 2
    }

    # --scope user avoids the admin prompt; the rest keeps it non-interactive.
    winget install --id Python.Python.3.12 --scope user --silent `
        --accept-package-agreements --accept-source-agreements
    $wingetCode = $LASTEXITCODE

    # PATH in this process is stale, so re-read it from the registry before
    # searching again. Without this, a successful install still looks absent.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")

    $py = Find-Python
    if (-not $py) {
        Bad "Python was installed but cannot be found (winget exit $wingetCode)."
        Say ""
        Say "Close this window, open a NEW PowerShell, and run this script again."
        Say "PATH changes never reach a window that was already open."
        exit 2
    }
    Ok "Installed $($py.Version)"
} else {
    Ok "Found $($py.Version)"
}

# One canonical way to invoke it from here on.
$pyExe  = $py.Exe
$pyArgs = @()
if ($py.Args) { $pyArgs = @($py.Args) }

# --- virtual environment --------------------------------------------------
if (Test-Path ".venv") {
    Ok "Virtual environment already exists"
} else {
    Say "Creating a virtual environment ..."
    & $pyExe @pyArgs -m venv .venv
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
& $venvPy -m pip install --quiet soundcard numpy "onnx-asr[cpu,hub]"
if ($LASTEXITCODE -eq 0) {
    # Install the tool itself, so `notetaker` imports from anywhere and the
    # `mtg` command exists inside the venv, rather than relying on the
    # current directory happening to be this folder.
    & $venvPy -m pip install --quiet -e .
}
if ($LASTEXITCODE -ne 0) {
    Bad "Dependency install failed."
    Say "Try running it directly to see the error:"
    Say "  .venv\Scripts\python.exe -m pip install soundcard numpy onnx-asr[cpu,hub]"
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
    onnx_asr.load_model('nemo-parakeet-tdt-0.6b-v3', quantization='int8')
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
    $shortcut.Arguments        = "-m notetaker.server"
    $shortcut.WorkingDirectory = $root
    $shortcut.Description      = "Record a meeting and hand it to Claude"
    $shortcut.IconLocation     = "$env:SystemRoot\System32\SndVol.exe,0"
    $shortcut.Save()
    Ok "Shortcut on your desktop: Meeting Notetaker"
} catch {
    Say "  (could not create the shortcut - use Notetaker.cmd in this folder)"
}

# --- run the watcher at login ---------------------------------------------
Say ""
Say "Setting the calendar watcher to run at login ..."
try {
    $startup = [Environment]::GetFolderPath("Startup")
    $lnk     = Join-Path $startup "Meeting Notetaker Watcher.lnk"
    $pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"

    $shell    = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($lnk)
    $shortcut.TargetPath       = $pythonw
    $shortcut.Arguments        = "-m notetaker.watcher"
    $shortcut.WorkingDirectory = $root
    $shortcut.Description      = "Offers to record when a meeting starts"
    $shortcut.Save()
    Ok "Watcher will start with Windows"
    Say "  (delete '$lnk' to turn it off)"
} catch {
    Say "  (could not set autostart - run 'mtg watch' by hand if you want it)"
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
