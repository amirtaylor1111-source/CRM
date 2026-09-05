@echo off
REM Double-click this to open the recorder. pythonw runs it without a
REM console window; the launcher itself closes immediately.
setlocal
set "HERE=%~dp0"
if exist "%HERE%.venv\Scripts\pythonw.exe" (
    start "" "%HERE%.venv\Scripts\pythonw.exe" -m notetaker.server
) else (
    start "" pythonw -m notetaker.server
)
endlocal
