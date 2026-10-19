import os
from datetime import date, datetime

import pytest

# Deterministic clock at or after every bundled snapshot review date.
# Bump it when a newly reviewed row would otherwise be in the future.
SNAPSHOT_REVIEW_DAY = date(2026, 10, 19)


@pytest.fixture
def snapshot_review_day(monkeypatch):
    """Pin "today" to the snapshot review day so example pricing checks do not
    expire as the wall clock moves; the real-date check is `make release-freshness`."""

    class ReviewDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                SNAPSHOT_REVIEW_DAY.year,
                SNAPSHOT_REVIEW_DAY.month,
                SNAPSHOT_REVIEW_DAY.day,
                tzinfo=tz,
            )

    monkeypatch.setattr("llm_preflight.pricing.datetime", ReviewDatetime)


@pytest.fixture
def august_catalog_review(monkeypatch):
    """Keep the August catalogue fixtures independent of wall-clock expiry."""

    class ReviewDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 31, tzinfo=tz)

    monkeypatch.setattr("llm_preflight.pricing.datetime", ReviewDatetime)


@pytest.fixture
def tripwire(tmp_path):
    """Make shell commands that leave `<name>.ran` in tmp_path if they ever run.

    A passthrough command copies stdin to stdout, as a Git clean filter must.
    """

    def make(name, passthrough=False):
        script = tmp_path / f"{name}.sh"
        script.write_text(
            f'#!/bin/sh\ntouch "{tmp_path / f"{name}.ran"}"\n'
            + ("exec cat\n" if passthrough else "exit 1\n")
        )
        script.chmod(0o755)
        return str(script)

    return make


@pytest.fixture
def non_utf8_file_names(tmp_path):
    """Skip unless the filesystem stores a file name that is not UTF-8 as given.

    APFS rejects such names, HFS+ rewrites them, and Windows names are UTF-16.
    """
    try:
        probe = tmp_path / os.fsdecode(b"probe\xff")
        probe.touch()
    except (OSError, ValueError):
        pytest.skip("the filesystem rejects file names that are not UTF-8")
    stored = os.fsencode(probe.name) in os.listdir(os.fsencode(tmp_path))
    probe.unlink(missing_ok=True)
    if not stored:
        pytest.skip("the filesystem rewrites file names that are not UTF-8")
