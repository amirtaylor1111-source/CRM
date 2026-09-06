"""A local HTTP server the widget talks to.

The window is HTML (in the always-on-top widget, or in Edge's app mode as
the fallback); this is the other half. Stdlib only, bound to loopback, one
small JSON API. The UI never touches files or audio — it asks this, and this
calls the same functions the CLI does, so the two can never disagree about
what "start" means.

While a call is recording, the Session also runs the live transcriber and
asks Claude Code, headlessly, for a brief every couple of minutes of speech.
At Stop it finishes the transcript and runs the write-up at once. The ask
box is a running Claude conversation per meeting. All of that goes through
`assistant.py`, which is the subscription, not an API.

Security posture: loopback only, a per-launch token in every request, and no
endpoint that takes a path from the client; meeting ids are whitelisted to
the shape the tool makes. The token is in the page, so another process on
this machine, as this user, could learn it. What that buys is what the user
already has: the files in this folder, and Claude Code turns on their plan
(a brief, an answer about a meeting, a write-up), throttled the same way. It
cannot start a recording past the consent gate, and it cannot read outside
the repo through Claude, which runs with --restricted.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from . import assistant, capture, hardware, live, log, store, uistate, watcher

_log = log.get("server")
UI_DIR = Path(__file__).resolve().parent / "ui"

RECORDER_START_SECONDS = 15   # how long the recorder gets to report in
BRIEF_AFTER_SECONDS = 120     # of new speech, before the next automatic brief
BRIEF_MIN_GAP_SECONDS = 30    # even by hand, no more often than this
BRIEF_BACKOFF_SECONDS = (120, 240, 480)   # after failures; then give up until Stop
CALENDAR_POLL_SECONDS = 60
SNAPSHOT_TTL_SECONDS = 3.0    # the parts of the state that read the disk
STALE_RECORDING_HOURS = 4     # an adopted recording older than this is probably forgotten


def _items(value: Any) -> list:
    """The list a panel expects, whatever Claude actually sent.

    The schema asks for a list, and the reply is validated against it, but
    `list()` of a string is that string's characters and `list()` of a dict
    is its keys. One wrong type would otherwise fill the panel with letters
    or raise inside the thread that owns the panel's state.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return []


def _process_alive(pid: Any) -> bool:
    """Is that process still running? Unknown pids count as alive.

    Used to tell a recording still in progress from a state file left behind
    by a reboot. `os.kill(pid, 0)` is not available on Windows, so ask the
    kernel through OpenProcess there.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True                      # written by an older version; trust it
    if pid <= 0:
        return True
    if sys.platform == "win32":
        import ctypes

        SYNCHRONIZE = 0x00100000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE | 0x0400, False, pid)   # + QUERY_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


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
        self.window: dict[str, Callable[[], None]] = {}   # set by widget.py

        self.live: live.LiveTranscriber | None = None
        self.live_error = ""
        self._recorder: subprocess.Popen | None = None   # this window's recorder
        self.brief: dict[str, Any] | None = None
        self.brief_state = "idle"       # idle | running | error
        self.brief_error = ""
        self.about = ""
        self.about_person = ""
        self.about_state = "idle"       # idle | running | done | error
        self.chat: list[dict[str, str]] = []
        self.chat_session = ""
        self.notes = ""
        self.notes_state = "idle"       # idle | running | done | error | login
        self.notes_error = ""
        self.login_needed = False
        self.turns = 0                  # headless Claude turns this meeting
        self.capture_hidden = False     # the widget sets this once the window is up
        self._brief_last = 0.0
        self._brief_failures = 0
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
            if not _process_alive(data.get("pid")):
                # The state file outlived its recorder: a reboot or a crash
                # mid-call. Adopting it would show a recording that no longer
                # runs, and refuse to start a new one.
                _log.info("ignoring a stale recording state in %s", latest.name)
                return
            self.meeting_dir = latest
            self.started_at = float(data.get("started_at") or time.time())
            self.state = uistate.RECORDING
            age_hours = (time.time() - self.started_at) / 3600
            if age_hours > STALE_RECORDING_HOURS:
                self.detail = f"This recording has been running for {age_hours:.0f} hours."
            _log.info("adopted in-progress recording: %s", latest.name)
            self.chat_session = _load_chat_session(latest.name)
            threading.Thread(target=self._begin_live, kwargs={"resume": True}, daemon=True).start()
            try:
                people = [p.name for p in store.load_meeting(latest).participants]
                self._begin_about(people)
            except Exception:
                _log.exception("about panel not restored")
        except Exception:
            _log.exception("adopt failed")

    # --- reads -------------------------------------------------------------

    def _disk_state(self) -> dict[str, Any]:
        """Calendar, recent meetings and whether Claude is installed: the
        parts of a poll that read the disk, cached for a few seconds because
        the widget polls from login to logout."""
        now = time.time()
        if self._cache and now - self._cache_at < SNAPSHOT_TTL_SECONDS:
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
            "claude_available": bool(assistant.available()),
        }
        self._cache_at = now
        return self._cache

    def invalidate(self) -> None:
        self._cache_at = 0.0

    def snapshot(self) -> dict[str, Any]:
        disk = self._disk_state()
        with self.lock:
            lt = self.live
            busy = self.state in (uistate.RECORDING, uistate.TRANSCRIBING, uistate.WRITING)
            return {
                "state": self.state,
                "elapsed": uistate.elapsed_text(time.time() - self.started_at)
                if self.state == uistate.RECORDING else "",
                "detail": self.detail,
                "meeting_id": self.meeting_dir.name if self.meeting_dir else "",
                "suggestion": disk["suggestion"],
                "upcoming": disk["upcoming"],
                "recent": disk["recent"],
                "disclosure": _disclosure(),
                "claude_available": disk["claude_available"],
                "claude": {"available": disk["claude_available"],
                           "login_needed": self.login_needed,
                           "turns": self.turns},
                "capture_hidden": self.capture_hidden,
                "poll_ms": 700 if busy or any(c["state"] == "running" for c in self.chat)
                or self.brief_state == "running" or self.about_state == "running" else 2500,
                "live": {"segments": lt.count() if lt else 0,
                         "seconds": round(lt.seconds(), 1) if lt else 0,
                         "error": self.live_error},
                "brief": self.brief,
                "brief_state": self.brief_state,
                "brief_error": self.brief_error,
                "about": self.about,
                "about_person": self.about_person,
                "about_state": self.about_state,
                "chat": list(self.chat),
                "notes": self.notes,
                "notes_state": self.notes_state,
                "notes_error": self.notes_error,
                "window": bool(self.window),
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
                recorder = subprocess.Popen(
                    [_console_python(), "-m", "notetaker.cli", "_record", str(self.meeting_dir)],
                    cwd=str(store.repo_root()), creationflags=_no_window(),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                return {"ok": False, "error": str(exc)}

            self.started_at = time.time()
            self.state = uistate.RECORDING
            self.detail = ""
            self._recorder = recorder
            self._clear_meeting_panels()
            self.invalidate()
            _log.info("start: %s", self.meeting_dir.name)

        # Confirm the recorder actually came up before reporting success. On
        # a loaded machine its imports alone can take several seconds.
        for _ in range(int(RECORDER_START_SECONDS * 4)):
            time.sleep(0.25)
            if capture.is_recording(self.meeting_dir):
                threading.Thread(target=self._begin_live, daemon=True).start()
                self._begin_about(participants)
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
        # A recorder that comes up after this would record with nobody
        # watching it; better none at all.
        self._release_recorder()
        with self.lock:
            self.state = uistate.ERROR
            self.detail = "The recorder did not start. Run Check setup."
        return {"ok": False, "error": self.detail}

    def _clear_meeting_panels(self) -> None:
        self._release_live()
        self.live_error = ""
        self.brief = None
        self.brief_state = "idle"
        self.brief_error = ""
        self.about = ""
        self.about_person = ""
        self.about_state = "idle"
        self.chat = []
        self.chat_session = ""
        self.notes = ""
        self.notes_state = "idle"
        self.notes_error = ""
        self._brief_last = 0.0
        self._brief_failures = 0
        self.turns = 0

    def stop(self) -> dict:
        with self.lock:
            if self.state != uistate.RECORDING:
                return {"ok": False, "error": "Nothing is recording."}
            self.state = uistate.TRANSCRIBING
            self.detail = "Stopping..."
        threading.Thread(target=self._finish, daemon=True).start()
        return {"ok": True}

    def _release_live(self) -> None:
        lt, self.live = self.live, None
        if lt is not None:
            try:
                lt.close(kill=True)
            except Exception:
                pass

    def _release_recorder(self) -> None:
        """Stop a recorder this window started but never got audio from.

        Stop can be pressed while the recorder is still opening its devices,
        before it has written a state file for stop_recording to find. Killing
        the process we started is the only way to get the microphone back.
        """
        proc, self._recorder = self._recorder, None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        except Exception:
            _log.exception("could not stop the recorder")

    def _finish(self):
        try:
            tracks = capture.stop_recording(self.meeting_dir)
            if not tracks:
                # Nothing was captured, so nothing asked the recorder to stop.
                self._release_recorder()
                self._release_live()
                self._set(uistate.ERROR, "No audio was captured — run Check setup")
                return
            self._recorder = None                 # it stops itself once asked
            store.finalize_meeting(self.meeting_dir, tracks=tracks)
            self._transcribe_final(tracks)

            meeting = store.load_meeting(self.meeting_dir)
            meeting.transcribed = True
            store.save_meeting(self.meeting_dir, meeting)
            for person in meeting.participants:
                store.link_contact(self.meeting_dir, person.name)
            store.rebuild_index()
            self.invalidate()
            _log.info("transcribed: %s", self.meeting_dir.name)
            self._write_notes()
        except Exception as exc:
            _log.exception("finish failed")
            self._release_recorder()
            self._release_live()          # or its worker outlives the window
            self._set(uistate.ERROR, str(exc)[:90])

    def _transcribe_final(self, tracks) -> None:
        """Finish the live transcript, or fall back to transcribing the files.

        Both happen in a worker process: the model must never load in this
        one, where it would freeze the API for the window.
        """
        lt = self.live
        if lt is not None and not self.live_error:
            try:
                self._set(uistate.TRANSCRIBING, "Finishing the transcript")
                count = lt.finish()
                _log.info("live transcript finished: %d segments", count)
                return
            except live.LiveError as exc:
                _log.warning("live transcript unusable, transcribing the files: %s", exc)
        elif lt is not None:
            lt.close(kill=True)
        seconds = sum(capture.audio_duration(Path(t)) for t in tracks if t.endswith(".wav"))
        choice = hardware.recommend()
        self._set(uistate.TRANSCRIBING,
                  f"Transcribing — {hardware.format_estimate(seconds, choice)}")
        worker = live.LiveProcess(self.meeting_dir, vocabulary=store.vocabulary())
        worker.transcribe_files()

    def _write_notes(self) -> None:
        """Run /notes headlessly and float with the result."""
        if not assistant.available():
            self.notes_state = "error"
            self.notes_error = assistant.MISSING_HINT
            self._set(uistate.DONE, "")
            return
        self.notes_state = "running"
        self._set(uistate.WRITING, "Writing up the notes")
        result = assistant.notes(self.meeting_dir.name)
        with self.lock:
            self._note_result(result)
            if result.ok:
                self.notes = _read_notes(self.meeting_dir)
                self.notes_state = "done" if self.notes else "error"
                self.notes_error = "" if self.notes else "Claude finished but wrote no notes.md"
            else:
                self.notes_state = "login" if result.error == "login" else "error"
                self.notes_error = result.hint
                self._note_failure(result)
        self.invalidate()
        self._set(uistate.DONE, "")
        _log.info("notes: %s", self.notes_state)

    def _note_failure(self, result) -> None:
        """Remember the one Claude failure that needs the user, not a retry."""
        if result.error == "login":
            self.login_needed = True

    def _note_result(self, result) -> None:
        """Every headless turn, whatever came back: counted; a success clears
        the login banner."""
        if result.error not in ("busy", "missing"):
            self.turns += 1
        if result.ok:
            self.login_needed = False

    # --- live transcription and briefs ---------------------------------------

    def _begin_live(self, resume: bool = False) -> None:
        """Start the live transcriber's worker; runs on its own thread, since
        the worker takes a while to load the model."""
        meeting_dir = self.meeting_dir
        try:
            lt = live.LiveProcess(meeting_dir, vocabulary=store.vocabulary())
            if not lt.open(resume=resume):
                self.live_error = lt.error or "the live transcriber did not start"
                _log.warning("live transcriber did not start: %s", self.live_error)
                return
        except Exception as exc:
            self.live_error = str(exc)
            _log.exception("live transcriber could not start")
            return
        with self.lock:
            if self.meeting_dir is not meeting_dir or self.state != uistate.RECORDING:
                lt.close()                         # the call ended while we loaded
                return
            self.live = lt
        threading.Thread(target=self._live_loop, daemon=True).start()

    def _live_loop(self) -> None:
        lt = self.live
        deadline = time.time() + live.INTERVAL
        while lt is not None and self.state == uistate.RECORDING and self.live is lt:
            while time.time() < deadline:
                if self.state != uistate.RECORDING or self.live is not lt:
                    return
                time.sleep(min(0.25, max(0.0, deadline - time.time())))
            deadline = time.time() + live.INTERVAL
            began = time.time()
            try:
                lt.tick()
                self.live_error = lt.error
            except Exception as exc:
                self.live_error = str(exc)
                _log.exception("live tick failed")
            took = time.time() - began
            if not lt.error and lt.backlog() > live.MAX_PASS_SECONDS:
                _log.info("live transcript %.0fs behind; catching up", lt.backlog())
                deadline = time.time()                # tick again at once
            elif took > live.INTERVAL / 2:        # back off on a slow machine
                _log.info("live pass took %.1fs; waiting longer", took)
                time.sleep(min(took, live.INTERVAL))
            if lt.new_speech_seconds() >= BRIEF_AFTER_SECONDS:
                self.refresh_brief(wait=False)

    def refresh_brief(self, wait: bool = True) -> dict:
        """Ask Claude for the mid-call brief, in a thread.

        Never more often than BRIEF_MIN_GAP_SECONDS, by hand or otherwise;
        after failures, automatic briefs back off and then stop until the
        next meeting, so a broken Claude does not burn the plan.
        """
        with self.lock:
            if self.meeting_dir is None or self.state not in (uistate.RECORDING, uistate.DONE):
                return {"ok": False, "error": "No meeting to brief on."}
            if self.brief_state == "running":
                return {"ok": False, "error": "A brief is already being written."}
            since = time.time() - self._brief_last
            if since < BRIEF_MIN_GAP_SECONDS:
                return {"ok": False, "error": f"Wait {int(BRIEF_MIN_GAP_SECONDS - since)} s."}
            if not wait and self._brief_failures:
                if self._brief_failures > len(BRIEF_BACKOFF_SECONDS):
                    return {"ok": False, "error": "Automatic briefs stopped after repeated failures."}
                if since < BRIEF_BACKOFF_SECONDS[self._brief_failures - 1]:
                    return {"ok": False, "error": "Backing off after a failure."}
            self.brief_state = "running"
            self.brief_error = ""
            self._brief_last = time.time()
            meeting_id = self.meeting_dir.name
            previous = dict(self.brief) if self.brief else None
            lt = self.live
        speech = lt.new_speech_seconds() if lt else 0.0

        def work():
            # Nothing outside this thread can clear brief_state, so an
            # exception here would leave the panel spinning and the Refresh
            # button disabled for the rest of the call.
            try:
                result = assistant.brief(meeting_id, previous=previous, wait=wait)
                with self.lock:
                    self._note_result(result)
                    if result.ok and isinstance(result.data, dict):
                        self.brief = {
                            "summary": str(result.data.get("summary") or ""),
                            "next_steps": _items(result.data.get("next_steps")),
                            "questions": _items(result.data.get("questions")),
                            "speech_seconds": round(speech, 1),
                            "generated_at": time.time(),
                            "as_of": uistate.elapsed_text(time.time() - self.started_at)
                            if self.started_at else "",
                        }
                        self.brief_state = "idle"
                        self._brief_failures = 0
                        if lt:
                            lt.reset_speech()      # local; the worker learns on the next tick
                    elif result.error == "busy":
                        self.brief_state = "idle"          # try again next tick
                        self._brief_last = 0.0
                    else:
                        self.brief_state = "error"
                        self.brief_error = (result.hint if not result.ok
                                            else "Claude returned no brief.")
                        self._brief_failures += 1
                        self._note_failure(result)
            except Exception:
                _log.exception("brief failed")
                with self.lock:
                    self.brief_state = "error"
                    self.brief_error = "The brief could not be written."
                    self._brief_failures += 1
            _log.info("brief: %s (%.0fs of speech)", self.brief_state, speech)

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def _begin_about(self, participants: list[str]) -> None:
        """The pre-call briefing on the first participant the CRM knows."""
        person = next((p for p in participants if store.load_contact(p)), "")
        if not person or not assistant.available():
            return
        with self.lock:
            self.about_person = person
            self.about_state = "running"

        def work():
            try:
                result = assistant.prep(person)
                with self.lock:
                    self._note_result(result)
                    if result.ok:
                        self.about = result.text
                        self.about_state = "done"
                    else:
                        self.about_state = "error"
                        self.about = result.hint
                        self._note_failure(result)
            except Exception:
                _log.exception("about panel failed")
                with self.lock:
                    self.about_state = "error"
                    self.about = "Could not read their history."

        threading.Thread(target=work, daemon=True).start()

    def ask(self, question: str) -> dict:
        question = (question or "").strip()
        if not question:
            return {"ok": False, "error": "Ask something."}
        with self.lock:
            if self.meeting_dir is None:
                return {"ok": False, "error": "Start or pick a meeting first."}
            if any(c["state"] == "running" for c in self.chat):
                return {"ok": False, "error": "Still answering the last one."}
            entry = {"q": question, "a": "", "state": "running"}
            self.chat.append(entry)
            meeting_id = self.meeting_dir.name
            session_id = self.chat_session

        def work():
            # An entry stuck at "running" refuses every later question, so
            # this thread must always finish it.
            try:
                result = assistant.ask(meeting_id, question, session_id=session_id)
                with self.lock:
                    self._note_result(result)
                    if result.session_id:          # even a failed turn has one now
                        self.chat_session = result.session_id
                        _save_chat_session(meeting_id, result.session_id)
                    if result.ok:
                        entry["a"] = result.text
                        entry["state"] = "done"
                    else:
                        entry["a"] = result.hint
                        entry["state"] = "error"
                        self._note_failure(result)
            except Exception:
                _log.exception("ask failed")
                with self.lock:
                    entry["a"] = "Claude could not answer that."
                    entry["state"] = "error"

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    # --- misc --------------------------------------------------------------

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
                self._clear_meeting_panels()
                self.invalidate()
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

    def show_meeting(self, meeting_id: str) -> dict:
        """Float with an earlier meeting's notes, for the ask box and reading."""
        safe = _safe_id(meeting_id)
        directory = store.meetings_dir() / safe if safe else None
        if directory is None or not (directory / "meeting.json").exists():
            return {"ok": False, "error": "No such meeting."}
        with self.lock:
            if self.state in (uistate.RECORDING, uistate.TRANSCRIBING, uistate.WRITING):
                return {"ok": False, "error": "A meeting is in progress."}
            self.meeting_dir = directory
            self.started_at = 0.0
            self._clear_meeting_panels()
            self.notes = _read_notes(directory)
            self.notes_state = "done" if self.notes else "idle"
            self.chat_session = _load_chat_session(directory.name)
            self.state = uistate.DONE
            self.detail = ""
        return {"ok": True}

    def window_action(self, action: str) -> dict:
        hook = self.window.get(action)
        if hook is None:
            return {"ok": False, "error": "No window to control."}
        if action == "quit" and self.state in (uistate.RECORDING, uistate.TRANSCRIBING,
                                                uistate.WRITING):
            # The recorder would carry on with no indicator anywhere.
            return {"ok": False, "error": "Stop the recording first."}
        try:
            hook()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}


def _read_notes(directory: Path) -> str:
    try:
        return (directory / "notes.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def _chat_sessions_path() -> Path:
    return log.log_dir() / "ask-sessions.json"


def _load_chat_session(meeting_id: str) -> str:
    """The Claude conversation for a meeting, kept outside the repo."""
    try:
        return str(json.loads(_chat_sessions_path().read_text(encoding="utf-8")).get(meeting_id, ""))
    except (OSError, ValueError, AttributeError):
        return ""


def _save_chat_session(meeting_id: str, session_id: str) -> None:
    try:
        path = _chat_sessions_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data[meeting_id] = session_id
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(sorted(data.items())[-200:])), encoding="utf-8")
    except OSError:
        pass


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

    def _host_ok(self) -> bool:
        """Only answer requests addressed to loopback by name or number.

        The page carries the token, and the page is served before any token
        check, so a site the user visits could otherwise point a hostname of
        its own at 127.0.0.1, fetch "/" same-origin and read the token out of
        it. Binding to loopback does not stop that; checking Host does.
        """
        host = (self.headers.get("Host") or "").strip()
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden"})
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
        # Read the body before answering, even when the answer is a refusal.
        # Replying to a request whose body is still in the socket makes
        # Windows reset the connection, and the client sees the reset instead
        # of the 403.
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        if not self._host_ok() or not self._authorised():
            return self._json(403, {"error": "forbidden"})
        try:
            payload = json.loads(raw or b"{}")
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
        if path == "/api/brief":
            return self._json(200, s.refresh_brief(wait=True))
        if path == "/api/ask":
            return self._json(200, s.ask(str(payload.get("question", ""))))
        if path == "/api/show":
            return self._json(200, s.show_meeting(str(payload.get("meeting_id", ""))))
        if path == "/api/window":
            return self._json(200, s.window_action(str(payload.get("action", ""))))
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
        # The port is ephemeral, so something unrelated can end up on it after
        # a hard kill. Check the process that wrote the lock is still there,
        # or the shortcut silently does nothing.
        if "pid" in data and not _process_alive(data.get("pid")):
            return ""
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return f"http://127.0.0.1:{port}/"
    except Exception:
        return ""


def _watchdog(httpd, session: Session, started: float) -> None:
    """Shut the server down once the window has gone.

    Exempts transcription and the write-up, which run inside this process
    and must finish. A recording is safe to leave: it is a separate process,
    and the next launch adopts it. The widget owns its own lifetime, so it
    disables this by never installing it.
    """
    while True:
        time.sleep(2)
        now = time.time()
        if session.state in (uistate.TRANSCRIBING, uistate.WRITING):
            continue
        seen = session.last_seen or started
        limit = STARTUP_GRACE_SECONDS if not session.last_seen else IDLE_EXIT_SECONDS
        if now - seen > limit:
            _log.info("window gone; exiting")
            httpd.shutdown()
            return


def _calendar_loop(session: Session) -> None:
    """Offer to record when a meeting is due, by expanding the widget."""
    seen = watcher._load_seen()
    while True:
        time.sleep(CALENDAR_POLL_SECONDS)
        try:
            if session.state != uistate.IDLE:
                continue
            event = watcher.due_now(seen)
            if event is None:
                continue
            seen.add(watcher.event_key(event))
            watcher._save_seen(seen)
            _log.info("calendar: offering %s", event.get("subject"))
            session.window_action("expand")
        except Exception:
            _log.exception("calendar poll failed")


def make_server(port: int = 0) -> tuple[ThreadingHTTPServer, str, Session]:
    """The server, bound and ready; the caller decides how to run it."""
    session = Session()
    Handler.session = session
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    try:
        _lock_path().parent.mkdir(parents=True, exist_ok=True)
        _lock_path().write_text(json.dumps({"port": httpd.server_address[1], "pid": os.getpid()}),
                                encoding="utf-8")
    except OSError:
        pass
    return httpd, url, session


def release_lock() -> None:
    try:
        _lock_path().unlink(missing_ok=True)
    except OSError:
        pass


def serve(open_browser: bool = True, port: int = 0, watchdog: bool = True,
          calendar: bool = False) -> int:
    """The Edge-window way to run the app; the widget uses make_server().

    The widget's fallback runs this with the watchdog off and the calendar
    loop on, so a machine without WebView2 still gets one process from login
    that offers to record when a meeting is due.
    """
    log.setup()

    existing = _running_instance()
    if existing and open_browser:
        _log.info("already running at %s; opening a window to it", existing)
        _open_window(existing)
        return 0

    httpd, url, session = make_server(port)
    _log.info("serving %s", url)

    if open_browser:
        threading.Thread(target=_open_window, args=(url,), daemon=True).start()
    if watchdog:
        threading.Thread(target=_watchdog, args=(httpd, session, time.time()), daemon=True).start()
    if calendar:
        session.window = {"expand": lambda: _open_window(url)}   # "expand" reopens the page
        threading.Thread(target=_calendar_loop, args=(session,), daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        release_lock()
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


_ID_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def _safe_id(meeting_id: str) -> str:
    """A meeting id is a directory name the tool made: date, slug, suffix.

    Anything else is refused, so an id can never carry a path, a drive
    letter, or a character that means something to cmd.exe on the way to
    the write-up launcher.
    """
    meeting_id = (meeting_id or "").strip()
    if not _ID_SHAPE.match(meeting_id) or ".." in meeting_id:
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
