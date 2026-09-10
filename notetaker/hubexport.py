"""The meetings export Hub reads.

Contract: `docs/superpowers/specs/2026-09-09-meetings-to-hub.md`. Agreed with
the Hub session on 9 September 2026; changed only by agreement.

Three things about this module are decisions rather than implementation
details, and each is load-bearing:

* **The transcript is referenced by path and never inlined.** Hub indexes what
  it stores for search and feeds it to prompts, and the transcript is 92-97%
  accurate. Shipping it would put words nobody said into Hub's index and let
  Hub read mis-transcribed numbers as fact. `notes.md` is where Claude has
  already repaired those from context, so it is the more accurate artifact,
  not the lossier one.
* **`lane` is three-valued.** Guessing `business` on thin evidence puts a
  personal conversation about Amir's finances into Hub's business surfaces.
  Saying `unknown` costs a search miss. Those are not the same size of
  mistake, so this never guesses.
* **The export is a full rebuild, always.** No cursor, no delta, no partial
  state. A deleted export costs nothing because the next run recreates it
  whole, which is the reasoning `store.rebuild_index` already uses.

No audio library, ffmpeg or speech model is imported here, so this runs on the
machine `mtg doctor` has to diagnose.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from . import store
from .schema import utcnow

SCHEMA_VERSION = 1

NOTE = ("Meetings from Amir's local notetaker. Notes are Claude-authored and "
        "error-repaired; transcripts are machine-authored and are referenced "
        "by path, never inlined.")

#: Written by this tool, read by Hub. One writer, everyone else reads.
EXPORT_NAME = "meetings.json"

#: The callout the meeting-notes skill puts at the top of a personal write-up.
PERSONAL_MARKER = re.compile(r"\*\*Personal,\s*not client work\.?\*\*", re.I)

#: `- [ ] **@owner** — what they committed to (due: date)`
ACTION_LINE = re.compile(
    r"^\s*[-*]\s*\[(?P<done>[ xX])\]\s*(?:\*\*(?P<owner>[^*]+)\*\*)?"
    r"\s*(?:[-—–:]\s*)?(?P<text>.+?)\s*$")
DUE = re.compile(r"\(due:\s*(?P<due>[^)]*)\)\s*$", re.I)

LANES = ("business", "personal", "unknown")


#: Overrides the export directory. The test suite sets it for every test, so
#: no test can name the production path even by accident. On 9 September the
#: server tests wrote a fixture meeting over Amir's real export, and Hub came
#: one collector run away from ingesting "Monty Smythe" as a client with an
#: action item attributed to Amir.
EXPORT_DIR_ENV = "MTG_EXPORT_DIR"


def export_dir() -> Path:
    """`%LOCALAPPDATA%\\mtg\\exports`, matching where `log.py` already writes."""
    if override := os.environ.get(EXPORT_DIR_ENV):
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "mtg" / "exports"


def export_path() -> Path:
    return export_dir() / EXPORT_NAME


# --- reading the pieces ----------------------------------------------------

def _frontmatter(text: str) -> dict[str, str]:
    """The transcript's own header. Deliberately not a YAML dependency."""
    if not text.startswith("---"):
        return {}
    _, _, rest = text.partition("\n")
    body, sep, _ = rest.partition("\n---")
    if not sep:
        return {}
    out: dict[str, str] = {}
    for line in body.splitlines():
        key, colon, value = line.partition(":")
        if colon:
            out[key.strip()] = value.strip()
    return out


def _sections(notes: str) -> dict[str, list[str]]:
    """Split a write-up into its `##` sections, keeping line order."""
    out: dict[str, list[str]] = {}
    current = ""
    for line in notes.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            out.setdefault(current, [])
        elif current:
            out[current].append(line)
    return out


def _bullets(lines: list[str]) -> list[str]:
    """Bullet text, with the marker and any checkbox removed."""
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(("- ", "* ")):
            continue
        text = stripped[2:].strip()
        text = re.sub(r"^\[[ xX]\]\s*", "", text)
        if text:
            out.append(text)
    return out


def _action_items(lines: list[str]) -> list[dict[str, Any]]:
    items = []
    for line in lines:
        match = ACTION_LINE.match(line)
        if not match:
            continue
        text = match.group("text").strip()
        due = None
        if found := DUE.search(text):
            raw = found.group("due").strip().strip('"').strip("'")
            text = text[:found.start()].strip()
            due = None if raw.lower().startswith("unspecified") else raw
        owner = (match.group("owner") or "").strip()
        items.append({
            "text": text.rstrip(" .") if text.endswith(" .") else text,
            "assignee": owner or None,
            "done": match.group("done").lower() == "x",
            "due": due,
        })
    return items


def _lane(meeting, notes: str) -> str:
    """Explicit beats marker beats participants beats admitting ignorance.

    Never guesses `business`. A personal conversation filed as business
    surfaces where it must not; an unknown one filed as unknown costs a
    search miss. Hub is told which way this can be wrong.
    """
    explicit = (getattr(meeting, "lane", "") or "").strip().lower()
    if explicit in LANES:
        return explicit
    if PERSONAL_MARKER.search(notes):
        return "personal"
    if any(p.name for p in meeting.participants):
        return "business"
    return "unknown"


def _transcript(directory: Path) -> tuple[str | None, dict[str, Any]]:
    path = directory / "transcript.md"
    if not path.exists():
        return None, {"engine": "", "expectedAccuracy": "", "tracks": "",
                      "segments": 0, "lowConfidenceSegments": 0,
                      "namesCorrected": 0, "speakerMethod": "",
                      "partial": False}
    meta = _frontmatter(path.read_text(encoding="utf-8", errors="replace"))

    def number(key: str) -> int:
        try:
            return int(meta.get(key, "0"))
        except ValueError:
            return 0

    return str(path.resolve()), {
        "engine": meta.get("engine", ""),
        "expectedAccuracy": meta.get("expected_accuracy", ""),
        "tracks": meta.get("tracks", ""),
        "segments": number("segments"),
        "lowConfidenceSegments": number("low_confidence_segments"),
        "namesCorrected": number("names_corrected"),
        "speakerMethod": meta.get("speaker_method", ""),
        "partial": meta.get("live", "False").strip().lower() == "true",
    }


# --- the revision ----------------------------------------------------------

#: Exactly what Hub stores, and nothing else. A re-transcription that leaves
#: the write-up alone must not look like a change, or Hub churns its rows over
#: content it does not hold. Advisory: Hub computes its own and logs a
#: mismatch rather than trusting this one.
REVISION_FIELDS = ("title", "lane", "date", "endedAt", "participants",
                   "summary", "decisions", "actionItems", "notes")


def revision(record: dict[str, Any]) -> str:
    subset = {k: record[k] for k in REVISION_FIELDS}
    subset["participants"] = sorted(subset["participants"])
    blob = json.dumps(subset, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --- building --------------------------------------------------------------

def _record(directory: Path) -> dict[str, Any]:
    meeting = store.load_meeting(directory)
    notes_file = directory / "notes.md"
    notes = notes_file.read_text(encoding="utf-8") if notes_file.exists() else ""
    sections = _sections(notes)
    transcript_path, transcript = _transcript(directory)

    record = {
        "id": meeting.id,
        "revision": "",
        "date": meeting.started_at,
        "endedAt": meeting.ended_at,
        "title": meeting.title,
        "lane": _lane(meeting, notes),
        "participants": [p.name for p in meeting.participants if p.name],
        "summary": " ".join(_bullets(sections.get("tl;dr", []))),
        "topics": list(meeting.tags),
        "decisions": _bullets(sections.get("decisions", [])),
        "actionItems": _action_items(sections.get("action items", [])),
        "notes": notes,
        "notesPath": str(notes_file.resolve()) if notes_file.exists() else None,
        "transcriptPath": transcript_path,
        "transcript": transcript,
        "consent": {"obtained": meeting.consent_obtained,
                    "note": meeting.consent_note},
        "project": None,
    }
    record["revision"] = revision(record)
    return record


def build(root: Path | None = None) -> dict[str, Any]:
    """Every meeting on disk, rebuilt from scratch.

    A meeting missing from this file is not a claim that it was deleted. Hub
    treats absence as no news, by agreement.
    """
    meetings = []
    for meeting in store.list_meetings(root):
        directory = store.meetings_dir(root) / meeting.id
        if (directory / "meeting.json").exists():
            meetings.append(_record(directory))
    return {
        "writtenAt": utcnow(),
        "note": NOTE,
        "schemaVersion": SCHEMA_VERSION,
        "meetings": meetings,
    }


def undecided(root: Path | None = None) -> list[dict[str, Any]]:
    """Meetings whose lane could not be derived, newest first.

    Hub declines to file an `unknown` meeting at all, which is the honest
    form of refusing to guess but means such a meeting is invisible there
    rather than merely uncategorised. So the tool has to offer this list
    rather than leave Amir to know he should ask for it.
    """
    return [m for m in build(root=root)["meetings"] if m["lane"] == "unknown"]


def write(destination: Path | None = None, root: Path | None = None) -> Path:
    """Write the export atomically, so Hub never reads half a file."""
    path = Path(destination) if destination else export_path()
    doc = build(root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".writing")
    temporary.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    os.replace(temporary, path)
    return path
