"""The Session during and after a call: live transcript, briefs, ask, notes.

Real HTTP against the real handler, with the recorder, the live transcriber
and Claude replaced by fakes that behave the way the real ones report.
"""

import http.client
import json
import os
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from notetaker import assistant, capture, live, server, store, uistate


class FakeLive:
    """What the Session sees of a LiveProcess."""

    instances = []
    open_result = True

    def __init__(self, meeting_dir, vocabulary=(), threads=None):
        self.meeting_dir = Path(meeting_dir)
        self.ticks = 0
        self.error = ""
        self.speech = 0.0
        self.finish_result = 7
        self.finish_raises = False
        self.reset_calls = 0
        self.closed = False
        self.opened_with = None
        self.files_transcribed = False
        self.backlog_value = 0.0
        self.tick_fails = False
        FakeLive.instances.append(self)

    def open(self, resume=False):
        self.opened_with = resume
        return FakeLive.open_result

    def close(self, kill=False):
        self.closed = True

    def count(self):
        return self.ticks

    def transcribe_files(self):
        self.files_transcribed = True
        (self.meeting_dir / "transcript.md").write_text("---\nlive: False\n---\n", encoding="utf-8")

    def seconds(self):
        return self.ticks * 30.0

    def tick(self, final=False):
        self.ticks += 1
        if self.tick_fails:
            # What a LiveProcess does once its worker has gone: it answers
            # at once, records the error, and adds nothing.
            self.error = "the live transcriber process is not running"
            return 0
        return 1

    def new_speech_seconds(self):
        return self.speech

    def backlog(self):
        return self.backlog_value

    def reset_speech(self):
        self.reset_calls += 1
        self.speech = 0.0

    def finish(self):
        if self.finish_raises:
            raise live.LiveError("the model fell over")
        (self.meeting_dir / "transcript.md").write_text("---\nlive: False\n---\n", encoding="utf-8")
        return self.finish_result


class FakeClaude:
    """Scripted answers for prep / brief / ask / notes, and a call log."""

    def __init__(self):
        self.calls = []
        self.brief_data = {"summary": "so far", "next_steps": [{"owner": "me", "text": "send it"}],
                           "questions": ["When?"]}
        self.notes_error = ""
        self.ask_error = ""

    def available(self):
        return "claude.cmd"

    def prep(self, person, **kw):
        self.calls.append(("prep", person))
        return assistant.Result(True, text=f"# About {person}\n\nWhere we left off.")

    def brief(self, meeting_id, **kw):
        self.calls.append(("brief", meeting_id, kw.get("wait")))
        return assistant.Result(True, text="{}", data=self.brief_data, session_id="b1")

    def ask(self, meeting_id, question, session_id="", **kw):
        self.calls.append(("ask", meeting_id, question, session_id))
        if self.ask_error:
            return assistant.Result(False, error=self.ask_error, detail="nope")
        return assistant.Result(True, text=f"Answer to: {question}", session_id="conv-9")

    def notes(self, meeting_id, **kw):
        self.calls.append(("notes", meeting_id))
        if self.notes_error:
            return assistant.Result(False, error=self.notes_error, detail="nope")
        (store.meetings_dir() / meeting_id / "notes.md").write_text(
            "# Notes\n\n## Action items\n\n- [ ] **@me** — send it\n", encoding="utf-8")
        return assistant.Result(True, text="Wrote the notes.", session_id="n1")


@pytest.fixture
def widget(crm, monkeypatch):
    monkeypatch.setattr(store, "repo_root", lambda: crm)
    (crm / "contacts" / "monty-smythe.md").write_text(
        "---\nname: Monty Smythe\ncompany: Open\n---\n\nLikes short calls.\n", encoding="utf-8")

    recorders = []

    class FakePopen:
        def __init__(self, *a, **k):
            meeting_dir = Path(a[0][-1])
            (meeting_dir / capture.STATE_FILE).write_text(
                json.dumps({"pid": os.getpid(), "started_at": time.time(), "tracks": []}))
            self.alive = True
            recorders.append(self)

        def poll(self):
            return None if self.alive else 0

        def kill(self):
            self.alive = False

        def wait(self, timeout=None):
            self.alive = False
            return 0

    def fake_stop(meeting_dir, timeout=30.0):
        out = []
        for name in ("mic.wav", "system.wav"):
            path = Path(meeting_dir) / name
            path.write_bytes(b"RIFF" + b"\0" * 60)
            out.append(str(path))
        return out

    monkeypatch.setattr(server.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(server.capture, "stop_recording", fake_stop)
    monkeypatch.setattr(server.live, "INTERVAL", 0.1)
    FakeLive.instances.clear()
    FakeLive.open_result = True
    monkeypatch.setattr(server.live, "LiveProcess", FakeLive)
    claude = FakeClaude()
    for name in ("available", "prep", "brief", "ask", "notes"):
        monkeypatch.setattr(server.assistant, name, getattr(claude, name))

    session = server.Session()
    server.Handler.session = session
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"port": httpd.server_address[1], "token": session.token, "session": session,
           "claude": claude, "crm": crm, "recorders": recorders}
    session.state = uistate.ERROR            # stop any live loop
    httpd.shutdown()
    httpd.server_close()


def call(w, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", w["port"], timeout=5)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Content-Type": "application/json", "X-Token": w["token"]})
    resp = conn.getresponse()
    data = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, data


def wait_for(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def start(w, people="Monty Smythe"):
    status, data = call(w, "POST", "/api/start",
                        {"title": "Catchup", "participants": people, "consent": True, "solo": False})
    assert data["ok"], data
    return data["meeting_id"]


class TestDuringTheCall:
    def test_start_begins_live_transcription_and_the_about_panel(self, widget):
        start(widget)
        assert wait_for(lambda: FakeLive.instances and FakeLive.instances[0].ticks >= 1)
        assert FakeLive.instances[0].opened_with is False
        assert wait_for(lambda: widget["session"].about_state == "done")
        _, state = call(widget, "GET", "/api/state")
        assert state["live"]["segments"] >= 1
        assert state["about_person"] == "Monty Smythe"
        assert state["about"].startswith("# About Monty Smythe")
        assert ("prep", "Monty Smythe") in widget["claude"].calls

    def test_unknown_person_gets_no_prep(self, widget):
        start(widget, people="Nobody Known")
        time.sleep(0.3)
        assert not any(c[0] == "prep" for c in widget["claude"].calls)
        assert widget["session"].about_state == "idle"

    def test_a_brief_is_written_after_two_minutes_of_speech(self, widget):
        start(widget)
        assert wait_for(lambda: FakeLive.instances)
        lt = FakeLive.instances[0]
        lt.speech = server.BRIEF_AFTER_SECONDS + 5
        assert wait_for(lambda: widget["session"].brief is not None)
        _, state = call(widget, "GET", "/api/state")
        assert state["brief"]["questions"] == ["When?"]
        assert state["brief"]["next_steps"][0]["text"] == "send it"
        assert state["brief"]["as_of"]
        assert lt.reset_calls == 1
        briefs = [c for c in widget["claude"].calls if c[0] == "brief"]
        assert briefs and briefs[0][2] is False                  # automatic: never waits

    def test_no_brief_without_speech(self, widget):
        start(widget)
        time.sleep(0.5)
        assert widget["session"].brief is None
        assert not any(c[0] == "brief" for c in widget["claude"].calls)

    def test_the_refresh_button_waits_its_turn(self, widget):
        start(widget)
        _, data = call(widget, "POST", "/api/brief")
        assert data["ok"]
        assert wait_for(lambda: widget["session"].brief is not None)
        assert ("brief", widget["session"].meeting_dir.name, True) in widget["claude"].calls

    def test_ask_is_a_running_conversation(self, widget):
        start(widget)
        _, data = call(widget, "POST", "/api/ask", {"question": "What did they promise?"})
        assert data["ok"]
        assert wait_for(lambda: widget["session"].chat and widget["session"].chat[0]["state"] == "done")
        call(widget, "POST", "/api/ask", {"question": "And when?"})
        assert wait_for(lambda: len(widget["session"].chat) == 2
                        and widget["session"].chat[1]["state"] == "done")
        asks = [c for c in widget["claude"].calls if c[0] == "ask"]
        assert asks[0][3] == "" and asks[1][3] == "conv-9"        # second call resumes
        _, state = call(widget, "GET", "/api/state")
        assert state["chat"][1]["a"] == "Answer to: And when?"

    def test_an_empty_question_is_refused(self, widget):
        start(widget)
        _, data = call(widget, "POST", "/api/ask", {"question": "  "})
        assert not data["ok"]


class TestStop:
    def test_stop_finishes_live_and_writes_the_notes(self, widget):
        mid = start(widget)
        wait_for(lambda: FakeLive.instances and FakeLive.instances[0].ticks >= 1)
        _, data = call(widget, "POST", "/api/stop")
        assert data["ok"]
        assert wait_for(lambda: widget["session"].state == uistate.DONE)
        s = widget["session"]
        assert s.notes_state == "done"
        assert "send it" in s.notes
        assert ("notes", mid) in widget["claude"].calls
        meeting = store.load_meeting(widget["crm"] / "meetings" / mid)
        assert meeting.transcribed
        assert (widget["crm"] / "contacts" / "monty-smythe.md").read_text(encoding="utf-8").count(mid) == 1

    def test_writing_state_is_visible_while_claude_works(self, widget, monkeypatch):
        seen = []
        real = widget["claude"].notes

        def slow(meeting_id, **kw):
            seen.append(widget["session"].state)
            time.sleep(0.2)
            return real(meeting_id, **kw)

        monkeypatch.setattr(server.assistant, "notes", slow)
        start(widget)
        call(widget, "POST", "/api/stop")
        assert wait_for(lambda: widget["session"].state == uistate.DONE)
        assert seen == [uistate.WRITING]

    def test_live_failure_falls_back_to_the_full_transcription(self, widget, monkeypatch):
        monkeypatch.setattr(server.hardware, "recommend", lambda *a, **k: {"model": "x", "realtime": 10})
        monkeypatch.setattr(server.hardware, "format_estimate", lambda *a, **k: "a moment")
        start(widget)
        assert wait_for(lambda: FakeLive.instances and widget["session"].live is not None)
        FakeLive.instances[0].finish_raises = True
        call(widget, "POST", "/api/stop")
        assert wait_for(lambda: widget["session"].state == uistate.DONE)
        assert any(f.files_transcribed for f in FakeLive.instances)   # a fresh worker did the files

    def test_a_worker_that_never_opens_is_reported_and_stop_still_works(self, widget, monkeypatch):
        monkeypatch.setattr(server.hardware, "recommend", lambda *a, **k: {"model": "x", "realtime": 10})
        monkeypatch.setattr(server.hardware, "format_estimate", lambda *a, **k: "a moment")
        FakeLive.open_result = False
        start(widget)
        assert wait_for(lambda: widget["session"].live_error != "")
        _, state = call(widget, "GET", "/api/state")
        assert state["live"]["error"]
        FakeLive.open_result = True
        call(widget, "POST", "/api/stop")
        assert wait_for(lambda: widget["session"].state == uistate.DONE)
        assert any(f.files_transcribed for f in FakeLive.instances)

    def test_missing_login_is_surfaced_not_fatal(self, widget):
        widget["claude"].notes_error = "login"
        start(widget)
        call(widget, "POST", "/api/stop")
        assert wait_for(lambda: widget["session"].state == uistate.DONE)
        _, state = call(widget, "GET", "/api/state")
        assert state["notes_state"] == "login"
        assert state["claude"]["login_needed"] is True
        assert "/login" in state["notes_error"]
        assert "billing" not in state["claude"]

    def test_turns_are_counted_and_a_success_clears_the_login_banner(self, widget):
        widget["claude"].notes_error = "login"
        start(widget)
        call(widget, "POST", "/api/stop")
        assert wait_for(lambda: widget["session"].state == uistate.DONE)
        assert widget["session"].login_needed is True
        turns_before = widget["session"].turns
        assert turns_before >= 2                                 # prep and notes at least
        call(widget, "POST", "/api/brief")
        assert wait_for(lambda: widget["session"].brief is not None)
        assert widget["session"].login_needed is False           # a success clears it
        assert widget["session"].turns == turns_before + 1
        assert widget["session"].brief["speech_seconds"] >= 0

    def test_a_failed_ask_still_keeps_the_conversation_id(self, widget):
        widget["claude"].ask_error = "failed"
        start(widget)
        call(widget, "POST", "/api/ask", {"question": "q"})
        assert wait_for(lambda: widget["session"].chat and widget["session"].chat[0]["state"] == "error")
        assert widget["session"].chat_session == ""             # the fake gives none on error
        widget["claude"].ask_error = ""
        call(widget, "POST", "/api/ask", {"question": "again"})
        assert wait_for(lambda: len(widget["session"].chat) == 2
                        and widget["session"].chat[1]["state"] == "done")
        assert widget["session"].chat_session == "conv-9"

    def test_reset_clears_the_panels(self, widget):
        start(widget)
        call(widget, "POST", "/api/stop")
        assert wait_for(lambda: widget["session"].state == uistate.DONE)
        call(widget, "POST", "/api/reset")
        _, state = call(widget, "GET", "/api/state")
        assert state["state"] == "idle" and state["notes"] == "" and state["chat"] == []
        assert state["brief"] is None and state["about"] == ""
        assert state["claude"]["turns"] == 0


class TestWhenThingsGoWrong:
    """The call is the one place nothing may spin, hang or leak."""

    def test_a_dead_worker_does_not_spin_the_live_loop(self, widget):
        """The catch-up branch must not fire on a stale backlog reading.

        A tick that fails returns at once, so a loop that then decides to
        tick again "because the backlog is high" burns a core for the rest
        of the call and fills the log.
        """
        start(widget)
        assert wait_for(lambda: FakeLive.instances)
        lt = FakeLive.instances[0]
        lt.backlog_value = 300.0            # far past MAX_PASS_SECONDS
        lt.tick_fails = True
        assert wait_for(lambda: lt.error != "")
        before = lt.ticks
        time.sleep(0.6)                     # six live.INTERVALs of 0.1 s
        assert lt.ticks - before < 20, f"{lt.ticks - before} ticks in 0.6 s"

    def test_catch_up_still_happens_when_the_worker_is_healthy(self, widget):
        start(widget)
        assert wait_for(lambda: FakeLive.instances)
        lt = FakeLive.instances[0]
        lt.backlog_value = 300.0
        before = lt.ticks
        assert wait_for(lambda: lt.ticks - before > 8, timeout=2.0)

    def test_stop_with_no_audio_kills_the_recorder_and_the_worker(self, widget, monkeypatch):
        """Stop can land before the recorder has opened its devices.

        Nothing else stops that process, so the microphone would stay open
        until the user found it in Task Manager.
        """
        monkeypatch.setattr(server.capture, "stop_recording", lambda d, timeout=30.0: [])
        start(widget)
        assert wait_for(lambda: FakeLive.instances and widget["session"].live is not None)
        call(widget, "POST", "/api/stop")
        assert wait_for(lambda: widget["session"].state == uistate.ERROR)
        assert widget["recorders"] and not widget["recorders"][-1].alive
        assert FakeLive.instances[0].closed
        assert widget["session"].live is None

    def test_a_failed_finish_releases_the_worker(self, widget, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("disk full")

        monkeypatch.setattr(server.store, "finalize_meeting", boom)
        start(widget)
        assert wait_for(lambda: FakeLive.instances and widget["session"].live is not None)
        call(widget, "POST", "/api/stop")
        assert wait_for(lambda: widget["session"].state == uistate.ERROR)
        assert FakeLive.instances[0].closed
        assert widget["session"].live is None

    def test_a_brief_of_the_wrong_shape_does_not_fill_the_panel_with_letters(self, widget):
        widget["claude"].brief_data = {"summary": "so far", "next_steps": "send the proposal",
                                       "questions": "When?"}
        start(widget)
        assert wait_for(lambda: FakeLive.instances)
        FakeLive.instances[0].speech = server.BRIEF_AFTER_SECONDS + 5
        assert wait_for(lambda: widget["session"].brief is not None)
        brief = widget["session"].brief
        assert brief["next_steps"] == ["send the proposal"]
        assert brief["questions"] == ["When?"]

    def test_a_brief_that_raises_leaves_the_panel_usable(self, widget, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("claude fell over")

        monkeypatch.setattr(server.assistant, "brief", boom)
        start(widget)
        call(widget, "POST", "/api/brief")
        assert wait_for(lambda: widget["session"].brief_state == "error")
        assert widget["session"].brief_error
        _, state = call(widget, "GET", "/api/state")
        assert state["brief_state"] == "error"          # not stuck at "running"

    def test_an_ask_that_raises_finishes_its_entry(self, widget, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("claude fell over")

        monkeypatch.setattr(server.assistant, "ask", boom)
        start(widget)
        call(widget, "POST", "/api/ask", {"question": "What did they promise?"})
        assert wait_for(lambda: widget["session"].chat and
                        widget["session"].chat[0]["state"] == "error")
        _, data = call(widget, "POST", "/api/ask", {"question": "And when?"})
        assert data["ok"]                               # the box still takes questions

    def test_an_about_panel_that_raises_lands_in_error(self, widget, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("claude fell over")

        monkeypatch.setattr(server.assistant, "prep", boom)
        start(widget)
        assert wait_for(lambda: widget["session"].about_state == "error")


class TestEarlierMeetings:
    def test_show_loads_an_earlier_meetings_notes(self, widget):
        d = store.create_meeting("Old one", ["Monty Smythe"])
        (d / "notes.md").write_text("# Old one\n\nDone.\n", encoding="utf-8")
        _, data = call(widget, "POST", "/api/show", {"meeting_id": d.name})
        assert data["ok"]
        _, state = call(widget, "GET", "/api/state")
        assert state["state"] == "done" and state["notes"].startswith("# Old one")
        assert state["meeting_id"] == d.name
        call(widget, "POST", "/api/brief")
        assert wait_for(lambda: widget["session"].brief is not None)
        assert widget["session"].brief["as_of"] == ""            # no live clock to stamp

    def test_show_refuses_a_hostile_id_and_a_missing_one(self, widget):
        for bad in ("../secrets", "nope"):
            _, data = call(widget, "POST", "/api/show", {"meeting_id": bad})
            assert not data["ok"]

    def test_show_is_refused_during_a_call(self, widget):
        d = store.create_meeting("Old one", [])
        start(widget)
        _, data = call(widget, "POST", "/api/show", {"meeting_id": d.name})
        assert not data["ok"]


class TestWindow:
    def test_quit_is_refused_while_a_meeting_is_in_progress(self, widget):
        quits = []
        widget["session"].window = {"quit": lambda: quits.append(1)}
        start(widget)
        _, data = call(widget, "POST", "/api/window", {"action": "quit"})
        assert not data["ok"] and "Stop" in data["error"] and quits == []
        widget["session"].state = uistate.IDLE
        _, data = call(widget, "POST", "/api/window", {"action": "quit"})
        assert data["ok"] and quits == [1]

    def test_no_brief_once_stop_has_begun(self, widget):
        start(widget)
        widget["session"].state = uistate.TRANSCRIBING
        _, data = call(widget, "POST", "/api/brief")
        assert not data["ok"]
        widget["session"].state = uistate.WRITING
        _, data = call(widget, "POST", "/api/brief")
        assert not data["ok"]

    def test_window_actions_reach_the_hooks(self, widget):
        done = []
        widget["session"].window = {"expand": lambda: done.append("expand")}
        _, data = call(widget, "POST", "/api/window", {"action": "expand"})
        assert data["ok"] and done == ["expand"]
        _, data = call(widget, "POST", "/api/window", {"action": "quit"})
        assert not data["ok"]

    def test_state_says_whether_there_is_a_window(self, widget):
        _, state = call(widget, "GET", "/api/state")
        assert state["window"] is False
        widget["session"].window = {"collapse": lambda: None}
        _, state = call(widget, "GET", "/api/state")
        assert state["window"] is True
