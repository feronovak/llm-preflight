import ipaddress
import os
import socket
from datetime import date, datetime

import pytest

# Deterministic clock at or after every bundled snapshot review date.
# Bump it when a newly reviewed row would otherwise be in the future.
SNAPSHOT_REVIEW_DAY = date(2026, 11, 9)


@pytest.fixture(autouse=True)
def empty_credential_registry(monkeypatch):
    """Credential values recorded for redaction never leak between tests."""
    monkeypatch.setattr("llm_preflight.redaction._REGISTERED_CREDENTIALS", set())


def _is_loopback_host(host):
    if host is None or host in ("", b""):
        return True
    name = os.fsdecode(host).lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_real_dns(monkeypatch):
    """Fail any test that resolves a non-loopback host (CONTRIBUTING.md: no live network).

    Tests that stub `getaddrinfo` themselves replace this guard for their own scope.
    """
    real_getaddrinfo = socket.getaddrinfo

    def guarded(host, *args, **kwargs):
        if not _is_loopback_host(host):
            raise AssertionError(f"test attempted a real DNS lookup of {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)


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
