"""
Audit logging.

Previously, file I/O (open/append) was written directly inside the
matching logic in llm_matcher.py -- functionally fine, but it mixes two
responsibilities: deciding a match, and persisting a record of that
decision. That coupling makes the matching logic harder to test in
isolation (every test has to deal with the filesystem) and harder to
extend later (e.g. logging to a database instead of a file means
touching matching code, not just this module).

This module is the single place that knows HOW audit entries are stored.
Callers just call log(entry) and don't know or care whether that's a
JSONL file, a database, or something else.
"""

import os
import json
from datetime import datetime, timezone

import config


def _path() -> str:
    """Computed fresh on every call, not cached at import time. If this
    were a module-level constant, it would freeze in whatever value
    config.OUTPUT_DIR held at import time -- which happens before main()
    ever gets a chance to apply a --output-dir CLI override. That exact
    bug was caught by a test before shipping; see tests/test_pipeline.py."""
    return os.path.join(config.OUTPUT_DIR, "audit_log.jsonl")


def log(entry: dict) -> None:
    """Appends one audit entry, stamped with a UTC timestamp if the
    caller didn't already provide one."""
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    with open(_path(), "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def read_all() -> list:
    """Reads back every logged entry -- useful for tests and for building
    a human-readable audit report from the raw log."""
    path = _path()
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]
