"""The desktop window.

A meeting recorder should be one button. Typing commands while someone is
waiting on the call is the wrong shape for the job, so this is the front door
and the CLI is the back one — both drive exactly the same code underneath.

Tkinter, because it ships with the standard Windows Python installer and
therefore costs the user nothing extra to install.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import capture, hardware, store, uistate

BG = "#1c1c1e"
CARD = "#2c2c2e"
FG = "#f2f2f7"
MUTED = "#9a9aa0"
ACCENT = "#0a84ff"
DANGER = "#ff453a"
OK = "#32d74b"


class App:
    def __init__(self, root):
        self.root = root
        self.state = uistate.IDLE
        self.meeting_dir: Path | None = None
        self.started_at = 0.0
        self.detail = ""
        self.events: queue.Queue = queue.Queue()

        root.title("Meeting Notetaker")
        root.configure(bg=BG)
        root.geometry("480x620")
        root.minsize(420, 560)

        self._build()
        self._refresh_suggestion()
        self._tick()

    # --- layout ------------------------------------------------------------

    def _build(self):
        import tkinter as tk

        pad = {"padx": 20}

        tk.Label(self.root, text="Meeting Notetaker", bg=BG, fg=FG,
                 font=("Segoe UI", 17, "bold")).pack(anchor="w", pady=(18, 2), **pad)
        self.next_label = tk.Label(self.root, text="", bg=BG, fg=MUTED,
                                   font=("Segoe UI", 10), anchor="w", justify="left")
        self.next_label.pack(anchor="w", pady=(0, 14), **pad)

        # --- what is being recorded
        card = tk.Frame(self.root, bg=CARD)
        card.pack(fill="x", pady=(0, 12), **pad)

        tk.Label(card, text="Meeting", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(12, 2))
        self.title_var = tk.StringVar()
        self.title_entry = tk.Entry(card, textvariable=self.title_var, bg=BG, fg=FG,
                                    insertbackground=FG, relief="flat",
                                    font=("Segoe UI", 11))
        self.title_entry.pack(fill="x", padx=14, ipady=6)

        tk.Label(card, text="With", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(10, 2))
        self.people_var = tk.StringVar()
        self.people_entry = tk.Entry(card, textvariable=self.people_var, bg=BG, fg=FG,
                                     insertbackground=FG, relief="flat",
                                     font=("Segoe UI", 11))
        self.people_entry.pack(fill="x", padx=14, ipady=6, pady=(0, 14))

        # --- consent, enforced here as well as in the CLI
        consent = tk.Frame(self.root, bg=CARD)
        consent.pack(fill="x", pady=(0, 12), **pad)
        tk.Label(consent, text="Say this before you start",
                 bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=14,
                                                               pady=(12, 4))
        tk.Label(consent, text=f'"{capture_disclosure()}"', bg=CARD, fg=FG,
                 font=("Segoe UI", 10, "italic"), wraplength=380,
                 justify="left").pack(anchor="w", padx=14)

        self.consent_var = tk.BooleanVar(value=False)
        self.solo_var = tk.BooleanVar(value=False)
        tk.Checkbutton(consent, text="I've told them", variable=self.consent_var,
                       command=self._sync_button, bg=CARD, fg=FG, selectcolor=BG,
                       activebackground=CARD, activeforeground=FG, relief="flat",
                       font=("Segoe UI", 10)).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Checkbutton(consent, text="Just me — nobody else on the call",
                       variable=self.solo_var, command=self._sync_button,
                       bg=CARD, fg=MUTED, selectcolor=BG, activebackground=CARD,
                       activeforeground=FG, relief="flat",
                       font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(0, 12))

        # --- the button
        self.button = tk.Button(self.root, text="Start recording", command=self._primary,
                                bg=ACCENT, fg="white", relief="flat",
                                font=("Segoe UI", 13, "bold"),
                                activebackground=ACCENT, activeforeground="white",
                                cursor="hand2", bd=0)
        self.button.pack(fill="x", ipady=13, pady=(4, 8), **pad)

        self.status = tk.Label(self.root, text="Ready", bg=BG, fg=MUTED,
                               font=("Segoe UI", 10))
        self.status.pack(pady=(0, 10))

        # --- history
        tk.Label(self.root, text="Recent", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", **pad)
        self.recent = tk.Listbox(self.root, bg=CARD, fg=FG, relief="flat",
                                 font=("Consolas", 9), selectbackground=ACCENT,
                                 highlightthickness=0, activestyle="none")
        self.recent.pack(fill="both", expand=True, pady=(4, 10), **pad)
        self.recent.bind("<Double-Button-1>", lambda e: self._open_selected())

        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", pady=(0, 14), **pad)
        for text, command in (("Open folder", self._open_folder),
                              ("Check setup", self._doctor)):
            tk.Button(footer, text=text, command=command, bg=BG, fg=MUTED,
                      relief="flat", font=("Segoe UI", 9), bd=0, cursor="hand2",
                      activebackground=BG, activeforeground=FG).pack(side="left",
                                                                     padx=(0, 14))
        self._sync_button()
        self._load_recent()

    # --- state -------------------------------------------------------------

    def _refresh_suggestion(self):
        try:
            import os

            suggestion = uistate.suggest(store, me=os.environ.get("MTG_ME", ""))
        except Exception:
            suggestion = uistate.Suggestion()
        self.next_label.config(text=suggestion.headline)
        if suggestion.title and not self.title_var.get():
            self.title_var.set(suggestion.title)
        if suggestion.participants and not self.people_var.get():
            self.people_var.set(suggestion.participants_text)

    def _load_recent(self):
        self.recent.delete(0, "end")
        try:
            for line in uistate.recent_lines(store):
                self.recent.insert("end", line)
        except Exception:
            pass

    def _sync_button(self):
        self.button.config(text=uistate.button_label(self.state))
        if self.state == uistate.RECORDING:
            self.button.config(bg=DANGER, state="normal", activebackground=DANGER)
        elif self.state == uistate.TRANSCRIBING:
            self.button.config(bg=CARD, state="disabled")
        else:
            allowed = uistate.can_start(self.state if self.state != uistate.DONE
                                        else uistate.IDLE,
                                        self.consent_var.get(), self.solo_var.get())
            self.button.config(bg=ACCENT if allowed else CARD,
                               state="normal" if allowed else "disabled",
                               activebackground=ACCENT)

    def _tick(self):
        """Drive the clock and drain worker messages on the UI thread."""
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "detail":
                self.detail = payload
            elif kind == "done":
                self.state = uistate.DONE
                self.detail = ""
                self._load_recent()
            elif kind == "error":
                self.state = uistate.ERROR
                self.detail = payload

        self.status.config(text=uistate.status_line(self.state, self.started_at,
                                                    self.detail),
                           fg=OK if self.state == uistate.DONE else MUTED)
        self._sync_button()
        self.root.after(400, self._tick)

    # --- actions -----------------------------------------------------------

    def _primary(self):
        if self.state == uistate.RECORDING:
            self._stop()
        else:
            self._start()

    def _start(self):
        people = [p.strip() for p in self.people_var.get().split(",") if p.strip()]
        title = self.title_var.get().strip() or (
            f"Call with {people[0]}" if people else "Meeting")

        try:
            self.meeting_dir = store.create_meeting(
                title, people,
                consent_obtained=self.consent_var.get(),
                consent_note=("participants informed" if self.consent_var.get()
                              else "solo recording; no other participants"),
            )
        except OSError as exc:
            self.state = uistate.ERROR
            self.detail = f"Could not create the meeting folder: {exc}"
            return

        child = [_python(), "-m", "notetaker.cli", "_record", str(self.meeting_dir)]
        try:
            subprocess.Popen(child, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, cwd=str(store.repo_root()),
                             creationflags=_no_window())
        except OSError as exc:
            self.state = uistate.ERROR
            self.detail = str(exc)
            return

        self.started_at = time.time()
        self.state = uistate.RECORDING

    def _stop(self):
        self.state = uistate.TRANSCRIBING
        self.detail = "Stopping..."
        threading.Thread(target=self._finish, daemon=True).start()

    def _finish(self):
        """Stop, transcribe, file. Runs off the UI thread so the window lives."""
        try:
            tracks = capture.stop_recording(self.meeting_dir)
            if not tracks:
                self.events.put(("error", "No audio captured — try Check setup"))
                return
            store.finalize_meeting(self.meeting_dir, tracks=tracks)

            from . import transcribe as tr

            seconds = sum(capture.audio_duration(Path(t)) for t in tracks
                          if t.endswith(".wav"))
            choice = hardware.recommend()
            self.events.put(("detail",
                             f"Transcribing — {hardware.format_estimate(seconds, choice)}"))

            tr.transcribe_meeting(
                self.meeting_dir,
                vocabulary=store.vocabulary(),
                progress=lambda msg: self.events.put(("detail", str(msg)[:60])),
            )

            meeting = store.load_meeting(self.meeting_dir)
            meeting.transcribed = True
            store.save_meeting(self.meeting_dir, meeting)
            for person in meeting.participants:
                store.link_contact(self.meeting_dir, person.name)
            store.rebuild_index()
            self.events.put(("done", ""))
        except Exception as exc:
            self.events.put(("error", str(exc)[:80]))

    def _open_folder(self):
        target = self.meeting_dir or store.repo_root()
        _reveal(target)

    def _open_selected(self):
        selection = self.recent.curselection()
        if not selection:
            return
        meetings = store.list_meetings()
        if selection[0] < len(meetings):
            _reveal(store.meetings_dir() / meetings[selection[0]].id)

    def _doctor(self):
        import tkinter as tk

        window = tk.Toplevel(self.root)
        window.title("Setup check")
        window.configure(bg=BG)
        window.geometry("560x360")
        text = tk.Text(window, bg=CARD, fg=FG, relief="flat", font=("Consolas", 9),
                       wrap="word")
        text.pack(fill="both", expand=True, padx=14, pady=14)
        text.insert("end", "Checking...\n")

        def run():
            result = subprocess.run([_python(), "-m", "notetaker.cli", "doctor"],
                                    capture_output=True, text=True,
                                    cwd=str(store.repo_root()),
                                    creationflags=_no_window())
            text.delete("1.0", "end")
            text.insert("end", (result.stdout or "") + (result.stderr or ""))

        self.root.after(50, run)


def capture_disclosure() -> str:
    from .cli import DISCLOSURE

    return DISCLOSURE


def _python() -> str:
    """The console interpreter, even when the app runs under pythonw."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        candidate = exe.with_name("python.exe")
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _no_window() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _reveal(path: Path) -> None:
    path = Path(path)
    try:
        if sys.platform == "win32":
            import os

            os.startfile(str(path))            # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def main() -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("The desktop app needs tkinter, which ships with the standard "
              "Python installer.\nReinstall Python from python.org with the "
              "'tcl/tk and IDLE' option ticked, or use `mtg start` instead.")
        return 2

    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
