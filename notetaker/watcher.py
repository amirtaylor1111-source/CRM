"""Watches the calendar and offers to record when a meeting starts.

The one real weakness of recording locally instead of sending a bot is that
nothing knows a call has begun, so the tool depends on the user remembering.
This removes that. It sits quietly in the background, and when a meeting is
due it puts the widget in front of them with everything already filled in.

It only ever *offers*. Starting a recording without someone pressing the
button would record people who were never told, which is the one thing this
design will not do.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from . import log, store

_log = log.get("watcher")

POLL_SECONDS = 60
STATE_FILE = ".watcher-seen.json"
LEAD_MINUTES = 2          # offer this long before the start time


def _seen_path() -> Path:
    """Per-user state, next to the log — never inside the repo."""
    return log.log_dir() / STATE_FILE


def _load_seen() -> set[str]:
    path = _seen_path()
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


def _save_seen(seen: set[str]) -> None:
    # Keep the file small; a key is only useful while its meeting is recent.
    try:
        _seen_path().parent.mkdir(parents=True, exist_ok=True)
        _seen_path().write_text(json.dumps(sorted(seen)[-50:]), encoding="utf-8")
    except OSError:
        pass


def event_key(event: dict) -> str:
    return f"{event.get('start', '')}|{event.get('subject', '')}"


def already_recorded(event: dict) -> bool:
    """True if a meeting for this slot exists, so we do not nag twice."""
    subject = (event.get("subject") or "").strip().lower()
    day = (event.get("start") or "")[:10]
    for meeting in store.list_meetings():
        if meeting.started_at[:10] == day and meeting.title.strip().lower() == subject:
            return True
    return False


def due_now(seen: set[str]) -> dict | None:
    event = store.current_or_next(window_minutes=LEAD_MINUTES)
    if event is None:
        return None
    if event_key(event) in seen or already_recorded(event):
        return None
    return event


def _launch_app() -> None:
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    interpreter = str(pythonw) if pythonw.exists() else sys.executable
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        subprocess.Popen([interpreter, "-m", "notetaker.widget"],
                         cwd=str(store.repo_root()), creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def run_once(seen: set[str]) -> dict | None:
    """One poll. Returns the event it offered, or None."""
    event = due_now(seen)
    if event is None:
        return None
    seen.add(event_key(event))
    _save_seen(seen)
    _launch_app()
    return event


def main() -> int:
    log.setup()
    _log.info("watcher started")
    seen = _load_seen()
    while True:
        try:
            offered = run_once(seen)
            if offered:
                _log.info("offered: %s", offered.get("subject"))
        except Exception:
            _log.exception("poll failed")                       # a watcher that dies is worse than one
        time.sleep(POLL_SECONDS)       # that quietly skips a poll


if __name__ == "__main__":
    sys.exit(main())
