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
from pathlib import Path

from . import capture, hardware, store
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

    # Confirm it actually came up, rather than reporting success blindly.
    for _ in range(20):
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


def cmd_doctor(args) -> int:
    hw = hardware.detect()
    choice = hardware.recommend(hw)

    print(f"\n  Machine   {hw.summary()}")
    print(f"  Engine    {choice['model']}  ({choice['wer']} expected word error)")
    print(f"  Speed     1-hour meeting -> {hardware.format_estimate(3600, choice, hw)}")
    print(f"  Reason    {choice['why']}")
    print()

    checks: list[tuple[str, bool, str]] = []

    try:
        import soundcard  # noqa: F401

        checks.append(("audio library", True, ""))
    except ImportError:
        checks.append(("audio library", False, "pip install soundcard"))

    try:
        import numpy  # noqa: F401

        checks.append(("numpy", True, ""))
    except ImportError:
        checks.append(("numpy", False, "pip install numpy"))

    try:
        devices = capture.list_devices()
        checks.append((f"microphone ({len(devices['microphones'])} found)",
                       bool(devices["microphones"]),
                       "check Windows Settings > System > Sound > Input"))
        checks.append((f"system audio ({len(devices['loopbacks'])} found)",
                       bool(devices["loopbacks"]),
                       "no loopback device; check your output device is active"))
    except capture.CaptureError:
        checks.append(("audio devices", False, "install the audio library first"))

    from . import transcribe as tr

    backends = tr.available_backends()
    checks.append((f"transcription engine ({', '.join(backends) or 'none'})",
                   bool(backends), "pip install onnx-asr"))

    checks.append((f"disk space ({hw.free_disk_gb:.0f} GB free)",
                   hw.free_disk_gb > 10,
                   "under 10 GB free; run `mtg prune` or clear space"))

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
    if failed:
        print(f"  {failed} check(s) failed.")
        return ENV_ERROR
    print("  Ready. Remember to wear headphones.")
    return OK


def cmd_app(args) -> int:
    """Open the desktop window."""
    from . import app

    return app.main()


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

    ap = sub.add_parser("app", help="open the desktop window")
    ap.set_defaults(func=cmd_app)

    nx = sub.add_parser("next", help="upcoming meetings from your calendar")
    nx.add_argument("--limit", "-n", type=int, default=5)
    nx.set_defaults(func=cmd_next)

    cal = sub.add_parser("calendar", help="load synced calendar events from JSON")
    cal.add_argument("file")
    cal.set_defaults(func=cmd_calendar)

    im = sub.add_parser("import", help="import meetings from a JSON file")
    im.add_argument("file")
    im.set_defaults(func=cmd_import)

    rec = sub.add_parser("_record", help=argparse.SUPPRESS)
    rec.add_argument("meeting_dir")
    rec.add_argument("--video", action="store_true")
    rec.set_defaults(func=cmd_record)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        return USER_ERROR
    except capture.CaptureError as exc:
        print(f"\n  {exc}", file=sys.stderr)
        return ENV_ERROR
    except OSError as exc:
        print(f"\n  Filesystem error: {exc}", file=sys.stderr)
        return ENV_ERROR


if __name__ == "__main__":
    sys.exit(main())
