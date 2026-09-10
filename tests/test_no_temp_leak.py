"""The suite must not leave anything behind in the temp directory.

Hub's test suite leaked 21,032 directories and 5.85 GB while every test
passed, and it was invisible except on disk. It cost three sessions a day to
find, on a machine that was already full. Amir asked for the same check here.

The obvious shape, snapshotting `tempfile.gettempdir()` before and after and
diffing, does not work on this machine: that directory holds 7,774 entries
and other applications write to it while the suite runs, so the diff would
fail on someone else's files and be switched off within a week.

So the suite gets its own temp root instead, set in `conftest.py` before any
test runs, and this asserts that nothing survives in it except pytest's own
`pytest-of-*` tree, which pytest deliberately retains so a failed test's
files can be inspected. Anything else is ours and is a leak.
"""
import os
import tempfile
from pathlib import Path

from tests.conftest import SUITE_TEMP_ROOT_ENV


def _suite_root() -> Path | None:
    root = os.environ.get(SUITE_TEMP_ROOT_ENV)
    return Path(root) if root else None


class TestTheSuiteCleansUpAfterItself:
    def test_the_suite_has_its_own_temp_root(self):
        """If this fails the isolation is gone and the leak check is a lie."""
        root = _suite_root()
        assert root is not None and root.exists()
        assert Path(tempfile.gettempdir()).resolve() == root.resolve()

    def test_nothing_of_ours_is_left_in_it(self):
        """Runs last by name, after the rest of the suite has finished.

        Not a session-teardown hook on purpose: a failure in teardown reports
        as an error against an unrelated test and gets ignored. A test that
        fails is a test that gets read.
        """
        root = _suite_root()
        assert root is not None

        strays = [
            entry for entry in root.iterdir()
            # pytest keeps the last few runs' tmp_path trees so a failure can
            # be inspected. That is deliberate retention, not a leak.
            if not entry.name.startswith("pytest-of-")
        ]
        assert not strays, (
            "the suite left "
            f"{len(strays)} entr{'y' if len(strays) == 1 else 'ies'} in its temp "
            f"root:\n  " + "\n  ".join(str(s) for s in strays[:20])
            + "\n\nSomething created a temp file or directory and did not remove "
              "it. Find the caller rather than adding it to an allowlist: this "
              "is the check that would have caught Hub's 21,032 leaked stores."
        )
