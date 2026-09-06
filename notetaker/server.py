"""A local HTTP server the desktop UI talks to.

The window is HTML in Edge's app mode; this is the other half. Stdlib only,
bound to loopback, one small JSON API. The UI never touches files or audio —
it asks this, and this calls the same functions the CLI does, so the two can
never disagree about what "start" means.

Security posture: loopback only, a per-launch token in every request, and no
endpoint that takes a path from the client. The worst a hostile local page
could do is start a recording, and the consent gate stops that too.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import capture, hardware, log, store, uistate

_log = log.get("server")
UI_DIR = Path(__file__).resolve().parent / "ui"

# How long the calendar and meeting list may be stale. The window polls
# far faster than either actually changes.
CACHE_SECONDS = 4.0


class Session:
    """Everything the UI needs to know, owned by the server process."""

    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self.state = uistate.IDLE
        self.meeting_dir: Path | None = None
        self.started_at = 0.0
        self.detail = ""
        self.lock = threading.Lock()
        self.last_seen = 0.0            # last time the window polled us
        # The window polls twice a second, but the meeting list and calendar
        # change on the order of minutes. Rescanning every file each poll
        # costs ~90 file opens here and grows with the history, so the slow
        # parts are cached and only the live state is recomputed.
        self._cache: dict[str, Any] = {}
        self._cache_at = 0.0
        self._adopt()

    def _adopt(self) -> None:
        """Pick up a recording left running by a previous window.

        The recorder is its own process, so closing the window never stops
        it. Reopening the app should therefore show the recording in
        progress, with the right elapsed time, rather than a fresh Ready
        screen that would let the user start a second one on top.
        """
        try:
            latest = store.latest_meeting()
            if latest is None or not capture.is_recording(latest):
                return
            data = json.loads((latest / capture.STATE_FILE).read_text(encoding="utf-8"))
            self.meeting_dir = latest
            self.started_at = float(data.get("started_at") or time.time())
            self.state = uistate.RECORDING
            _log.info("adopted in-progress recording: %s", latest.name)
        except Exception:
            _log.exception("adopt failed")

    # --- reads -------------------------------------------------------------

    def _slow_parts(self) -> dict[str, Any]:
        """Calendar and meeting history: rescanned at most every few seconds."""
        now = time.time()
        if self._cache and now - self._cache_at < CACHE_SECONDS:
            return self._cache

        me = os.environ.get("MTG_ME", "")
        try:
            suggestion = uistate.suggest(store, me=me)
        except Exception:
            suggestion = uistate.Suggestion()
        try:
            upcoming = [
                {"subject": e.get("subject", ""), "when": uistate.friendly_when(e.get("start", "")),
                 "with": ", ".join(store.attendee_names(e, me=me))}
                for e in store.upcoming(limit=4)
            ]
        except Exception:
            upcoming = []
        try:
            recent = [
                {"id": m.id, "title": m.title, "date": m.started_at[:10],
                 "with": ", ".join(p.name for p in m.participants),
                 "transcribed": m.transcribed,
                 "has_notes": (store.meetings_dir() / m.id / "notes.md").exists()}
                for m in store.list_meetings()[:8]
            ]
        except Exception:
            recent = []

        self._cache = {
            "suggestion": {"title": suggestion.title, "participants": suggestion.participants,
                           "headline": suggestion.headline, "source": suggestion.source},
            "upcoming": upcoming,
            "recent": recent,
        }
        self._cache_at = now
        return self._cache

    def _invalidate(self) -> None:
        """Force a rescan after we ourselves changed something on disk."""
        self._cache_at = 0.0

    def snapshot(self) -> dict[str, Any]:
        self.last_seen = time.time()
        slow = self._slow_parts()

        with self.lock:
            return {
                "state": self.state,
                "elapsed": uistate.elapsed_text(time.time() - self.started_at)
                if self.state == uistate.RECORDING else "",
                "detail": self.detail,
                "meeting_id": self.meeting_dir.name if self.meeting_dir else "",
                "suggestion": slow["suggestion"],
                "upcoming": slow["upcoming"],
                "recent": slow["recent"],
                "disclosure": _disclosure(),
                "claude_available": bool(_which("claude")),
            }

    # --- writes ------------------------------------------------------------

    def start(self, title: str, participants: list[str], consent: bool, solo: bool) -> dict:
        with self.lock:
            if not uistate.can_start(self.state if self.state != uistate.DONE else uistate.IDLE,
                                     consent, solo):
                return {"ok": False, "error": "Confirm you've told them, or mark it as solo."}
            title = title.strip() or (f"Call with {participants[0]}" if participants else "Meeting")
            try:
                self.meeting_dir = store.create_meeting(
                    title, participants, consent_obtained=consent,
                    consent_note="participants informed" if consent
                    else "solo recording; no other participants")
            except OSError as exc:
                return {"ok": False, "error": f"Could not create the meeting folder: {exc}"}

            try:
                subprocess.Popen(
                    [_console_python(), "-m", "notetaker.cli", "_record", str(self.meeting_dir)],
                    cwd=str(store.repo_root()), creationflags=_no_window(),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                return {"ok": False, "error": str(exc)}

            self.started_at = time.time()
            self.state = uistate.RECORDING
            self.detail = ""
            self._invalidate()
            _log.info("start: %s", self.meeting_dir.name)

        # Confirm the recorder actually came up before reporting success.
        for _ in range(20):
            time.sleep(0.25)
            if capture.is_recording(self.meeting_dir):
                return {"ok": True, "meeting_id": self.meeting_dir.name}
            state_file = self.meeting_dir / capture.STATE_FILE
            if state_file.exists():
                try:
                    data = json.loads(state_file.read_text(encoding="utf-8"))
                    if data.get("error"):
                        with self.lock:
                            self.state = uistate.ERROR
                            self.detail = data["error"].splitlines()[0]
                        return {"ok": False, "error": data["error"]}
                except (OSError, json.JSONDecodeError):
                    pass
        with self.lock:
            self.state = uistate.ERROR
            self.detail = "The recorder did not start. Run Check setup."
        return {"ok": False, "error": self.detail}

    def stop(self) -> dict:
        with self.lock:
            if self.state != uistate.RECORDING:
                return {"ok": False, "error": "Nothing is recording."}
            self.state = uistate.TRANSCRIBING
            self.detail = "Stopping..."
        threading.Thread(target=self._finish, daemon=True).start()
        return {"ok": True}

    def _finish(self):
        try:
            tracks = capture.stop_recording(self.meeting_dir)
            if not tracks:
                self._set(uistate.ERROR, "No audio was captured — run Check setup")
                return
            store.finalize_meeting(self.meeting_dir, tracks=tracks)

            from . import transcribe as tr

            seconds = sum(capture.audio_duration(Path(t)) for t in tracks if t.endswith(".wav"))
            choice = hardware.recommend()
            self._set(uistate.TRANSCRIBING,
                      f"Transcribing — {hardware.format_estimate(seconds, choice)}")
            tr.transcribe_meeting(self.meeting_dir, vocabulary=store.vocabulary(),
                                  progress=lambda m: self._set(uistate.TRANSCRIBING, str(m)[:70]))

            meeting = store.load_meeting(self.meeting_dir)
            meeting.transcribed = True
            store.save_meeting(self.meeting_dir, meeting)
            for person in meeting.participants:
                store.link_contact(self.meeting_dir, person.name)
            store.rebuild_index()
            self._invalidate()
            self._set(uistate.DONE, "")
            _log.info("done: %s", self.meeting_dir.name)
        except Exception as exc:
            _log.exception("finish failed")
            self._set(uistate.ERROR, str(exc)[:90])

    def _set(self, state: str, detail: str):
        with self.lock:
            self.state = state
            self.detail = detail

    def reset(self) -> dict:
        with self.lock:
            if self.state in (uistate.DONE, uistate.ERROR):
                self.state = uistate.IDLE
                self.detail = ""
                self.meeting_dir = None
        return {"ok": True}

    def doctor(self) -> dict:
        result = subprocess.run([_console_python(), "-m", "notetaker.cli", "doctor"],
                                capture_output=True, text=True, cwd=str(store.repo_root()),
                                creationflags=_no_window())
        return {"ok": result.returncode == 0, "output": (result.stdout or "") + (result.stderr or "")}

    def open_folder(self, meeting_id: str = "") -> dict:
        target = store.repo_root()
        safe = _safe_id(meeting_id)
        if safe:
            candidate = store.meetings_dir() / safe
            if candidate.exists():
                target = candidate
        elif self.meeting_dir:
            target = self.meeting_dir
        _reveal(target)
        return {"ok": True}

    def write_up(self, meeting_id: str = "") -> dict:
        """Open Claude Code with /notes queued. On the user's plan, visibly."""
        target = _safe_id(meeting_id) or (self.meeting_dir.name if self.meeting_dir else "")
        if not _which("claude"):
            return {"ok": False, "error": "Claude Code is not installed or not on PATH.",
                    "command": f"/notes {target}".strip()}
        try:
            if sys.platform == "win32":
                subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", "claude",
                                  f"/notes {target}".strip()], cwd=str(store.repo_root()))
            else:
                subprocess.Popen(["claude", f"/notes {target}".strip()], cwd=str(store.repo_root()))
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}


# --- http ------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    session: Session = None  # set by serve()

    def log_message(self, fmt, *args):     # keep the console quiet
        _log.debug("http " + fmt, *args)

    def _json(self, status: int, payload: Any):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        return self.headers.get("X-Token") == self.session.token

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            html = (UI_DIR / "index.html").read_text(encoding="utf-8")
            html = html.replace("__TOKEN__", self.session.token)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if not self._authorised():
            return self._json(403, {"error": "forbidden"})
        if path == "/api/state":
            self.session.last_seen = time.time()
            return self._json(200, self.session.snapshot())
        if path == "/api/doctor":
            return self._json(200, self.session.doctor())
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorised():
            return self._json(403, {"error": "forbidden"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"ok": False, "error": "bad json"})

        path = self.path.split("?", 1)[0]
        s = self.session
        if path == "/api/start":
            people = [p.strip() for p in str(payload.get("participants", "")).split(",") if p.strip()]
            return self._json(200, s.start(str(payload.get("title", "")), people,
                                           bool(payload.get("consent")), bool(payload.get("solo"))))
        if path == "/api/stop":
            return self._json(200, s.stop())
        if path == "/api/reset":
            return self._json(200, s.reset())
        if path == "/api/open":
            return self._json(200, s.open_folder(str(payload.get("meeting_id", ""))))
        if path == "/api/writeup":
            return self._json(200, s.write_up(str(payload.get("meeting_id", ""))))
        self._json(404, {"ok": False, "error": "not found"})


IDLE_EXIT_SECONDS = 12      # no poll from the window for this long => it closed
STARTUP_GRACE_SECONDS = 45  # but give Edge time to open on a slow machine


def _lock_path() -> Path:
    return log.log_dir() / "app.lock"


def _running_instance() -> str:
    """URL of an already-running app, or "" if there is none."""
    import socket

    try:
        data = json.loads(_lock_path().read_text(encoding="utf-8"))
        port = int(data["port"])
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return f"http://127.0.0.1:{port}/"
    except Exception:
        return ""


def _watchdog(httpd, session: Session, started: float) -> None:
    """Shut the server down once the window has gone.

    Exempts transcription, which runs inside this process and must finish.
    A recording is safe to leave: it is a separate process, and the next
    launch adopts it.
    """
    while True:
        time.sleep(2)
        now = time.time()
        if session.state == uistate.TRANSCRIBING:
            continue
        seen = session.last_seen or started
        limit = STARTUP_GRACE_SECONDS if not session.last_seen else IDLE_EXIT_SECONDS
        if now - seen > limit:
            _log.info("window gone; exiting")
            httpd.shutdown()
            return


def serve(open_browser: bool = True, port: int = 0) -> int:
    log.setup()

    existing = _running_instance()
    if existing and open_browser:
        _log.info("already running at %s; opening a window to it", existing)
        _open_window(existing)
        return 0

    session = Session()
    Handler.session = session
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    _log.info("serving %s", url)

    try:
        _lock_path().parent.mkdir(parents=True, exist_ok=True)
        _lock_path().write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass

    if open_browser:
        threading.Thread(target=_open_window, args=(url,), daemon=True).start()
    threading.Thread(target=_watchdog, args=(httpd, session, time.time()), daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        try:
            _lock_path().unlink(missing_ok=True)
        except OSError:
            pass
    return 0


# --- helpers ---------------------------------------------------------------


def _open_window(url: str) -> None:
    """Edge app mode gives a chromeless window; fall back to any browser."""
    time.sleep(0.3)
    if sys.platform == "win32":
        for exe in (
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ):
            if os.path.exists(exe):
                subprocess.Popen([exe, f"--app={url}", "--window-size=520,840"])
                return
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        if _which(name):
            subprocess.Popen([name, f"--app={url}", "--window-size=520,840"])
            return
    import webbrowser

    webbrowser.open(url)


def _disclosure() -> str:
    from .cli import DISCLOSURE

    return DISCLOSURE


def _which(name: str):
    import shutil

    return shutil.which(name)


def _console_python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        c = exe.with_name("python.exe")
        if c.exists():
            return str(c)
    return sys.executable


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _safe_id(meeting_id: str) -> str:
    """A meeting id is a directory name; refuse anything with path parts."""
    meeting_id = (meeting_id or "").strip()
    if not meeting_id or "/" in meeting_id or "\\" in meeting_id or ".." in meeting_id:
        return ""
    return meeting_id


def _reveal(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(serve())
