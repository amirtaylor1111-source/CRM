"""The `mtg` command.

Deliberately small. Start, stop, and hand off to Claude — anything cleverer
belongs in a skill, where it runs on the user's existing subscription rather
than costing them an API bill.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import capture, hardware, log, store
from .schema import utcnow

DISCLOSURE = (
    "Just so everyone knows, I'm recording this call so I can take notes "
    "afterwards. Let me know if you'd rather I didn't."
)

OK, USER_ERROR, ENV_ERROR = 0, 1, 2


def _print_disclosure() -> None:
    print()
    print("  Say this before you start:")
    print()
    for line in _wrap(DISCLOSURE, 66):
        print(f"    {line}")
    print()


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def cmd_start(args) -> int:
    consent = False
    note = ""

    if args.solo:
        note = "solo recording; no other participants present"
    else:
        _print_disclosure()
        try:
            reply = input("  Have you told them? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return USER_ERROR
        if reply not in ("y", "yes"):
            print("\n  Not started. Say the line above, then run `mtg start` again.")
            return USER_ERROR
        consent = True
        note = f"participants informed verbally at {utcnow()}"

    people = [p.strip() for p in (args.with_ or "").split(",") if p.strip()]
    title = args.title

    if args.next:
        event = store.current_or_next()
        if event is None:
            print("  No meeting starting soon. Sync with /calendar, or pass --title.",
                  file=sys.stderr)
            return USER_ERROR
        title = title or event["subject"]
        if not people:
            people = store.attendee_names(event, me=_me())
        print(f"  From your calendar: {event['subject']}")

    title = title or (f"Call with {people[0]}" if people else "Meeting")

    meeting_dir = store.create_meeting(title, people, consent, note)
    print(f"\n  Recording: {meeting_dir.name}")
    if args.video:
        print("  Screen capture on.")
    print("  Wear headphones — otherwise both voices land on both tracks.")
    print(f"\n  Stop with:  mtg stop\n")

    # Re-exec ourselves as a detached recorder so the user's terminal is free
    # and `mtg stop` can be run from anywhere.
    child = [sys.executable, "-m", "notetaker.cli", "_record", str(meeting_dir)]
    if args.video:
        child.append("--video")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    try:
        subprocess.Popen(
            child,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
            cwd=str(store.repo_root()),
        )
    except OSError as exc:
        print(f"  Could not start the recorder: {exc}", file=sys.stderr)
        return ENV_ERROR

    # Confirm it actually came up, rather than reporting success blindly. On
    # a loaded machine its imports alone can take several seconds.
    for _ in range(60):
        time.sleep(0.25)
        if capture.is_recording(meeting_dir):
            return OK
    print("  Warning: the recorder did not report in. Run `mtg doctor`.",
          file=sys.stderr)
    return ENV_ERROR


def cmd_record(args) -> int:
    """Internal: the detached recording process."""
    try:
        capture.start_recording(Path(args.meeting_dir), video=args.video)
    except capture.CaptureError as exc:
        state = Path(args.meeting_dir) / capture.STATE_FILE
        state.write_text(json.dumps({"error": str(exc), "ended_at": time.time()}),
                         encoding="utf-8")
        return ENV_ERROR
    return OK


def cmd_stop(args) -> int:
    meeting_dir = store.resolve_meeting(args.meeting)
    if meeting_dir is None:
        print("  No meeting found.", file=sys.stderr)
        return USER_ERROR

    state_path = meeting_dir / capture.STATE_FILE
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("error"):
                print(f"  The recorder failed to start:\n\n  {state['error']}",
                      file=sys.stderr)
                return ENV_ERROR
        except (OSError, json.JSONDecodeError):
            pass

    print("  Stopping ...")
    tracks = capture.stop_recording(meeting_dir)
    if not tracks:
        print("  No audio was captured. Run `mtg doctor`.", file=sys.stderr)
        return ENV_ERROR

    store.finalize_meeting(meeting_dir, tracks=tracks)
    for track in tracks:
        size = Path(track).stat().st_size / (1024 * 1024)
        print(f"    {Path(track).name}  {size:.1f} MB")

    if args.no_transcribe:
        print(f"\n  Transcribe later with:  mtg transcribe {meeting_dir.name}")
        return OK
    return _transcribe(meeting_dir)


def _transcribe(meeting_dir: Path) -> int:
    from . import transcribe as tr

    print()
    try:
        tr.transcribe_meeting(meeting_dir, vocabulary=store.vocabulary())
    except tr.TranscribeError as exc:
        print(f"\n  {exc}", file=sys.stderr)
        return ENV_ERROR

    meeting = store.load_meeting(meeting_dir)
    meeting.transcribed = True
    store.save_meeting(meeting_dir, meeting)
    for person in meeting.participants:
        store.link_contact(meeting_dir, person.name)
    store.rebuild_index()

    print()
    print("  Done. Now open Claude Code here and run:")
    print()
    print("      /notes")
    print()
    print("  That writes up the meeting on your existing subscription.")
    return OK


def cmd_transcribe(args) -> int:
    meeting_dir = store.resolve_meeting(args.meeting)
    if meeting_dir is None:
        print("  No meeting found.", file=sys.stderr)
        return USER_ERROR
    return _transcribe(meeting_dir)


def cmd_status(args) -> int:
    meeting_dir = store.latest_meeting()
    if meeting_dir is None:
        print("  No meetings yet. Start one with `mtg start`.")
        return OK
    meeting = store.load_meeting(meeting_dir)
    if capture.is_recording(meeting_dir):
        state = json.loads((meeting_dir / capture.STATE_FILE).read_text(encoding="utf-8"))
        elapsed = int(time.time() - state.get("started_at", time.time()))
        print(f"  RECORDING  {meeting.title}")
        print(f"  Elapsed    {elapsed // 60}m {elapsed % 60}s")
        print(f"  Tracks     {', '.join(t['name'] for t in state.get('tracks', []))}")
        print("\n  Stop with:  mtg stop")
    else:
        print(f"  Not recording. Last meeting: {meeting.title} ({meeting.started_at[:10]})")
        print(f"  Transcribed: {'yes' if meeting.transcribed else 'no'}")
    return OK


def cmd_list(args) -> int:
    meetings = store.list_meetings()
    if not meetings:
        print("  No meetings yet.")
        return OK
    for meeting in meetings[: args.limit]:
        mark = "✓" if meeting.transcribed else " "
        people = ", ".join(p.name for p in meeting.participants) or "—"
        print(f"  {mark} {meeting.started_at[:10]}  {meeting.title[:40]:42} {people}")
    return OK


def cmd_search(args) -> int:
    results = store.search(args.query)
    if not results:
        print(f"  Nothing found for {args.query!r}.")
        return OK
    for result in results:
        print(f"\n  {result['date']}  {result['title']}")
        for hit in result["hits"]:
            print(f"      {hit}")
    return OK


def cmd_open(args) -> int:
    meeting_dir = store.resolve_meeting(args.meeting)
    if meeting_dir is None:
        print("  No meeting found.", file=sys.stderr)
        return USER_ERROR
    print(meeting_dir)
    return OK


def _check_import(label: str, module: str, fix: str) -> tuple[str, bool, str]:
    """Import an optional dependency and report, whatever goes wrong.

    ImportError is the common case, but a native audio backend can raise
    OSError when the platform's audio subsystem is absent, and onnxruntime
    raises an ImportError subclass on a missing DLL. The doctor exists to
    explain those; it must never die of them.
    """
    import importlib

    try:
        importlib.import_module(module)
        return (label, True, "")
    except ImportError as exc:
        detail = str(exc)
        if "DLL" in detail or "dll" in detail:
            fix = f"{fix}  (DLL load failed: install the Visual C++ Redistributable)"
        return (label, False, fix)
    except Exception as exc:
        return (label, False, f"{fix}  ({type(exc).__name__}: {str(exc)[:60]})")


def _webview2_present() -> bool:
    """Windows 11 ships the WebView2 runtime; older machines may not have it."""
    if sys.platform != "win32":
        return True
    try:
        import winreg

        for root, path in (
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_CURRENT_USER,
             r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        ):
            try:
                with winreg.OpenKey(root, path):
                    return True
            except OSError:
                continue
    except Exception:
        pass
    return False


def cmd_doctor(args) -> int:
    hw = hardware.detect()
    choice = hardware.recommend(hw)

    print(f"\n  Machine   {hw.summary()}")
    print(f"  Engine    {choice['model']}  ({choice['wer']} word error on published benchmarks)")
    print(f"  Speed     1-hour meeting -> {hardware.format_estimate(3600, choice, hw)}")
    print(f"  Reason    {choice['why']}")
    print()

    checks: list[tuple[str, bool, str]] = []

    checks.append(_check_import("audio library", "soundcard", "pip install soundcard"))
    checks.append(_check_import("numpy", "numpy", "pip install numpy"))

    try:
        devices = capture.list_devices()
        checks.append((f"microphone ({len(devices['microphones'])} found)",
                       bool(devices["microphones"]),
                       "check Windows Settings > System > Sound > Input"))
        checks.append((f"system audio ({len(devices['loopbacks'])} found)",
                       bool(devices["loopbacks"]),
                       "no loopback device; check your output device is active"))
    except capture.CaptureError as exc:
        checks.append(("audio devices", False, str(exc).splitlines()[0]))
    except Exception as exc:                     # a broken driver must not
        checks.append(("audio devices", False,   # end the diagnosis
                       f"{type(exc).__name__}: {str(exc)[:70]}"))

    from . import transcribe as tr

    try:
        backends = tr.available_backends()
    except Exception as exc:
        backends = []
        checks.append(("transcription engine import", False,
                       f"{type(exc).__name__}: {str(exc)[:70]}"))
    checks.append((f"transcription engine ({', '.join(backends) or 'none'})",
                   bool(backends),
                   "pip install onnx-asr[cpu,hub]  (on Windows, a DLL error here "
                   "means the Visual C++ Redistributable is missing)"))

    checks.append((f"disk space ({hw.free_disk_gb:.0f} GB free)",
                   hw.free_disk_gb > 10,
                   "under 10 GB free; run `mtg prune` or clear space"))

    # The widget and its brain. None of these stop a recording; they say
    # which parts of the widget will be there.
    checks.append(_check_import("widget window (pywebview)", "webview",
                                "pip install pywebview  (or use `mtg app --browser`)"))
    checks.append(("WebView2 runtime", _webview2_present(),
                   "install the WebView2 Runtime from Microsoft, or use `mtg app --browser`"))
    from . import assistant

    checks.append(("Claude Code on PATH", bool(assistant.available()),
                   "install Claude Code, then run  claude  once and  /login"))

    width = max(len(name) for name, _, _ in checks)
    failed = 0
    for name, ok, fix in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:{width}}", end="")
        if not ok:
            failed += 1
            print(f"   -> {fix}")
        else:
            print()

    print()
    print(f"  Log       {log.log_path()}")
    print()
    if failed:
        print(f"  {failed} check(s) failed.")
        return ENV_ERROR
    print("  Ready. Remember to wear headphones.")
    return OK


def cmd_watch(args) -> int:
    """Run the calendar watcher in the foreground (setup runs it at login)."""
    from . import watcher

    print("  Watching your calendar. It will offer to record when a meeting starts.")
    print("  Ctrl-C to stop.")
    return watcher.main()


def cmd_app(args) -> int:
    """Open the widget.

    The always-on-top widget is the default. --browser opens the same page
    in Edge's app mode, which needs no extra packages; --classic opens the
    Tkinter window for a machine with no Chromium-based browser at all.
    """
    if args.classic:
        from . import app

        return app.main()
    if args.browser:
        from . import server

        return server.serve()
    from . import widget

    return widget.main()


def cmd_next(args) -> int:
    """What is coming up, and what is recordable right now."""
    events = store.upcoming(limit=args.limit)
    if not events:
        print("  No upcoming meetings. Sync with /calendar in Claude Code.")
        return OK

    due = store.current_or_next()
    for event in events:
        marker = ">" if event is due else " "
        names = ", ".join(store.attendee_names(event, me=_me())) or "no attendees listed"
        when = event.get("start", "")[:16].replace("T", " ")
        print(f"  {marker} {when}  {event['subject'][:38]:40} {names}")

    if due:
        print(f"\n  Ready to record: {due['subject']}")
        print("  Start it with:  mtg start --next")
    return OK


def _me() -> str:
    """The user's own address, so they are not listed as their own attendee."""
    return os.environ.get("MTG_ME", "")


def cmd_calendar(args) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"  No such file: {path}", file=sys.stderr)
        return USER_ERROR
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  {path} is not valid JSON: {exc}", file=sys.stderr)
        return USER_ERROR
    events = payload if isinstance(payload, list) else payload.get("events", [])
    store.save_calendar(events)
    print(f"  Synced {len(events)} event(s).")
    return cmd_next(argparse.Namespace(limit=5))


def cmd_phone(args) -> int:
    """Import call recordings the phone made itself."""
    from . import phone

    folder = Path(args.folder).expanduser()

    when = None
    if args.when:
        try:
            when = datetime.fromisoformat(args.when)
        except ValueError:
            print(f"\n  --when is not an ISO 8601 timestamp: {args.when}\n"
                  "  Try something like  2026-08-27T10:37:16+02:00", file=sys.stderr)
            return USER_ERROR

    print(f"  Scanning {folder}")
    try:
        recordings = phone.find_recordings(folder)
    except phone.PhoneImportError as exc:
        print(f"\n  {exc}", file=sys.stderr)
        return ENV_ERROR
    if args.limit:
        recordings = recordings[-args.limit:]

    # A title and a time belong to one call. Spread across a folder they
    # would stamp the same name and date on every recording in it.
    if (args.title or when) and len(recordings) != 1:
        print(f"\n  --title and --when describe one recording, but {len(recordings)} "
              f"were found under {folder}.\n"
              "  Name the audio file itself, or drop those flags.", file=sys.stderr)
        return USER_ERROR

    try:
        result = phone.import_folder(folder, transcribe=not args.no_transcribe,
                                     limit=args.limit, progress=lambda m: print(f"    {m}"),
                                     title=args.title, when=when)
    except phone.PhoneImportError as exc:
        print(f"\n  {exc}", file=sys.stderr)
        return ENV_ERROR

    print(f"\n  Found {result['found']}, imported {result['imported']}, "
          f"already had {result['skipped']}, failed {result['failed']}.")
    for meeting in result["meetings"]:
        print(f"    {meeting['name']}  ({meeting['status']})")
    if result["imported"]:
        print("\n  Write them up with  /notes  in Claude Code.")
    return OK


def cmd_import(args) -> int:
    """Import meetings recorded elsewhere, from a JSON file.

    The connector lives in the Claude session, which holds the credentials;
    this end only files what it is given, so the import path stays testable
    with no network involved.
    """
    path = Path(args.file)
    if not path.exists():
        print(f"  No such file: {path}", file=sys.stderr)
        return USER_ERROR
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  {path} is not valid JSON: {exc}", file=sys.stderr)
        return USER_ERROR

    meetings = payload if isinstance(payload, list) else payload.get("meetings", [])
    if not meetings:
        print("  Nothing to import.")
        return OK

    counts = store.import_batch(meetings)
    print(f"  Imported {counts['created']} new, updated {counts['updated']}.")
    print(f"  Contacts now known: {len(store.list_contacts())}")
    return OK


def cmd_prune(args) -> int:
    """Delete raw audio from meetings that are already transcribed."""
    freed = 0
    removed = 0
    for meeting in store.list_meetings():
        directory = store.meetings_dir() / meeting.id
        if not (directory / "transcript.md").exists():
            continue
        for name in ("mic.wav", "system.wav", "screen.mp4"):
            path = directory / name
            if path.exists():
                size = path.stat().st_size
                if args.dry_run:
                    print(f"  would remove  {path.relative_to(store.repo_root())}"
                          f"  ({size / 1024 / 1024:.0f} MB)")
                else:
                    path.unlink()
                freed += size
                removed += 1
    verb = "Would free" if args.dry_run else "Freed"
    print(f"\n  {verb} {freed / 1024 / 1024:.0f} MB across {removed} file(s).")
    if args.dry_run and removed:
        print("  Run without --dry-run to delete.")
    return OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mtg",
        description="Record meetings locally, transcribe them, hand them to Claude.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start recording")
    start.add_argument("--title", "-t", help="what to call this meeting")
    start.add_argument("--with", "-w", dest="with_", help="participants, comma separated")
    start.add_argument("--video", action="store_true", help="also capture the screen")
    start.add_argument("--solo", action="store_true",
                       help="no other participants; skip the consent prompt")
    start.add_argument("--next", action="store_true",
                       help="take the title and attendees from your calendar")
    start.set_defaults(func=cmd_start)

    stop = sub.add_parser("stop", help="stop recording and transcribe")
    stop.add_argument("meeting", nargs="?")
    stop.add_argument("--no-transcribe", action="store_true")
    stop.set_defaults(func=cmd_stop)

    tr = sub.add_parser("transcribe", help="transcribe a meeting")
    tr.add_argument("meeting", nargs="?")
    tr.set_defaults(func=cmd_transcribe)

    st = sub.add_parser("status", help="is anything recording")
    st.set_defaults(func=cmd_status)

    ls = sub.add_parser("list", help="recent meetings")
    ls.add_argument("--limit", "-n", type=int, default=20)
    ls.set_defaults(func=cmd_list)

    se = sub.add_parser("search", help="search transcripts and notes")
    se.add_argument("query")
    se.set_defaults(func=cmd_search)

    op = sub.add_parser("open", help="print a meeting's folder")
    op.add_argument("meeting", nargs="?")
    op.set_defaults(func=cmd_open)

    dr = sub.add_parser("doctor", help="check everything is set up")
    dr.set_defaults(func=cmd_doctor)

    pr = sub.add_parser("prune", help="delete audio from transcribed meetings")
    pr.add_argument("--dry-run", action="store_true")
    pr.set_defaults(func=cmd_prune)

    wa = sub.add_parser("watch", help="offer to record when a meeting starts")
    wa.set_defaults(func=cmd_watch)

    ap = sub.add_parser("app", help="open the widget")
    ap.add_argument("--browser", action="store_true",
                    help="open the page in an Edge window instead of the widget")
    ap.add_argument("--classic", action="store_true",
                    help="use the plain built-in window instead of the widget")
    ap.set_defaults(func=cmd_app)

    nx = sub.add_parser("next", help="upcoming meetings from your calendar")
    nx.add_argument("--limit", "-n", type=int, default=5)
    nx.set_defaults(func=cmd_next)

    cal = sub.add_parser("calendar", help="load synced calendar events from JSON")
    cal.add_argument("file")
    cal.set_defaults(func=cmd_calendar)

    ph = sub.add_parser("phone", help="import call recordings from your phone")
    ph.add_argument("folder", help="folder or single audio file")
    ph.add_argument("--no-transcribe", action="store_true")
    ph.add_argument("--limit", type=int, default=0, help="only the newest N")
    ph.add_argument("--title", help="title for a single recording, "
                                    "when the filename does not carry one")
    ph.add_argument("--when", help="when a single recording was made, ISO 8601, "
                                   "e.g. 2026-08-27T10:37:16+02:00")
    ph.set_defaults(func=cmd_phone)

    im = sub.add_parser("import", help="import meetings from a JSON file")
    im.add_argument("file")
    im.set_defaults(func=cmd_import)

    rec = sub.add_parser("_record", help=argparse.SUPPRESS)
    rec.add_argument("meeting_dir")
    rec.add_argument("--video", action="store_true")
    rec.set_defaults(func=cmd_record)

    return parser


def _utf8_console() -> None:
    """Stop a cp1252 console from crashing on ✓, ⚠ or an em dash.

    Classic cmd.exe still defaults to the OEM code page. Replacing rather
    than raising means the worst case is a '?' on screen, never a traceback
    in place of the user's meeting list.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    logger = log.setup(verbose=os.environ.get("MTG_DEBUG") == "1")
    logger.info("command: %s", args.command)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        return USER_ERROR
    except capture.CaptureError as exc:
        logger.error("capture: %s", exc)
        print(f"\n  {exc}", file=sys.stderr)
        return ENV_ERROR
    except OSError as exc:
        logger.exception("filesystem error")
        print(f"\n  Filesystem error: {exc}", file=sys.stderr)
        return ENV_ERROR
    except Exception:
        logger.exception("unhandled")
        print(f"\n  Something went wrong. Details are in:\n  {log.log_path()}",
              file=sys.stderr)
        return ENV_ERROR


if __name__ == "__main__":
    sys.exit(main())
