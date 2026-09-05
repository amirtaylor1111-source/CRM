"""The CLI must survive a legacy Windows console."""

import io
import sys

from notetaker import cli


def test_non_utf8_console_does_not_crash_on_symbols(monkeypatch, capsys):
    # A cp1252 stream, as classic cmd.exe hands Python on many machines.
    buf = io.BytesIO()
    legacy = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", legacy)
    cli._utf8_console()
    # After reconfigure, these must not raise.
    print("✓ ⚠ — fine", file=sys.stdout)
    sys.stdout.flush()
    assert b"fine" in buf.getvalue()


def test_reconfigure_is_harmless_on_streams_without_it(monkeypatch):
    class Bare:
        pass
    monkeypatch.setattr(sys, "stdout", Bare())
    monkeypatch.setattr(sys, "stderr", Bare())
    cli._utf8_console()          # must not raise


def test_doctor_survives_an_optional_import_that_raises_oserror(monkeypatch, capsys):
    """The doctor explains broken backends; it must not die of them."""
    import builtins

    real = builtins.__import__

    def poisoned(name, *a, **k):
        if name == "soundcard":
            raise OSError("cannot load library 'libpulse.so'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", poisoned)
    code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "FAIL" in out and "audio library" in out
    assert "Traceback" not in out
    assert code in (cli.OK, cli.ENV_ERROR)


def test_check_import_names_the_vc_runtime_on_dll_failure(monkeypatch):
    import importlib

    def dll_fail(name, *a, **k):
        raise ImportError("DLL load failed while importing onnxruntime_pybind11_state")

    monkeypatch.setattr(importlib, "import_module", dll_fail)
    label, ok, fix = cli._check_import("engine", "fake_ort", "pip install x")
    assert ok is False
    assert "Visual C++" in fix
