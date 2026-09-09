"""Data types and the tiny frontmatter format used across the CRM.

Stdlib only, by design: the whole store is plain markdown and JSON so that
Claude (and grep, and the user) can read it without any tooling.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

MAX_SLUG_LEN = 60


def utcnow() -> str:
    """An ISO-8601 timestamp in UTC, second precision, always suffixed Z."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(text: str, max_len: int = MAX_SLUG_LEN) -> str:
    """Filesystem-safe slug.

    Transliterates unicode to ASCII, collapses runs of punctuation into single
    hyphens, and trims to max_len on a word boundary where possible. Returns
    'untitled' rather than an empty string, so a slug is always a usable
    path segment.
    """
    if not text:
        return "untitled"
    # NFKD then drop combining marks: "Ámir Tàylor" -> "Amir Taylor"
    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in normalised if not unicodedata.combining(c))
    ascii_text = ascii_text.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    if not slug:
        return "untitled"
    if len(slug) > max_len:
        cut = slug[:max_len]
        # Prefer not to end mid-word, but never return an empty result.
        if "-" in cut[1:]:
            cut = cut[: cut.rindex("-")]
        slug = cut.strip("-") or slug[:max_len].strip("-")
    return slug or "untitled"


# --- frontmatter -----------------------------------------------------------
#
# A deliberately small subset of YAML: `key: value` scalars and `key: [a, b]`
# inline lists. Values round-trip through JSON when they contain anything
# that would need quoting, which keeps the parser honest about colons,
# quotes and unicode without pulling in pyyaml.

_FM_DELIM = "---"


def _fm_encode_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    if value is None:
        return ""
    text = str(value)
    # Quote anything that would confuse a naive reader or a real YAML parser.
    if text != text.strip() or re.search(r'^[\[\{>|&*!%@`"\']|:\s|\n|#', text):
        return json.dumps(text, ensure_ascii=False)
    return text


def _fm_decode_value(raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return ""
    if raw in ("true", "false"):
        return raw == "true"
    if raw.startswith(("[", '"', "{")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d*\.\d+", raw):
        return float(raw)
    return raw


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a document into (frontmatter dict, body).

    A document with no frontmatter returns ({}, original_text) — never raises,
    because a hand-edited contact file must always remain readable.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FM_DELIM:
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == _FM_DELIM:
            meta: dict[str, Any] = {}
            for line in lines[1:i]:
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                key, sep, raw = line.partition(":")
                if not sep:
                    continue
                meta[key.strip()] = _fm_decode_value(raw)
            body = "\n".join(lines[i + 1 :])
            return meta, body.lstrip("\n")
    # Unterminated frontmatter: treat the whole thing as body rather than
    # silently swallowing the user's content.
    return {}, text


def serialise_frontmatter(meta: dict[str, Any], body: str) -> str:
    if not meta:
        return body
    out = [_FM_DELIM]
    for key, value in meta.items():
        out.append(f"{key}: {_fm_encode_value(value)}")
    out.append(_FM_DELIM)
    out.append("")
    out.append(body.lstrip("\n"))
    return "\n".join(out)


# --- records ---------------------------------------------------------------


@dataclass
class Participant:
    name: str
    email: str = ""
    company: str = ""
    role: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Participant":
        return cls(
            name=d.get("name", ""),
            email=d.get("email", ""),
            company=d.get("company", ""),
            role=d.get("role", ""),
        )

    @property
    def slug(self) -> str:
        return slugify(self.name)


@dataclass
class Meeting:
    id: str
    title: str
    started_at: str
    ended_at: str = ""
    participants: list[Participant] = field(default_factory=list)
    consent_obtained: bool = False
    consent_note: str = ""
    tracks: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    transcribed: bool = False
    transcript_engine: str = ""
    #: "business", "personal" or "" for undecided. Set by hand when the
    #: export's heuristic gets it wrong; see notetaker/hubexport.py.
    lane: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["participants"] = [p.to_dict() for p in self.participants]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Meeting":
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            started_at=d.get("started_at", ""),
            ended_at=d.get("ended_at", ""),
            participants=[Participant.from_dict(p) for p in d.get("participants", [])],
            consent_obtained=bool(d.get("consent_obtained", False)),
            consent_note=d.get("consent_note", ""),
            tracks=list(d.get("tracks", [])),
            tags=list(d.get("tags", [])),
            transcribed=bool(d.get("transcribed", False)),
            transcript_engine=d.get("transcript_engine", ""),
            lane=d.get("lane", ""),
        )


@dataclass
class Contact:
    name: str
    email: str = ""
    company: str = ""
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    meetings: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return slugify(self.name)
