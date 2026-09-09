import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notetaker import hubexport  # noqa: E402  (needs the path above)

#: Records where the suite's own temp root is, so test_no_temp_leak can check
#: it. Set below, at import time, before any fixture or test runs.
SUITE_TEMP_ROOT_ENV = "MTG_SUITE_TEMP_ROOT"


def _isolate_temp() -> None:
    """Give the whole run its own temp root and take it away afterwards.

    Hub's suite leaked 21,032 directories into the real temp directory, 5.85
    GB of them, while every test passed. The fix that works is not discipline
    at each call site; it is that the run cannot write to the shared location
    in the first place.

    This has to happen at import time rather than in a fixture, because
    pytest builds its `tmp_path` factory from the temp directory before any
    fixture runs.
    """
    if os.environ.get(SUITE_TEMP_ROOT_ENV):
        return                                    # already set by an outer run
    root = Path(tempfile.mkdtemp(prefix="mtg-suite-"))
    os.environ[SUITE_TEMP_ROOT_ENV] = str(root)
    for name in ("TMPDIR", "TEMP", "TMP"):
        os.environ[name] = str(root)
    tempfile.tempdir = str(root)

    def _remove() -> None:
        # Best effort. A file still held open on Windows must not turn a
        # green run red at the very last moment.
        shutil.rmtree(root, ignore_errors=True)

    atexit.register(_remove)


_isolate_temp()


@pytest.fixture
def crm(tmp_path):
    """An isolated CRM root, so tests never touch the real repo."""
    (tmp_path / "meetings").mkdir()
    (tmp_path / "contacts").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def _never_touch_the_real_export(tmp_path, monkeypatch):
    """Point the Hub export at a scratch directory for every single test.

    Autouse and unconditional on purpose. The widget refreshes the export
    whenever a write-up finishes, so any test that drives a Session writes
    one, and on 9 September that replaced Amir's real 26-meeting export with
    a single fixture meeting. Hub read it before its collector shipped, which
    is the only reason a test participant did not land in his CRM as a client
    with an action item against his name.

    The lesson is not "remember to override the path in the server tests". It
    is that a suite must not be able to name a production location at all, so
    this is enforced here, once, rather than per test.
    """
    monkeypatch.setenv(hubexport.EXPORT_DIR_ENV, str(tmp_path / "exports"))
