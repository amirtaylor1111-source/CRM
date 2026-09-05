"""Presentation logic for the desktop app, kept free of any UI toolkit.

Separated so the parts that decide what the window should say can be tested
on a machine with no display, which is most machines a developer works on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

IDLE = "idle"
RECORDING = "recording"
TRANSCRIBING = "transcribing"
DONE = "done"
ERROR = "error"


def elapsed_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def friendly_when(iso: str) -> str:
    """'Today 12:30', 'Tomorrow 09:00', or 'Mon 15 Sep 09:30'."""
    from datetime import datetime, timedelta, timezone

    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:16].replace("T", " ")
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone()
    today = datetime.now(local.tzinfo).date()
    delta = (local.date() - today).days
    clock = local.strftime("%H:%M")
    if delta == 0:
        return f"Today {clock}"
    if delta == 1:
        return f"Tomorrow {clock}"
    if 0 < delta < 7:
        return local.strftime(f"%A {clock}")
    return local.strftime(f"%a %d %b {clock}")


@dataclass
class Suggestion:
    """What the window should pre-fill, and why."""
    title: str = ""
    participants: list[str] = field(default_factory=list)
    when: str = ""
    source: str = ""          # "calendar" or "" when nothing was found

    @property
    def participants_text(self) -> str:
        return ", ".join(self.participants)

    @property
    def headline(self) -> str:
        if not self.title:
            return "No meeting scheduled"
        when = friendly_when(self.when)
        return f"{self.title} — {when}" if when else self.title


def suggest(store_module, window_minutes: int = 30, me: str = "") -> Suggestion:
    """Pre-fill from the calendar when a meeting is due, else leave it blank.

    A wider window than the CLI uses: someone opening the app is usually
    about to take the call, so reaching a little further forward is helpful
    rather than presumptuous.
    """
    event = store_module.current_or_next(window_minutes=window_minutes)
    if event is None:
        upcoming = store_module.upcoming(limit=1)
        if not upcoming:
            return Suggestion()
        event = upcoming[0]
        return Suggestion(
            title="",                       # too far off to assume
            participants=[],
            when=event.get("start", ""),
            source="calendar-later",
        )
    return Suggestion(
        title=event.get("subject", ""),
        participants=store_module.attendee_names(event, me=me),
        when=event.get("start", ""),
        source="calendar",
    )


def can_start(state: str, consent_given: bool, solo: bool) -> bool:
    """The start button is live only once consent is settled.

    Enforced in the UI as well as the CLI, so the disclosure is not
    something the graphical path quietly skips.
    """
    return state == IDLE and (consent_given or solo)


def status_line(state: str, started_at: float = 0.0, detail: str = "") -> str:
    if state == RECORDING:
        return f"Recording  {elapsed_text(time.time() - started_at)}"
    if state == TRANSCRIBING:
        return detail or "Transcribing..."
    if state == DONE:
        return "Done — open Claude Code and run /notes"
    if state == ERROR:
        return detail or "Something went wrong"
    return "Ready"


def button_label(state: str) -> str:
    return {
        IDLE: "Start recording",
        RECORDING: "Stop",
        TRANSCRIBING: "Working...",
        DONE: "Start recording",
        ERROR: "Try again",
    }.get(state, "Start recording")


def recent_lines(store_module, limit: int = 6) -> list[str]:
    out = []
    for meeting in store_module.list_meetings()[:limit]:
        mark = "✓" if meeting.transcribed else "·"
        people = ", ".join(p.name for p in meeting.participants)
        label = f"{mark}  {meeting.started_at[:10]}  {meeting.title}"
        if people:
            label += f"  ({people})"
        out.append(label[:70])
    return out
