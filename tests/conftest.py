import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notetaker import hubexport  # noqa: E402  (needs the path above)


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
