"""The headless Claude Code bridge, against a stand-in `claude`.

The stand-in is a real executable on PATH, launched the way the widget
launches the real one (a .cmd wrapper on Windows, prompt on stdin), so the
command line, the environment and the parsing are all exercised. What it
replies is scripted per test.
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from notetaker import assistant

STANDIN = '''
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
prompt = sys.stdin.read()
json.dump({"args": sys.argv[1:], "prompt": prompt,
           "claude_env": sorted(k for k in os.environ if k.upper().startswith(("CLAUDE", "ANTHROPIC")))},
          open(os.path.join(here, "call.json"), "w", encoding="utf-8"))
reply = json.load(open(os.path.join(here, "reply.json"), encoding="utf-8"))
time.sleep(reply.pop("_sleep", 0))
if "_raw" in reply:
    sys.stdout.write(reply["_raw"]); sys.exit(reply.get("_code", 0))
print(json.dumps(reply))
'''

# The real thing is python -> cmd.exe -> claude, and killing the shim leaves
# claude holding the stdout pipe. This stand-in reproduces that: a child that
# inherits the pipe and outlives anything but a kill of the whole tree.
CHILD_STANDIN = '''
import subprocess, sys
sys.stdin.read()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
child.wait()
print("late")
'''


@pytest.fixture
def standin(tmp_path, monkeypatch):
    """A fake `claude` on PATH that records its call and replies as told."""
    script = tmp_path / "claude_standin.py"
    script.write_text(STANDIN, encoding="utf-8")
    if sys.platform == "win32":
        launcher = tmp_path / "claude.cmd"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = tmp_path / "claude"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("CLAUDECODE", "1")            # as when launched from a session
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://example.invalid")

    class Standin:
        def reply(self, **payload):
            (tmp_path / "reply.json").write_text(json.dumps(payload), encoding="utf-8")

        def call(self):
            return json.loads((tmp_path / "call.json").read_text(encoding="utf-8"))

        def was_called(self):
            return (tmp_path / "call.json").exists()

    s = Standin()
    s.reply(type="result", subtype="success", is_error=False, result="OK", session_id="sess-1")
    return s


@pytest.fixture
def leaves_a_child(tmp_path, monkeypatch):
    """A fake `claude` that starts a child of its own and waits for it."""
    script = tmp_path / "claude_child.py"
    script.write_text(CHILD_STANDIN, encoding="utf-8")
    if sys.platform == "win32":
        launcher = tmp_path / "claude.cmd"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = tmp_path / "claude"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    return launcher


@pytest.fixture
def commands(tmp_path, monkeypatch):
    """A repo root with the command files the bridge reads."""
    root = tmp_path / "repo"
    (root / ".claude" / "commands").mkdir(parents=True)
    for name, body in {
        "prep": "---\ndescription: x\n---\n\nPrepare me for a call with: $ARGUMENTS\n",
        "live-brief": "---\ndescription: x\n---\n\nBrief me on: $ARGUMENTS\nReturn JSON.\n",
        "ask": "---\ndescription: x\n---\n\nAnswer: $ARGUMENTS\n",
        "notes": "---\ndescription: x\n---\n\nWrite up the meeting: $ARGUMENTS\n",
    }.items():
        (root / ".claude" / "commands" / f"{name}.md").write_text(body, encoding="utf-8")
    monkeypatch.setattr(assistant.store, "repo_root", lambda: root)
    return root


class TestLaunch:
    def test_prompt_goes_on_stdin_and_flags_on_the_line(self, standin, commands):
        r = assistant.brief("2026-09-06-x", wait=True)
        assert r.ok and r.text == "OK"
        call = standin.call()
        assert call["prompt"].startswith("Brief me on: 2026-09-06-x")
        assert call["args"][:3] == ["-p", "--output-format", "json"]
        assert "--json-schema" in call["args"]
        assert json.loads(call["args"][call["args"].index("--json-schema") + 1]) == assistant.BRIEF_SCHEMA
        args = call["args"]
        tools = args[args.index("--allowedTools") + 1: args.index("--disallowedTools")]
        assert tools == list(assistant.READ_ONLY)
        assert "--restricted" in args
        assert args[args.index("--disallowedTools") + 1:] == list(assistant.FORBIDDEN)

    def test_the_session_environment_is_stripped(self, standin, commands, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")       # a headless login: kept
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "C:/somewhere")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-no")            # never
        assistant.prep("Monty Smythe")
        assert standin.call()["claude_env"] == ["CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"]

    def test_a_cost_estimate_is_kept_not_refused(self, standin, commands):
        standin.reply(type="result", is_error=False, result="OK", session_id="s", total_cost_usd=0.0123)
        r = assistant.prep("x")
        assert r.ok and r.cost_usd == pytest.approx(0.0123)

    def test_the_previous_brief_rides_along(self, standin, commands):
        assistant.brief("m", previous={"as_of": "00:04:00", "summary": "so far", "next_steps": [],
                                       "questions": ["q1"]}, wait=True)
        prompt = standin.call()["prompt"]
        assert "as of 00:04:00" in prompt and '"q1"' in prompt

    def test_notes_may_write_and_gets_longer(self, standin, commands, monkeypatch):
        seen = {}
        real = assistant.run

        def spy(prompt, **kw):
            seen.update(kw)
            return real(prompt, **kw)

        monkeypatch.setattr(assistant, "run", spy)
        assistant.notes("2026-09-06-x")
        assert seen["allowed_tools"] == assistant.writing_tools("2026-09-06-x")
        assert seen["timeout"] == assistant.NOTES_TIMEOUT
        assert standin.call()["prompt"].startswith("Write up the meeting: 2026-09-06-x")

    def test_ask_starts_a_conversation_then_resumes_it(self, standin, commands):
        first = assistant.ask("2026-09-06-x", "What did they say about price?")
        assert first.session_id == "sess-1"
        args = standin.call()["args"]
        assert "--resume" not in args
        assert args[args.index("--session-id") + 1] == assistant.conversation_id("2026-09-06-x")
        assert standin.call()["prompt"].startswith("Answer: 2026-09-06-x What did they say")
        assistant.ask("2026-09-06-x", "And when?", session_id=first.session_id)
        call = standin.call()
        assert call["args"][call["args"].index("--resume") + 1] == "sess-1"
        assert call["prompt"] == "And when?"

    def test_a_first_ask_that_finds_its_conversation_taken_resumes_it(self, standin, commands, monkeypatch):
        calls = []
        real = assistant.run

        def flaky(prompt, **kw):
            calls.append(kw)
            if kw.get("session_id") and not kw.get("resume"):
                return assistant.Result(False, error="failed", detail="Session ID already in use")
            return real(prompt, **kw)

        monkeypatch.setattr(assistant, "run", flaky)
        r = assistant.ask("2026-09-06-x", "What now?")
        assert r.ok
        assert calls[0]["session_id"] == assistant.conversation_id("2026-09-06-x")
        assert calls[1]["resume"] == assistant.conversation_id("2026-09-06-x")

    def test_headless_notes_cannot_touch_contacts(self, standin, commands):
        assistant.notes("2026-09-06-x")
        args = standin.call()["args"]
        tools = args[args.index("--allowedTools") + 1: args.index("--disallowedTools")]
        assert not any("contacts" in t for t in tools)
        assert "Write(meetings/2026-09-06-x/notes.md)" in tools
        assert "headless" in standin.call()["prompt"]

    def test_the_write_grant_names_one_meeting_not_every_meeting(self, standin, commands):
        assistant.notes("2026-09-06-x")
        args = standin.call()["args"]
        tools = args[args.index("--allowedTools") + 1: args.index("--disallowedTools")]
        assert tools == list(assistant.READ_ONLY) + [
            "Write(meetings/2026-09-06-x/notes.md)",
            "Edit(meetings/2026-09-06-x/notes.md)",
            "Edit(meetings/2026-09-06-x/meeting.json)",
        ]
        assert not any("meetings/**" in t for t in tools)

    @pytest.mark.parametrize("bad", ["../2026-09-06-y", "a/b", "a\\b", "..", "", "-x", "a;b",
                                     "C:/meetings/x", "x" * 300])
    def test_an_id_that_is_not_a_meeting_id_never_reaches_the_command_line(
            self, standin, commands, bad):
        r = assistant.notes(bad)
        assert not r.ok and r.error == "failed" and "not a meeting id" in r.hint
        assert not standin.was_called()

    def test_the_backstop_forbids_contacts_and_the_other_write_tools(self, standin, commands):
        assistant.notes("2026-09-06-x")
        args = standin.call()["args"]
        forbidden = args[args.index("--disallowedTools") + 1:]
        for tool in ("Bash", "MultiEdit", "NotebookEdit",
                     "Write(contacts/**)", "Edit(contacts/**)"):
            assert tool in forbidden

    def test_missing_claude_is_reported_not_raised(self, commands, monkeypatch):
        monkeypatch.setenv("PATH", "")
        r = assistant.prep("x")
        assert not r.ok and r.error == "missing" and "not installed" in r.hint


class TestReplies:
    def test_structured_output_is_returned_as_data(self, standin, commands):
        standin.reply(type="result", is_error=False, result="{}", session_id="s",
                      structured_output={"summary": "so far", "next_steps": [], "questions": ["q"]})
        r = assistant.brief("m", wait=True)
        assert r.ok and r.data["questions"] == ["q"]

    def test_json_in_the_text_counts_as_data_too(self, standin, commands):
        standin.reply(type="result", is_error=False, session_id="s",
                      result=json.dumps({"summary": "s", "next_steps": [], "questions": []}))
        r = assistant.brief("m", wait=True)
        assert r.ok and r.data["summary"] == "s"

    def test_not_logged_in_becomes_the_login_hint(self, standin, commands):
        standin.reply(type="result", subtype="error", is_error=True,
                      result="Not logged in · Please run /login", session_id="s")
        r = assistant.prep("x")
        assert not r.ok and r.error == "login"
        assert "/login" in r.hint

    def test_other_errors_carry_their_text(self, standin, commands):
        standin.reply(type="result", subtype="error_max_turns", is_error=True,
                      result="Reached max turns", session_id="s")
        r = assistant.prep("x")
        assert not r.ok and r.error == "failed" and "max turns" in r.hint

    def test_garbage_output_is_a_failure_with_detail(self, standin, commands):
        standin.reply(_raw="Segmentation fault\n", _code=139)
        r = assistant.prep("x")
        assert not r.ok and r.error == "failed" and "Segmentation" in r.hint

    def test_timeout_is_reported(self, standin, commands):
        standin.reply(type="result", is_error=False, result="late", session_id="s", _sleep=3)
        r = assistant.run("hello", timeout=0.5)
        assert not r.ok and r.error == "timeout"

    @pytest.mark.skipif(sys.platform != "win32",
                        reason="the tree kill this pins down is the Windows taskkill path")
    def test_a_timeout_kills_the_tree_and_does_not_wait_for_the_child(
            self, leaves_a_child, commands):
        started = time.monotonic()
        r = assistant.run("hello", timeout=1.5)
        waited = time.monotonic() - started
        assert not r.ok and r.error == "timeout"
        # The child lives 20 s and holds the pipe; returning at all means the
        # whole tree died, and the lock it holds went with it.
        assert waited < 8, f"run() waited {waited:.1f}s for a child it had timed out"


class TestLock:
    def test_a_brief_skips_while_a_turn_is_running(self, standin, commands):
        standin.reply(type="result", is_error=False, result="slow", session_id="s", _sleep=1.5)
        results = {}

        def slow():
            results["ask"] = assistant.ask("m", "q")

        t = threading.Thread(target=slow)
        t.start()
        time.sleep(0.4)
        results["brief"] = assistant.brief("m")           # wait=False by default
        t.join(10)
        assert results["brief"].error == "busy"
        assert results["ask"].ok


class TestCommandPrompt:
    def test_frontmatter_is_dropped_and_arguments_filled(self, commands):
        text = assistant.command_prompt("prep", "Monty Smythe")
        assert text == "Prepare me for a call with: Monty Smythe"

    def test_the_real_command_files_exist(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("prep", "live-brief", "ask", "notes"):
            text = assistant.command_prompt(name, "ARGS", root=root)
            assert "ARGS" in text and "$ARGUMENTS" not in text


class TestTheAskPanelCarriesGapsNotAHistory:
    """The widget's "Ask them" list is questions to ASK, never a record of
    what was asked. On 10 September Amir reported it drifting into the
    second thing. The previous brief's questions were being handed back
    inside the "previous brief" blob, where they read as prior output to
    continue rather than as suggestions already made."""

    def _args(self, previous):
        captured = {}

        def fake_run(prompt, **kw):
            captured["prompt"] = prompt
            return assistant.Result(ok=True, data={}, text="", error="")

        original, assistant.run = assistant.run, fake_run
        try:
            assistant.brief("2026-09-10-meeting", previous=previous)
        finally:
            assistant.run = original
        return captured["prompt"]

    def test_previous_questions_are_marked_as_already_offered(self):
        prompt = self._args({"as_of": "00:10:00", "summary": "s",
                             "next_steps": [], "questions": ["When is it due?"]})
        assert "already put in front of the user" in prompt
        assert "Do not repeat any of them" in prompt

    def test_they_are_not_inside_the_previous_brief_blob(self):
        """Where they sat before, and where they read as answer-so-far."""
        prompt = self._args({"as_of": "00:10:00", "summary": "s",
                             "next_steps": [], "questions": ["When is it due?"]})
        head, _, tail = prompt.partition("already put in front of the user")
        assert "When is it due?" not in head
        assert "When is it due?" in tail

    def test_no_questions_means_no_extra_instruction(self):
        prompt = self._args({"as_of": "00:10:00", "summary": "s",
                             "next_steps": [], "questions": []})
        assert "already put in front of the user" not in prompt

    def test_dict_shaped_questions_survive(self):
        """The UI accepts a bare string or an object with .text; so must this."""
        prompt = self._args({"as_of": "00:10:00", "summary": "s",
                             "next_steps": [], "questions": [{"text": "How many?"}]})
        assert "How many?" in prompt
