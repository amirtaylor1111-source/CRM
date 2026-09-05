"""One log file, so a failure on the user's machine leaves a trail.

When something goes wrong on a laptop I cannot see, "it didn't work" is the
whole bug report unless the tool wrote down what it was doing. Every entry
point calls setup() once; everything else just logs.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

NAME = "mtg"


def log_dir() -> Path:
    """Per-user, outside the repo, so logs never get committed."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "mtg"


def log_path() -> Path:
    return log_dir() / "mtg.log"


def setup(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger(NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_path(), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    except OSError:
        pass                                   # a tool that cannot log still works

    if verbose:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        console.setLevel(logging.DEBUG)
        logger.addHandler(console)

    logger.debug("--- start: %s %s", sys.platform, " ".join(sys.argv[:3]))
    return logger


def get(child: str = "") -> logging.Logger:
    return logging.getLogger(f"{NAME}.{child}" if child else NAME)
