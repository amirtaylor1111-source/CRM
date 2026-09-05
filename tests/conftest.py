import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def crm(tmp_path):
    """An isolated CRM root, so tests never touch the real repo."""
    (tmp_path / "meetings").mkdir()
    (tmp_path / "contacts").mkdir()
    return tmp_path
