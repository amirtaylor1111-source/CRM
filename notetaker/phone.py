"""Import call recordings made by the phone itself.

Android will not let any app capture call audio — the OS excludes voice
calls from playback capture on purpose. But Samsung's own dialer is a
system app, so it can, and in South Africa that feature ships enabled.

So the phone records; this brings the files in. Point it at whatever folder
those recordings sync into (OneDrive, Samsung Cloud's local mirror, or a USB
copy) and it files each call as a meeting, transcribes it, and links the
contact.

Cellular calls only. WhatsApp calls never reach this folder, because
Samsung's recorder cannot see them either — take those on the laptop, where
loopback capture works.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import log, store
from .schema import slugify

_log = log.get("phone")

# Samsung names its files a few different ways depending on One UI version.
# Ordered most-specific first; the first that matches wins.
_PATTERNS = [
    # Call recording Monty Smythe_260904_143012.m4a
    re.compile(r"^Call\s*recording\s+(?P<who>.+?)[_\s](?P<date>\d{6})[_\s](?P<time>\d{6})", re.I),
    # Call_Monty Smythe_20260904_143012.m4a
    re.compile(r"^Call[_\s](?P<who>.+?)[_\s](?P<date>\d{8})[_\s](?P<time>\d{6})", re.I),
    # 20260904 143012 Monty Smythe.m4a
    re.compile(r"^(?P<date>\d{8})[_\s](?P<time>\d{6})[_\s](?P<who>.+)$"),
    # Monty Smythe_260904_143012.m4a
    re.compile(r"^(?P<who>.+?)[_\s](?P<date>\d{6})[_\s](?P<time>\d{6})"),
]

AUDIO_SUFFIXES = {".m4a", ".mp3", ".amr", ".3gp", ".aac", ".wav", ".ogg", ".opus"}
LEDGER = "phone-imports.json"


class PhoneImportError(RuntimeError):
    """Raised when a recording cannot be brought in, with the fix."""


def parse_filename(name: str) -> tuple[str, datetime | None]:
    """Pull (who, when) out of a recording's filename.

    Returns ("", None) rather than guessing when the name does not match a
    known shape — a wrong contact is worse than an unnamed call.
    """
    stem = Path(name).stem.strip()
    for pattern in _PATTERNS:
        match = pattern.match(stem)
        if not match:
            continue
        raw_date, raw_time = match.group("date"), match.group("time")
        fmt = "%y%m%d%H%M%S" if len(raw_date) == 6 else "%Y%m%d%H%M%S"
        try:
            when = datetime.strptime(raw_date + raw_time, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        who = re.sub(r"[_]+", " ", match.group("who")).strip(" -_")
        # A bare number is a number, not a name.
        if re.fullmatch(r"[\d\s+()-]+", who):
            who = who.strip()
        return who, when
    return "", None


def file_id(path: Path) -> str:
    """A stable id for a recording: first 1 MB plus size.

    Hashing the whole file would be slow over a synced network folder, and
    the head plus size is more than enough to tell two calls apart.
    """
    digest = hashlib.sha256()
    digest.update(str(path.stat().st_size).encode())
    with path.open("rb") as fh:
        digest.update(fh.read(1_000_000))
    return digest.hexdigest()[:16]


def _ledger_path(root: Path | None = None) -> Path:
    return store.meetings_dir(root) / LEDGER


def _load_ledger(root: Path | None = None) -> dict[str, str]:
    path = _ledger_path(root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_ledger(ledger: dict[str, str], root: Path | None = None) -> None:
    path = _ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")


def to_wav(source: Path, destination: Path) -> None:
    """Convert a phone recording to the 16 kHz mono WAV the engine expects.

    Phones record AMR or M4A; the speech engine reads PCM WAV only. ffmpeg
    is the one dependency this path adds, and only this path.
    """
    if not shutil.which("ffmpeg"):
        raise PhoneImportError(
            "ffmpeg is needed to convert phone recordings.\n"
            "  Fix:  winget install Gyan.FFmpeg\n"
            "  Then open a new terminal and try again."
        )
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not destination.exists():
        raise PhoneImportError(
            f"Could not convert {source.name}:\n  {(result.stderr or '').strip()[:200]}")


def find_recordings(folder: Path) -> list[Path]:
    if not folder.exists():
        raise PhoneImportError(
            f"No such folder: {folder}\n"
            "  On the phone the recordings live in Internal storage > Call.\n"
            "  Sync that folder to this PC, then point --from at it.")
    return sorted(p for p in folder.rglob("*")
                  if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES)


def import_recording(
    path: Path,
    root: Path | None = None,
    transcribe: bool = True,
    progress=lambda _m: None,
) -> tuple[Path | None, str]:
    """Bring one recording in. Returns (meeting_dir, status)."""
    ledger = _load_ledger(root)
    key = file_id(path)
    if key in ledger:
        return None, "already imported"

    who, when = parse_filename(path.name)
    when = when or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    title = f"Call with {who}" if who else "Phone call"

    meeting_dir = store.create_meeting(
        title,
        [who] if who and not re.fullmatch(r"[\d\s+()-]+", who) else [],
        # The phone recorded this, and Samsung announces recording on the
        # line where the law requires it. Record what we actually know.
        consent_obtained=True,
        consent_note="recorded by the phone's own dialer",
        root=root,
    )
    meeting = store.load_meeting(meeting_dir)
    meeting.started_at = when.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    store.save_meeting(meeting_dir, meeting)

    # The far end is on the only track there is, so label it as such rather
    # than pretending this is a two-track recording.
    destination = meeting_dir / "system.wav"
    progress(f"converting {path.name}")
    to_wav(path, destination)

    status = "imported"
    if transcribe:
        from . import transcribe as tr

        progress(f"transcribing {path.name}")
        try:
            tr.transcribe_meeting(
                meeting_dir,
                vocabulary=store.vocabulary(root),
                speaker_names={"system": who or "Caller"},
                progress=progress,
            )
            meeting = store.load_meeting(meeting_dir)
            meeting.transcribed = True
            store.save_meeting(meeting_dir, meeting)
            status = "imported and transcribed"
        except Exception as exc:
            _log.exception("transcription failed for %s", path.name)
            status = f"imported, transcription failed: {str(exc)[:60]}"

    if who and not re.fullmatch(r"[\d\s+()-]+", who):
        store.link_contact(meeting_dir, who, root=root)

    ledger[key] = meeting_dir.name
    _save_ledger(ledger, root)
    store.rebuild_index(root)
    _log.info("imported %s -> %s", path.name, meeting_dir.name)
    return meeting_dir, status


def import_folder(
    folder: Path,
    root: Path | None = None,
    transcribe: bool = True,
    limit: int = 0,
    progress=lambda _m: None,
) -> dict[str, Any]:
    recordings = find_recordings(Path(folder))
    if limit:
        recordings = recordings[-limit:]
    results = {"found": len(recordings), "imported": 0, "skipped": 0, "failed": 0,
               "meetings": []}
    for recording in recordings:
        try:
            meeting_dir, status = import_recording(recording, root, transcribe, progress)
        except PhoneImportError as exc:
            results["failed"] += 1
            progress(f"{recording.name}: {exc}")
            continue
        if meeting_dir is None:
            results["skipped"] += 1
        else:
            results["imported"] += 1
            results["meetings"].append({"name": meeting_dir.name, "status": status})
    return results
