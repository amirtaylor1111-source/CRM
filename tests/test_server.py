"""The local API the desktop window talks to, driven over real HTTP.

A real ThreadingHTTPServer on a random loopback port, with the recorder
subprocess and transcription patched out. Proves the token gate, the
consent gate, the state machine, and that a hostile meeting_id cannot
escape the meetings directory.
"""

import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from notetaker import capture, server, store, uistate


@pytest.fixture
def live(crm, monkeypatch):
    monkeypatch.setattr(store, "repo_root", lambda: crm)
    # No real recorder subprocess, no real audio.
    started = {}

    class FakePopen:
        def __init__(self, *a, **k):
            started["cmd"] = a[0]
            # Simulate the child writing its state file so is_recording() is True.
            meeting_dir = a[0][-1]
            (__import__("pathlib").Path(meeting_dir) / capture.STATE_FILE).write_text(
                json.dumps({"pid": 4242, "started_at": time.time(), "tracks": []}))

    monkeypatch.setattr(server.subprocess, "Popen", FakePopen)

    session = server.Session()
    server.Handler.session = session
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield {"port": httpd.server_address[1], "token": session.token,
           "session": session, "started": started, "crm": crm}
    httpd.shutdown()
    httpd.server_close()


def call(live, method, path, body=None, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", live["port"], timeout=5)
    headers = {"Content-Type": "application/json"}
    headers["X-Token"] = live["token"] if token is None else token
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, data


class TestAuth:
    def test_index_serves_html_with_token_injected(self, live):
        conn = http.client.HTTPConnection("127.0.0.1", live["port"], timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        html = resp.read().decode()
        assert resp.status == 200
        assert live["token"] in html
        assert "__TOKEN__" not in html

    def test_api_refuses_a_missing_token(self, live):
        status, _ = call(live, "GET", "/api/state", token="")
        assert status == 403

    def test_api_refuses_a_wrong_token(self, live):
        status, _ = call(live, "POST", "/api/start", {"title": "x"}, token="nope")
        assert status == 403


class TestStateMachine:
    def test_initial_state_is_idle_with_disclosure(self, live):
        status, data = call(live, "GET", "/api/state")
        assert status == 200
        assert data["state"] == uistate.IDLE
        assert "recording" in data["disclosure"].lower()

    def test_start_without_consent_is_refused(self, live):
        _, data = call(live, "POST", "/api/start", {"title": "Call", "consent": False, "solo": False})
        assert data["ok"] is False
        assert "told them" in data["error"]
        assert live["session"].state == uistate.IDLE

    def test_start_with_consent_records_it_and_spawns_recorder(self, live):
        _, data = call(live, "POST", "/api/start",
                       {"title": "Acme call", "participants": "Jane Doe, Bob",
                        "consent": True, "solo": False})
        assert data["ok"] is True, data
        assert "_record" in live["started"]["cmd"]
        meeting = store.load_meeting(live["session"].meeting_dir)
        assert meeting.consent_obtained is True
        assert [p.name for p in meeting.participants] == ["Jane Doe", "Bob"]
        _, state = call(live, "GET", "/api/state")
        assert state["state"] == uistate.RECORDING
        assert state["elapsed"]

    def test_solo_bypasses_consent_but_records_that_honestly(self, live):
        _, data = call(live, "POST", "/api/start", {"title": "Notes to self", "solo": True})
        assert data["ok"] is True
        meeting = store.load_meeting(live["session"].meeting_dir)
        assert meeting.consent_obtained is False
        assert "solo" in meeting.consent_note

    def test_stop_when_idle_is_refused(self, live):
        _, data = call(live, "POST", "/api/stop", {})
        assert data["ok"] is False

    def test_reset_only_from_terminal_states(self, live):
        live["session"].state = uistate.RECORDING
        call(live, "POST", "/api/reset", {})
        assert live["session"].state == uistate.RECORDING
        live["session"].state = uistate.DONE
        call(live, "POST", "/api/reset", {})
        assert live["session"].state == uistate.IDLE

    def test_empty_title_gets_a_sensible_default(self, live):
        call(live, "POST", "/api/start", {"title": "  ", "participants": "Monty Smythe", "consent": True})
        assert store.load_meeting(live["session"].meeting_dir).title == "Call with Monty Smythe"


class TestSafety:
    @pytest.mark.parametrize("bad", ["../../etc", "..\\..\\x", "a/b", ""])
    def test_meeting_id_cannot_traverse(self, bad):
        assert server._safe_id(bad) == ""

    def test_open_with_hostile_id_falls_back_to_root(self, live, monkeypatch):
        revealed = []
        monkeypatch.setattr(server, "_reveal", lambda p: revealed.append(p))
        call(live, "POST", "/api/open", {"meeting_id": "../../../etc"})
        assert revealed == [live["crm"]]

    def test_writeup_without_claude_returns_the_command_to_paste(self, live, monkeypatch):
        monkeypatch.setattr(server, "_which", lambda n: None)
        live["session"].meeting_dir = store.create_meeting("X", root=live["crm"])
        _, data = call(live, "POST", "/api/writeup", {})
        assert data["ok"] is False
        assert data["command"].startswith("/notes ")

    def test_unknown_route_is_404_not_a_crash(self, live):
        status, _ = call(live, "GET", "/api/nope")
        assert status == 404
        status, _ = call(live, "POST", "/api/nope", {})
        assert status == 404


class TestResilience:
    def test_reopening_adopts_a_recording_in_progress(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        d = store.create_meeting("Live call", root=crm)
        (d / capture.STATE_FILE).write_text(json.dumps(
            {"pid": 1, "started_at": time.time() - 300, "tracks": []}))
        s = server.Session()
        assert s.state == uistate.RECORDING
        assert s.meeting_dir == d
        assert 295 <= time.time() - s.started_at <= 305

    def test_a_finished_recording_is_not_adopted(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        d = store.create_meeting("Old call", root=crm)
        (d / capture.STATE_FILE).write_text(json.dumps(
            {"pid": 1, "started_at": time.time() - 900, "ended_at": time.time() - 300}))
        assert server.Session().state == uistate.IDLE

    def test_no_meetings_at_all_is_idle(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        assert server.Session().state == uistate.IDLE

    def test_watchdog_exits_when_the_window_stops_polling(self, monkeypatch):
        class FakeHttpd:
            def __init__(self): self.down = False
            def shutdown(self): self.down = True
        monkeypatch.setattr(server, "IDLE_EXIT_SECONDS", 0.05)
        monkeypatch.setattr(server.time, "sleep", lambda s: None)
        s = server.Session.__new__(server.Session)
        s.state = uistate.IDLE; s.last_seen = time.time() - 1
        httpd = FakeHttpd()
        server._watchdog(httpd, s, time.time() - 1)
        assert httpd.down

    def test_watchdog_never_interrupts_transcription(self, monkeypatch):
        calls = {"n": 0}
        def fake_sleep(_):
            calls["n"] += 1
            if calls["n"] > 3:
                raise StopIteration     # break out of the loop for the test
        class FakeHttpd:
            def __init__(self): self.down = False
            def shutdown(self): self.down = True
        monkeypatch.setattr(server, "IDLE_EXIT_SECONDS", 0.0)
        monkeypatch.setattr(server.time, "sleep", fake_sleep)
        s = server.Session.__new__(server.Session)
        s.state = uistate.TRANSCRIBING; s.last_seen = time.time() - 999
        httpd = FakeHttpd()
        with pytest.raises(StopIteration):
            server._watchdog(httpd, s, 0)
        assert not httpd.down

    def test_second_launch_finds_the_first(self, live, monkeypatch, tmp_path):
        monkeypatch.setattr(server.log, "log_dir", lambda: tmp_path)
        (tmp_path / "app.lock").write_text(json.dumps({"port": live["port"], "pid": 1}))
        assert server._running_instance() == f"http://127.0.0.1:{live['port']}/"

    def test_stale_lock_is_ignored(self, monkeypatch, tmp_path):
        monkeypatch.setattr(server.log, "log_dir", lambda: tmp_path)
        (tmp_path / "app.lock").write_text(json.dumps({"port": 1, "pid": 1}))   # nothing listens
        assert server._running_instance() == ""


class TestPollCost:
    """The window polls twice a second; that must not rescan the whole repo."""

    def test_repeat_polls_do_not_rescan_disk(self, live, monkeypatch):
        calls = {"n": 0}
        real = server.store.list_meetings
        monkeypatch.setattr(server.store, "list_meetings",
                            lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(*a, **k))[1])
        for _ in range(6):
            call(live, "GET", "/api/state")
        assert calls["n"] == 1, f"rescanned {calls['n']} times across 6 polls"

    def test_starting_a_recording_refreshes_immediately(self, live, monkeypatch):
        call(live, "GET", "/api/state")                      # warm the cache
        calls = {"n": 0}
        real = server.store.list_meetings
        monkeypatch.setattr(server.store, "list_meetings",
                            lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(*a, **k))[1])
        call(live, "POST", "/api/start", {"title": "New call", "consent": True})
        call(live, "GET", "/api/state")
        assert calls["n"] >= 1, "cache not invalidated after a write"

    def test_cache_expires(self, live):
        call(live, "GET", "/api/state")
        live["session"]._cache_at -= server.CACHE_SECONDS + 1
        stale = live["session"]._cache_at
        call(live, "GET", "/api/state")
        assert live["session"]._cache_at > stale
