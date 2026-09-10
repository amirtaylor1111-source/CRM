"""The file-based CRM: meetings on disk, contacts as markdown.

Nothing here is a database. Every record is a file a human can open and a
grep can find, because the consumer is Claude reading the repo in a normal
session.

Layout::

    meetings/<YYYY-MM-DD>-<slug>/
        meeting.json      metadata, including the consent record
        transcript.md     machine-authored, never hand-edited
        transcript.json   segments with timings and confidence
        notes.md          Claude-authored write-up
    contacts/<slug>.md    frontmatter + managed meeting list + human notes
    meetings/index.json   rollup, always rebuildable from the directories
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from .schema import (
    Meeting,
    Participant,
    parse_frontmatter,
    serialise_frontmatter,
    slugify,
    utcnow,
)

MANAGED_HEADING = "## Meetings"
MANAGED_END_MARKER = "<!-- /meetings -->"
_MEETING_LINE = re.compile(r"^- \[(?P<date>[\d-]+)\]\((?P<path>[^)]+)\)")


def repo_root() -> Path:
    """The CRM root: the directory containing this package."""
    return Path(__file__).resolve().parent.parent


def meetings_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "meetings"


def contacts_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "contacts"


#: Windows refuses os.replace onto a file another handle has open, so an
#: ordinary concurrent read fails the writer. Every reader here holds a file
#: for microseconds, so a few short retries clear it; a lock that outlives
#: them is a real problem and still raises.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF = 0.05


def _replace_with_retry(tmp: str, path: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF * (attempt + 1))


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then replace.

    os.replace is atomic on POSIX and on Windows (MoveFileEx with
    REPLACE_EXISTING), so a crash mid-write can never leave a contact file
    truncated. The temp file shares the destination directory so the replace
    never crosses a filesystem boundary.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        _replace_with_retry(tmp, path)
    except BaseException:
        # Leave no debris if anything went wrong on the way.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: Any) -> None:
    _write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# --- meetings --------------------------------------------------------------


def create_meeting(
    title: str,
    participants: Iterable[str | Participant] = (),
    consent_obtained: bool = False,
    consent_note: str = "",
    root: Path | None = None,
    started_at: str | None = None,
) -> Path:
    """Create a meeting directory and its meeting.json.

    The directory name is <date>-<slug>; a second meeting with the same title
    on the same day gets -2, -3 and so on rather than colliding.

    `started_at` is for a recording that happened before now: an ISO-8601 UTC
    timestamp used for both the date in the directory name and the meeting's
    own start time. Without it the clock decides, as it does for a live
    recording. Correcting the start time after creation is not enough — by
    then the directory is already named for today.
    """
    started = started_at or utcnow()
    date = started[:10]
    base = f"{date}-{slugify(title)}"
    parent = meetings_dir(root)
    parent.mkdir(parents=True, exist_ok=True)

    directory = parent / base
    suffix = 2
    while directory.exists():
        directory = parent / f"{base}-{suffix}"
        suffix += 1
    directory.mkdir(parents=True)

    people = [p if isinstance(p, Participant) else Participant(name=str(p)) for p in participants]
    meeting = Meeting(
        id=directory.name,
        title=title,
        started_at=started,
        participants=people,
        consent_obtained=consent_obtained,
        consent_note=consent_note,
    )
    _write_json(directory / "meeting.json", meeting.to_dict())
    return directory


def load_meeting(directory: Path) -> Meeting:
    return Meeting.from_dict(_read_json(Path(directory) / "meeting.json"))


def save_meeting(directory: Path, meeting: Meeting) -> None:
    _write_json(Path(directory) / "meeting.json", meeting.to_dict())


def finalize_meeting(
    directory: Path,
    ended_at: str = "",
    tracks: Iterable[str] = (),
    root: Path | None = None,
) -> Meeting:
    directory = Path(directory)
    meeting = load_meeting(directory)
    meeting.ended_at = ended_at or utcnow()
    if tracks:
        meeting.tracks = [str(t) for t in tracks]
    save_meeting(directory, meeting)
    rebuild_index(root=root)
    return meeting


def latest_meeting(root: Path | None = None) -> Path | None:
    """The most recently started meeting, or None if there are none."""
    candidates = [d for d in meetings_dir(root).glob("*/") if (d / "meeting.json").exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda d: load_meeting(d).started_at)


def resolve_meeting(ref: str | None, root: Path | None = None) -> Path | None:
    """Resolve a user-supplied meeting reference.

    Accepts a directory name, a path, a bare slug, or None meaning 'the most
    recent one'. Partial names match when unambiguous, so `mtg open acme`
    finds 2026-09-05-acme-renewal.
    """
    if not ref:
        return latest_meeting(root)
    direct = Path(ref)
    if (direct / "meeting.json").exists():
        return direct
    parent = meetings_dir(root)
    exact = parent / ref
    if (exact / "meeting.json").exists():
        return exact
    matches = sorted(
        d for d in parent.glob("*/") if (d / "meeting.json").exists() and ref.lower() in d.name.lower()
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return max(matches, key=lambda d: load_meeting(d).started_at)
    return None


def list_meetings(root: Path | None = None) -> list[Meeting]:
    out = [load_meeting(d) for d in meetings_dir(root).glob("*/") if (d / "meeting.json").exists()]
    return sorted(out, key=lambda m: m.started_at, reverse=True)


def rebuild_index(root: Path | None = None) -> Path:
    """Regenerate meetings/index.json purely from what is on disk.

    The index is a convenience for fast lookup and is never the source of
    truth, so a corrupted or deleted index costs nothing.
    """
    parent = meetings_dir(root)
    parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for meeting in list_meetings(root):
        entries.append(
            {
                "id": meeting.id,
                "title": meeting.title,
                "started_at": meeting.started_at,
                "ended_at": meeting.ended_at,
                "participants": [p.name for p in meeting.participants],
                "consent_obtained": meeting.consent_obtained,
                "transcribed": meeting.transcribed,
                "path": f"meetings/{meeting.id}",
            }
        )
    index = parent / "index.json"
    _write_json(index, {"generated_at": utcnow(), "count": len(entries), "meetings": entries})
    return index


# --- contacts --------------------------------------------------------------
#
# A contact file has three regions: frontmatter, a managed meeting list
# delimited by MANAGED_HEADING .. MANAGED_END_MARKER, and everything else,
# which belongs to the human. Only the middle region is ever rewritten.


def contact_path(name: str, root: Path | None = None) -> Path:
    return contacts_dir(root) / f"{slugify(name)}.md"


def _split_managed(body: str) -> tuple[str, list[str], str]:
    """Split a contact body into (before, managed_lines, after).

    A file with no managed block yields ('', [], whole_body) so the caller
    can insert one without disturbing what is already there.
    """
    lines = body.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == MANAGED_HEADING:
            start = i
            break
    if start is None:
        return "", [], body

    end = None
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == MANAGED_END_MARKER:
            end = j
            break
    if end is None:
        # Heading with no end marker: treat only the contiguous list that
        # follows as managed, and hand the rest back to the human. This is
        # the case where someone hand-added a "## Meetings" heading.
        j = start + 1
        while j < len(lines) and (not lines[j].strip() or _MEETING_LINE.match(lines[j])):
            j += 1
        end = j
        managed = [l for l in lines[start + 1 : end] if _MEETING_LINE.match(l)]
        before = "\n".join(lines[:start]).rstrip()
        after = "\n".join(lines[end:]).strip()
        return before, managed, after

    managed = [l for l in lines[start + 1 : end] if _MEETING_LINE.match(l)]
    before = "\n".join(lines[:start]).rstrip()
    after = "\n".join(lines[end + 1 :]).strip()
    return before, managed, after


def _render_contact(meta: dict[str, Any], before: str, managed: list[str], after: str) -> str:
    parts: list[str] = []
    if before.strip():
        parts.append(before.strip())
        parts.append("")
    parts.append(MANAGED_HEADING)
    parts.append("")
    parts.extend(managed if managed else ["_No meetings recorded yet._"])
    parts.append(MANAGED_END_MARKER)
    if after.strip():
        parts.append("")
        parts.append(after.strip())
    return serialise_frontmatter(meta, "\n".join(parts) + "\n")


def link_contact(
    meeting_dir: Path,
    name: str,
    root: Path | None = None,
    **fields: Any,
) -> Path:
    """Add a meeting to a contact's managed list, creating the contact if new.

    Idempotent: linking the same meeting twice leaves exactly one line.
    Everything the human wrote outside the managed block survives untouched.
    """
    meeting_dir = Path(meeting_dir)
    meeting = load_meeting(meeting_dir)
    path = contact_path(name, root)

    if path.exists():
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    else:
        meta, body = {"name": name}, ""

    meta.setdefault("name", name)
    for key, value in fields.items():
        if value:
            meta[key] = value

    before, managed, after = _split_managed(body)
    rel = f"../meetings/{meeting_dir.name}"
    line = f"- [{meeting.started_at[:10]}]({rel}) — {meeting.title}"

    # Identity is the meeting path, not the rendered line, so a retitled
    # meeting updates in place instead of appearing twice.
    kept = [l for l in managed if (m := _MEETING_LINE.match(l)) and m.group("path") != rel]
    kept.append(line)
    kept.sort(key=lambda l: (_MEETING_LINE.match(l).group("date"), l), reverse=True)

    _write_atomic(path, _render_contact(meta, before, kept, after))
    return path


def load_contact(name: str, root: Path | None = None) -> tuple[dict[str, Any], str] | None:
    path = contact_path(name, root)
    if not path.exists():
        return None
    return parse_frontmatter(path.read_text(encoding="utf-8"))


def list_contacts(root: Path | None = None) -> list[str]:
    directory = contacts_dir(root)
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.md"))


def vocabulary(root: Path | None = None) -> list[str]:
    """Every proper noun the CRM knows: contact names, companies, tags.

    Fed to transcription so the names of people you actually talk to are
    spelled correctly. This is the synergy that makes the CRM worth having:
    the more you use it, the better the transcripts get.
    """
    terms: set[str] = set()
    for path in contacts_dir(root).glob("*.md") if contacts_dir(root).exists() else []:
        meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        for key in ("name", "company"):
            if value := meta.get(key):
                terms.add(str(value))
        tags = meta.get("tags") or []
        if isinstance(tags, list):
            terms.update(str(t) for t in tags)
    for meeting in list_meetings(root):
        for person in meeting.participants:
            if person.name:
                terms.add(person.name)
            if person.company:
                terms.add(person.company)
    # Split full names into parts too: "Jane Doe" should also fix a stray "Doe".
    expanded = set(terms)
    for term in terms:
        for part in term.split():
            if len(part) > 3:
                expanded.add(part)
    return sorted(t for t in expanded if t.strip())


def unfinished(root: Path | None = None) -> list[Path]:
    """Meetings whose audio is finished but which were never transcribed.

    On 10 September a real 39-minute call landed here: the recorder shut down
    and wrote its results, but the widget's stop handler never ran, so nothing
    transcribed it, nothing wrote it up and nothing said so. The transcript on
    disk was the mid-call partial and still carried `live: True`.

    A recording that survived is worth rescuing, so the tool has to be able to
    find one rather than wait to be told.
    """
    out = []
    for meeting in list_meetings(root):
        directory = meetings_dir(root) / meeting.id
        state = directory / "recording.json"
        if not state.exists():
            continue                      # never recorded here, or already tidied
        try:
            ended = "ended_at" in _read_json(state)
        except (OSError, ValueError):
            continue
        if not ended:
            continue                      # still recording; leave it alone
        if meeting.transcribed:
            continue
        if _being_transcribed(directory):
            continue
        if any(directory.glob("*.wav")):
            out.append(directory)
    return out


def _being_transcribed(directory: Path) -> bool:
    """Is something already working on this meeting?

    Without this, `mtg finish` races the widget. On 10 September both
    transcribed the same hour of audio at once on the same six cores, because
    a meeting mid-transcription looks exactly like an abandoned one: audio
    present, `transcribed` still false.
    """
    from . import transcribe as tr
    return tr.is_being_transcribed(directory)


def empty_records(root: Path | None = None) -> list[Path]:
    """Meetings with no audio and no transcript: a record and nothing else.

    Four arrived from a Fathom import on this repo, all titled "Impromptu
    Microsoft Teams Meeting", each holding a meeting.json and nothing else.
    They inflate every count, sit permanently in `mtg lane` because there is
    nothing to derive a lane from, and make the corpus look larger than it is.

    They are not deleted here. A record that a call happened has some value,
    and deciding that is the user's. They are reported so the decision can be
    made rather than never noticed.
    """
    out = []
    for meeting in list_meetings(root):
        directory = meetings_dir(root) / meeting.id
        if (directory / "transcript.md").exists():
            continue
        if any(directory.glob("*.wav")) or any(directory.glob("*.mp4")):
            continue
        if (directory / "notes.md").exists() and (directory / "notes.md").stat().st_size:
            continue                      # written up from somewhere else
        out.append(directory)
    return out


def search(query: str, root: Path | None = None) -> list[dict[str, Any]]:
    """Grep transcripts and notes, returning meetings with matching snippets."""
    needle = query.lower()
    results: list[dict[str, Any]] = []
    for meeting in list_meetings(root):
        directory = meetings_dir(root) / meeting.id
        hits: list[str] = []
        for filename in ("notes.md", "transcript.md"):
            path = directory / filename
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if needle in line.lower():
                    hits.append(f"{filename}: {line.strip()[:160]}")
                    if len(hits) >= 5:
                        break
            if len(hits) >= 5:
                break
        if hits:
            results.append({"id": meeting.id, "title": meeting.title,
                            "date": meeting.started_at[:10], "hits": hits})
    return results


# --- import ----------------------------------------------------------------
#
# Meetings recorded elsewhere (Fathom, Otter, a handwritten note) enter the
# CRM through here. The connector lives in the Claude session, which has the
# credentials; this only takes the structured result and files it, so the
# import path is testable without any network.


def find_by_source(source: str, source_id: str, root: Path | None = None) -> Path | None:
    """Locate an already-imported meeting, so importing twice is a no-op."""
    for directory in meetings_dir(root).glob("*/"):
        meta = directory / "meeting.json"
        if not meta.exists():
            continue
        try:
            data = _read_json(meta)
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("source") == source and str(data.get("source_id")) == str(source_id):
            return directory
    return None


def import_meeting(
    title: str,
    date: str,
    participants: Iterable[str | dict[str, Any]] = (),
    transcript_md: str = "",
    summary_md: str = "",
    source: str = "import",
    source_id: str = "",
    source_url: str = "",
    consent_note: str = "",
    root: Path | None = None,
) -> tuple[Path, bool]:
    """File a meeting that was recorded somewhere else.

    Returns (directory, created). Re-importing the same source_id updates the
    existing folder rather than making a second copy of the same call.
    """
    existing = find_by_source(source, source_id, root) if source_id else None
    created = existing is None

    people: list[Participant] = []
    for person in participants:
        if isinstance(person, dict):
            people.append(Participant(
                name=person.get("name") or person.get("email", "").split("@")[0],
                email=person.get("email", ""),
                company=person.get("company", ""),
            ))
        elif person:
            name = str(person)
            people.append(Participant(name=name.split("@")[0] if "@" in name else name,
                                      email=name if "@" in name else ""))

    if existing is not None:
        directory = existing
        meeting = load_meeting(directory)
        meeting.title = title or meeting.title
        if people:
            meeting.participants = people
    else:
        parent = meetings_dir(root)
        parent.mkdir(parents=True, exist_ok=True)
        base = f"{date}-{slugify(title)}"
        directory = parent / base
        suffix = 2
        while directory.exists():
            directory = parent / f"{base}-{suffix}"
            suffix += 1
        directory.mkdir(parents=True)
        meeting = Meeting(
            id=directory.name,
            title=title,
            started_at=f"{date}T00:00:00Z",
            ended_at=f"{date}T00:00:00Z",
            participants=people,
            # Consent for an imported meeting was handled by whatever recorded
            # it. Recording that honestly beats asserting consent we cannot
            # vouch for.
            consent_obtained=True,
            consent_note=consent_note or f"recorded via {source}; consent handled there",
        )

    meeting.transcribed = bool(transcript_md)
    meeting.transcript_engine = source
    data = meeting.to_dict()
    data["source"] = source
    data["source_id"] = str(source_id)
    data["source_url"] = source_url
    data["imported"] = True
    _write_json(directory / "meeting.json", data)

    if transcript_md:
        header = [
            "---",
            f"source: {source}",
            f"source_url: {source_url}",
            f"date: {date}",
            "speaker_method: imported from source; attribution as recorded there",
            "---",
            "",
            "<!-- Imported. Do not edit; write notes.md instead. -->",
            "",
        ]
        (directory / "transcript.md").write_text(
            "\n".join(header) + transcript_md.strip() + "\n", encoding="utf-8"
        )

    if summary_md:
        # A summary written by the source service. It fills the notes slot
        # until Claude writes a better one from a transcript, and says so in
        # its header rather than passing itself off as Claude-authored.
        (directory / "notes.md").write_text(
            f"# {meeting.title}\n\n"
            f"> Imported from {source} on {utcnow()[:10]}. This is "
            f"{source}'s own summary, not a Claude write-up.\n"
            f"> Run `/notes {directory.name}` after pulling the transcript "
            f"to regenerate it.\n\n"
            + summary_md.strip() + "\n",
            encoding="utf-8",
        )

    for person in meeting.participants:
        if person.name:
            link_contact(directory, person.name, root=root,
                         email=person.email, company=person.company)

    return directory, created


def import_batch(meetings: list[dict[str, Any]], root: Path | None = None) -> dict[str, int]:
    """Import many meetings; returns counts of created and updated."""
    created = updated = 0
    for entry in meetings:
        _, was_created = import_meeting(
            title=entry.get("title", "Untitled"),
            date=entry.get("date", "1970-01-01"),
            participants=entry.get("participants", []),
            transcript_md=entry.get("transcript_md", ""),
            summary_md=entry.get("summary_md", ""),
            source=entry.get("source", "import"),
            source_id=entry.get("source_id", ""),
            source_url=entry.get("source_url", ""),
            root=root,
        )
        created += was_created
        updated += not was_created
    rebuild_index(root=root)
    return {"created": created, "updated": updated}


# --- calendar --------------------------------------------------------------
#
# The recorder has no way to know a meeting is starting; nothing joins the
# call. A synced calendar closes that gap: it supplies the title and the
# attendee list so `mtg start` does not have to be typed out, and those
# attendee names feed the transcript name corrector.
#
# As with the importer, the connector lives in the Claude session. This side
# only reads a JSON file, so it works offline and is testable.

CALENDAR_FILE = "calendar.json"


def calendar_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / CALENDAR_FILE


def save_calendar(events: list[dict[str, Any]], root: Path | None = None) -> Path:
    """Store upcoming events, newest sync wins."""
    path = calendar_path(root)
    cleaned = []
    for event in events:
        cleaned.append({
            "subject": event.get("subject", "").strip() or "Meeting",
            "start": event.get("start", ""),
            "end": event.get("end", ""),
            "attendees": [a for a in event.get("attendees", []) if a],
            "organizer": event.get("organizer", ""),
            "location": event.get("location", ""),
        })
    cleaned.sort(key=lambda e: e["start"])
    _write_json(path, {"synced_at": utcnow(), "events": cleaned})
    return path


def load_calendar(root: Path | None = None) -> list[dict[str, Any]]:
    path = calendar_path(root)
    if not path.exists():
        return []
    try:
        return _read_json(path).get("events", [])
    except (OSError, json.JSONDecodeError):
        return []


def _parse_iso(value: str):
    from datetime import datetime, timezone as tz

    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=tz.utc) if parsed.tzinfo is None else parsed


def upcoming(limit: int = 5, root: Path | None = None) -> list[dict[str, Any]]:
    """Events that have not finished yet."""
    from datetime import datetime, timezone as tz

    now = datetime.now(tz.utc)
    out = []
    for event in load_calendar(root):
        end = _parse_iso(event.get("end", "")) or _parse_iso(event.get("start", ""))
        if end and end >= now:
            out.append(event)
    return out[:limit]


def current_or_next(window_minutes: int = 15, root: Path | None = None):
    """The meeting to record right now.

    Matches one already running, or one starting within the window, so
    `mtg start --next` picks the obvious meeting without being told which.
    """
    from datetime import datetime, timedelta, timezone as tz

    now = datetime.now(tz.utc)
    soon = now + timedelta(minutes=window_minutes)
    for event in upcoming(limit=20, root=root):
        start = _parse_iso(event.get("start", ""))
        end = _parse_iso(event.get("end", ""))
        if not start:
            continue
        if start <= now and (end is None or end >= now):
            return event                      # in progress
        if now <= start <= soon:
            return event                      # about to begin
    return None


def contact_by_email(email: str, root: Path | None = None) -> str:
    """The known name for an address, or "" if the CRM has never seen it."""
    if not email:
        return ""
    directory = contacts_dir(root)
    if not directory.exists():
        return ""
    wanted = email.strip().lower()
    for path in directory.glob("*.md"):
        meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        if str(meta.get("email", "")).strip().lower() == wanted:
            return str(meta.get("name", "")) or path.stem
    return ""


def attendee_names(event: dict[str, Any], me: str = "",
                   root: Path | None = None) -> list[str]:
    """Attendees as display names, excluding the user.

    Resolves against the CRM first, so a known address becomes the real
    name. Falls back to the address's local part, which is honest about what
    the calendar actually told us rather than inventing a name.
    """
    names = []
    for entry in event.get("attendees", []):
        if me and entry.lower() == me.lower():
            continue
        if "@" not in entry:
            names.append(entry)
            continue
        known = contact_by_email(entry, root)
        if known:
            names.append(known)
        else:
            local = entry.split("@")[0]
            names.append(re.sub(r"[._-]+", " ", local).title())
    return names
