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
        os.replace(tmp, path)
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
) -> Path:
    """Create a meeting directory and its meeting.json.

    The directory name is <date>-<slug>; a second meeting with the same title
    on the same day gets -2, -3 and so on rather than colliding.
    """
    started = utcnow()
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
