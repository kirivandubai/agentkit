"""A SQLite database someone else writes, opened for reading alone.

mode=ro and nothing else: a missing file is an error rather than a new empty database, and no write can happen by
mistake. Not immutable=1: that reads a live database without its WAL and its locks, so a count would be stale by
chance. The path goes in as a file: URI, percent-encoded, so a name with '?' or '#' cannot add parameters.

Stdlib only and Python 3.9 (annotations are never evaluated): a host script on /usr/bin/python3 and dev's box run a
vendored copy of it.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

TIMEOUT_S = 2.0  # how long a read waits on a writer's lock before it fails


def open_ro(path: str | os.PathLike[str], *, timeout: float = TIMEOUT_S) -> sqlite3.Connection:
    """A read-only connection to the database at path; sqlite3.OperationalError when there is none."""
    uri = Path(path).absolute().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=timeout)
