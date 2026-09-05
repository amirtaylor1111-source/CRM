@echo off
REM Run the notetaker using the local virtual environment if there is one.
setlocal
set "HERE=%~dp0"
if exist "%HERE%.venv\Scripts\python.exe" (
    "%HERE%.venv\Scripts\python.exe" -m notetaker.cli %*
) else (
    python -m notetaker.cli %*
)
endlocal
