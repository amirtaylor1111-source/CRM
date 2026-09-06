"""The always-on-top widget: the app's window, owned by Python.

The page is the same local HTML the Edge window shows; what changes is who
owns the window. pywebview (Windows' own WebView2 engine) gives a frameless
window that stays on top, drags by its pill, collapses to a strip at a
screen edge, and, because Python holds the window handle, can be excluded
from screen capture. That last part is why the widget exists at all: a
window showing "questions to ask them" must never appear in a screen share.

It replaces the calendar watcher as the thing that runs from login: the
server's calendar poll expands the pill when a meeting is due, and the
consent switch and Start button do the rest, as they always have.

If pywebview or WebView2 is missing, `main()` logs it and runs the Edge
window instead, so the user is never without a way to record.
"""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from pathlib import Path

from . import log, server

_log = log.get("widget")

TITLE = "Meeting Notetaker"
WIDTH = 380
PILL_HEIGHT = 64
EXPANDED_HEIGHT = 700
MARGIN = 16

WDA_EXCLUDEFROMCAPTURE = 0x11
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000


# --- pure parts, tested without a window -----------------------------------


# All geometry below is in logical pixels (DIPs), which is what pywebview
# takes and reports; it scales by the display's DPI itself. On this laptop
# that is 150%, so a 380-wide request is a 570-pixel window.


def expanded_height(work_area) -> int:
    """As tall as designed, or as tall as the screen allows."""
    left, top, right, bottom = work_area
    return max(PILL_HEIGHT * 4, min(EXPANDED_HEIGHT, bottom - top - 2 * MARGIN))


def size_for(expanded: bool, work_area=None) -> tuple[int, int]:
    tall = expanded_height(work_area) if work_area else EXPANDED_HEIGHT
    return WIDTH, (tall if expanded else PILL_HEIGHT)


def default_position(work_area: tuple[int, int, int, int], expanded: bool) -> tuple[int, int]:
    """Bottom-right of the work area (the screen minus the taskbar)."""
    left, top, right, bottom = work_area
    width, height = size_for(expanded, work_area)
    return max(left, right - width - MARGIN), max(top, bottom - height - MARGIN)


def reshaped_position(x: int, y: int, was_expanded: bool, work_area) -> tuple[int, int]:
    """Keep the bottom edge where it is when the height changes, and stay on screen."""
    old_h = size_for(was_expanded, work_area)[1]
    new_h = size_for(not was_expanded, work_area)[1]
    left, top, right, bottom = work_area
    ny = y + old_h - new_h
    ny = min(max(top, ny), bottom - new_h)
    nx = min(max(left, x), right - WIDTH)
    return nx, ny


def clamped_position(x: int, y: int, expanded: bool, work_area) -> tuple[int, int]:
    """A saved position, kept on screen for the shape being opened."""
    left, top, right, bottom = work_area
    width, height = size_for(expanded, work_area)
    return (min(max(left, x), max(left, right - width)),
            min(max(top, y), max(top, bottom - height)))


def settings_path() -> Path:
    return log.log_dir() / "widget.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    try:
        settings_path().parent.mkdir(parents=True, exist_ok=True)
        settings_path().write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def dpi_scale(user32=None) -> float:
    """Physical pixels per logical pixel, once the process is DPI-aware."""
    user32 = user32 or _user32()
    try:
        return max(1.0, user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


def work_area(user32=None, scale: float | None = None) -> tuple[int, int, int, int]:
    """The primary monitor minus the taskbar, in logical pixels."""
    user32 = user32 or _user32()
    if user32 is None:
        return (0, 0, 1920, 1040)
    scale = scale or dpi_scale(user32)
    rect = ctypes.wintypes.RECT()
    if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):     # SPI_GETWORKAREA
        physical = (rect.left, rect.top, rect.right, rect.bottom)
    else:
        physical = (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    return tuple(int(v / scale) for v in physical)


def hide_from_capture(hwnd: int, user32=None) -> bool:
    """Exclude the window from screen capture and from the taskbar.

    SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) makes the window
    invisible to screen sharing and recording while it stays visible on the
    monitor; verified on this laptop. The tool-window style keeps a
    Grammarly-style strip out of the taskbar and Alt-Tab.
    """
    user32 = user32 or _user32()
    if user32 is None or not hwnd:
        return False
    ok = bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
    # SWP_FRAMECHANGED makes the shell re-read the style; hiding and
    # re-showing the window from this thread wedged WebView2 on the laptop.
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0020 | 0x0040)   # topmost, frame changed, show
    if ok and hasattr(user32, "GetWindowDisplayAffinity"):
        affinity = ctypes.c_uint(0)
        user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
        ok = affinity.value == WDA_EXCLUDEFROMCAPTURE
    return ok


def native_handle(window) -> int:
    """The HWND from pywebview's own window object, when the backend has one."""
    try:
        handle = window.native.Handle
        return int(handle.ToInt64()) if hasattr(handle, "ToInt64") else int(handle)
    except Exception:
        return 0


def bring_to_front(title: str, user32=None) -> bool:
    """Show an already-running widget instead of starting a second one."""
    user32 = user32 or _user32()
    if user32 is None:
        return False
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)                 # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True


def window_size(hwnd: int, user32=None) -> tuple[int, int]:
    user32 = user32 or _user32()
    if user32 is None or not hwnd:
        return (0, 0)
    rect = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (0, 0)
    return (rect.right - rect.left, rect.bottom - rect.top)


def find_window(title: str, user32=None, pid: int | None = None) -> int:
    """This process's top-level window with that title, or 0.

    Only this process: an Edge window showing the same page has the same
    title, and styles applied to it would fail or, worse, take.
    """
    user32 = user32 or _user32()
    if user32 is None:
        return 0
    import ctypes.wintypes as wt

    own = pid if pid is not None else ctypes.windll.kernel32.GetCurrentProcessId()
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    found = []

    def visit(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == own:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == title:
                found.append(int(hwnd))
        return True

    for _ in range(40):                     # the window appears a moment after start
        user32.EnumWindows(proto(visit), 0)
        if found:
            return found[0]
        time.sleep(0.1)
    return 0


def _user32():
    if sys.platform != "win32":
        return None
    import ctypes.wintypes  # noqa: F401  (registers the RECT type)

    return ctypes.windll.user32


def make_dpi_aware() -> bool:
    """Measure and place the window in physical pixels, like pywebview does.

    Without this the process sees a 150%-scaled laptop screen as 1280x720
    while the window is placed in 1920x1080 coordinates, and the widget ends
    up half off the top of the screen with a saved position to match.
    Must run before anything asks the screen its size.
    """
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return True
        except Exception:
            return False


# --- the window ------------------------------------------------------------


class Api:
    """What the page can call: window.pywebview.api.<name>()."""

    def __init__(self, widget: "Widget"):
        self._w = widget

    def collapse(self):
        self._w.collapse()

    def expand(self):
        self._w.expand()

    def toggle(self):
        self._w.expand() if not self._w.expanded else self._w.collapse()

    def quit(self) -> bool:
        """Refused while a meeting is in progress: the recorder would keep
        the microphone open with nothing on screen to say so."""
        state = getattr(getattr(self._w, "session", None), "state", "")
        if state in ("recording", "transcribing", "writing"):
            return False
        self._w.quit()
        return True

    def shape(self) -> str:
        return "expanded" if self._w.expanded else "pill"


class Widget:
    def __init__(self, url: str, session: server.Session, webview_module=None):
        self.url = url
        self.session = session
        self.webview = webview_module
        self.window = None
        self.expanded = False              # a strip until there is something to say
        self.scale = dpi_scale()
        self.area = work_area(scale=self.scale)
        settings = load_settings()
        self.x = int(settings.get("x", -1))
        self.y = int(settings.get("y", -1))
        if self.x < 0 or self.y < 0:
            self.x, self.y = default_position(self.area, expanded=False)
        else:
            self.x, self.y = clamped_position(self.x, self.y, False, self.area)
        self.hwnd = 0

    def run(self) -> None:
        width, height = size_for(self.expanded, self.area)
        self.window = self.webview.create_window(
            TITLE, self.url, width=width, height=height, x=self.x, y=self.y,
            frameless=True, on_top=True, easy_drag=False, js_api=Api(self),
            background_color="#0b0c10", min_size=(WIDTH, PILL_HEIGHT))
        try:
            self.window.events.moved += self._on_moved
        except Exception:
            pass
        self.session.window = {"collapse": self.collapse, "expand": self.expand,
                               "toggle": Api(self).toggle, "quit": self.quit}
        self.webview.start(self._on_shown, self.window, gui="edgechromium", private_mode=False)

    def _on_shown(self, window) -> None:
        """Runs on pywebview's worker thread once the GUI loop is up. The
        form may still be laying itself out, so wait until it is visible and
        has a size before touching its styles, and verify what took."""
        user32 = _user32()
        for _ in range(40):                          # pywebview sets .native a moment later
            self.hwnd = native_handle(window)
            if self.hwnd:
                break
            time.sleep(0.1)
        self.hwnd = self.hwnd or find_window(TITLE)
        if not self.hwnd or user32 is None:
            _log.warning("could not find the window handle; capture exclusion not applied")
            return
        for _ in range(20):                          # up to 5 s; then apply regardless
            if (user32.IsWindowVisible(self.hwnd)
                    and window_size(self.hwnd, user32)[0] >= WIDTH * self.scale * 0.9):
                break
            time.sleep(0.25)
        hidden = hide_from_capture(self.hwnd, user32)
        if not hidden:
            _log.warning("SetWindowDisplayAffinity failed (error %s)", ctypes.get_last_error())
        _log.info("window %s size=%s; hidden from capture: %s", hex(self.hwnd),
                  window_size(self.hwnd, user32), hidden)
        self.session.capture_hidden = hidden

    def _on_moved(self, x, y) -> None:
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            return
        left, top, right, bottom = self.area
        if not (left - WIDTH < x < right and top - PILL_HEIGHT < y < bottom):
            return                                 # off screen: not a position to keep
        self.x, self.y = x, y
        save_settings({"x": self.x, "y": self.y})

    def _reshape(self, expanded: bool) -> None:
        if self.window is None or expanded == self.expanded:
            return
        nx, ny = reshaped_position(self.x, self.y, self.expanded, self.area)
        self.expanded = expanded
        width, height = size_for(expanded, self.area)
        try:
            self.window.resize(width, height)
            self.window.move(nx, ny)
            self.x, self.y = nx, ny
            self.window.evaluate_js(f"window.setShape && setShape({json.dumps('expanded' if expanded else 'pill')})")
        except Exception:
            _log.exception("reshape failed")

    def collapse(self) -> None:
        self._reshape(False)

    def expand(self) -> None:
        self._reshape(True)
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass

    def quit(self) -> None:
        try:
            self.window.destroy()
        except Exception:
            pass


def main() -> int:
    log.setup()
    running = server._running_instance()
    if running:
        _log.info("the widget is already running; bringing it forward")
        # If there is no widget window to raise, the instance holding the
        # port is the Edge fallback. Open its page, or a second click on the
        # shortcut looks like nothing happening.
        if not bring_to_front(TITLE):
            server._open_window(running)
        return 0
    make_dpi_aware()
    try:
        import webview
    except Exception as exc:                  # ImportError, or a .NET/WebView2 failure
        _log.warning("pywebview unavailable (%s); using the Edge window", exc)
        return server.serve(watchdog=False, calendar=True)

    httpd, url, session = server.make_server()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    threading.Thread(target=server._calendar_loop, args=(session,), daemon=True).start()
    _log.info("widget serving %s", url)
    try:
        Widget(url, session, webview).run()
    except Exception as exc:
        _log.exception("widget window failed; using the Edge window")
        httpd.shutdown()
        httpd.server_close()
        server.release_lock()
        return server.serve(watchdog=False, calendar=True)
    finally:
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass
        try:
            session._release_live()      # the worker holds the speech model
        except Exception:
            _log.exception("could not stop the live transcriber")
        server.release_lock()
    return 0


if __name__ == "__main__":
    sys.exit(main())
