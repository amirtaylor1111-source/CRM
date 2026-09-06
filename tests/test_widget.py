"""The widget's window logic, without a window."""

import json

import pytest

from notetaker import widget


class FakeUser32:
    """Enough of user32 to see what the widget asks of it."""

    def __init__(self, hwnd=1234, affinity_ok=1):
        self.hwnd = hwnd
        self.affinity_ok = affinity_ok
        self.style = 0x00040000          # WS_EX_APPWINDOW set, as a new window has
        self.calls = []

    def SetWindowDisplayAffinity(self, hwnd, affinity):
        self.calls.append(("affinity", hwnd, affinity))
        return self.affinity_ok

    def GetWindowLongW(self, hwnd, index):
        return self.style

    def SetWindowLongW(self, hwnd, index, value):
        self.calls.append(("style", hwnd, value))
        self.style = value
        return 1

    def FindWindowW(self, cls, title):
        return self.hwnd

    def ShowWindow(self, hwnd, how):
        self.calls.append(("show", hwnd, how))

    def SetWindowPos(self, hwnd, after, x, y, w, h, flags):
        self.calls.append(("pos", hwnd, after, flags))
        return 1

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("front", hwnd))


AREA = (0, 0, 1920, 1040)


class TestGeometry:
    def test_pill_and_expanded_sizes(self):
        assert widget.size_for(False) == (widget.WIDTH, widget.PILL_HEIGHT)
        assert widget.size_for(True) == (widget.WIDTH, widget.EXPANDED_HEIGHT)

    def test_default_position_is_bottom_right_of_the_work_area(self):
        x, y = widget.default_position(AREA, expanded=True)
        assert x == 1920 - widget.WIDTH - widget.MARGIN
        assert y == 1040 - widget.EXPANDED_HEIGHT - widget.MARGIN

    def test_collapsing_keeps_the_bottom_edge_where_it_was(self):
        x, y = widget.default_position(AREA, expanded=True)
        nx, ny = widget.reshaped_position(x, y, was_expanded=True, work_area=AREA)
        assert nx == x
        assert ny + widget.PILL_HEIGHT == y + widget.EXPANDED_HEIGHT

    def test_expanding_never_leaves_the_screen(self):
        nx, ny = widget.reshaped_position(1900, 5, was_expanded=False, work_area=AREA)
        assert 0 <= nx <= 1920 - widget.WIDTH
        assert 0 <= ny <= 1040 - widget.EXPANDED_HEIGHT

    def test_a_short_screen_gets_a_shorter_widget(self):
        short = (0, 0, 1280, 672)                    # a 150% laptop, in logical pixels
        assert widget.expanded_height(short) == 672 - 2 * widget.MARGIN
        assert widget.size_for(True, short)[1] == 672 - 2 * widget.MARGIN
        x, y = widget.default_position(short, expanded=True)
        assert y == widget.MARGIN and x == 1280 - widget.WIDTH - widget.MARGIN
        assert widget.expanded_height(AREA) == widget.EXPANDED_HEIGHT

    def test_work_area_is_reported_in_logical_pixels(self):
        class U:
            def GetDpiForSystem(self):
                return 144

            def SystemParametersInfoW(self, action, p, rect, w):
                rect._obj.left, rect._obj.top, rect._obj.right, rect._obj.bottom = 0, 0, 1920, 1008
                return 1

        assert widget.dpi_scale(U()) == 1.5
        assert widget.work_area(U()) == (0, 0, 1280, 672)


class TestCaptureExclusion:
    def test_affinity_and_tool_window_style(self):
        u = FakeUser32()
        assert widget.hide_from_capture(1234, user32=u) is True
        assert ("affinity", 1234, widget.WDA_EXCLUDEFROMCAPTURE) in u.calls
        assert u.style & widget.WS_EX_TOOLWINDOW
        assert not (u.style & widget.WS_EX_APPWINDOW)

    def test_a_refused_affinity_is_reported_not_assumed(self):
        u = FakeUser32(affinity_ok=0)
        assert widget.hide_from_capture(1234, user32=u) is False

    def test_no_handle_means_no_call(self):
        u = FakeUser32()
        assert widget.hide_from_capture(0, user32=u) is False
        assert u.calls == []

    def test_native_handle_from_the_window_object(self):
        class FakeHandle:
            def ToInt64(self):
                return 777

        class Native:
            Handle = FakeHandle()

        class Window:
            native = Native()

        assert widget.native_handle(Window()) == 777
        assert widget.native_handle(object()) == 0

    def test_second_launch_brings_the_first_forward(self):
        u = FakeUser32(hwnd=42)
        assert widget.bring_to_front("Meeting Notetaker", user32=u) is True
        assert ("front", 42) in u.calls
        assert widget.bring_to_front("x", user32=FakeUser32(hwnd=0)) is False


class TestStartsAsAPill:
    def test_the_widget_opens_collapsed_at_the_bottom_right(self, monkeypatch, tmp_path):
        monkeypatch.setattr(widget.log, "log_dir", lambda: tmp_path)
        monkeypatch.setattr(widget, "dpi_scale", lambda user32=None: 1.0)
        monkeypatch.setattr(widget, "work_area", lambda user32=None, scale=None: AREA)
        w = widget.Widget("http://127.0.0.1:1/", session=None)
        assert w.expanded is False
        assert (w.x, w.y) == widget.default_position(AREA, expanded=False)


class TestClamp:
    def test_a_pill_position_is_clamped_for_the_expanded_shape(self):
        x, y = widget.default_position(AREA, expanded=False)      # bottom right, as a pill
        cx, cy = widget.clamped_position(x, y, True, AREA)
        assert cy + widget.expanded_height(AREA) <= AREA[3]
        assert cx == x

    def test_an_off_screen_position_comes_back(self):
        assert widget.clamped_position(-500, 9000, True, AREA)[0] == 0
        assert widget.clamped_position(-500, 9000, True, AREA)[1] == AREA[3] - widget.expanded_height(AREA)


class TestSettings:
    def test_position_round_trips_outside_the_repo(self, tmp_path, monkeypatch):
        monkeypatch.setattr(widget.log, "log_dir", lambda: tmp_path)
        widget.save_settings({"x": 10, "y": 20})
        assert widget.load_settings() == {"x": 10, "y": 20}
        assert json.loads((tmp_path / "widget.json").read_text()) == {"x": 10, "y": 20}

    def test_missing_or_broken_settings_are_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(widget.log, "log_dir", lambda: tmp_path)
        assert widget.load_settings() == {}
        (tmp_path / "widget.json").write_text("{not json", encoding="utf-8")
        assert widget.load_settings() == {}


class TestHost:
    def test_the_api_exposes_the_window_controls(self):
        class W:
            expanded = True
            calls = []

            def collapse(self):
                self.calls.append("collapse"); self.expanded = False

            def expand(self):
                self.calls.append("expand"); self.expanded = True

            def quit(self):
                self.calls.append("quit")

        w = W()
        api = widget.Api(w)
        assert api.shape() == "expanded"
        api.toggle()
        assert w.calls == ["collapse"] and api.shape() == "pill"
        api.toggle()
        assert w.calls == ["collapse", "expand"]
        api.quit()
        assert w.calls[-1] == "quit"
