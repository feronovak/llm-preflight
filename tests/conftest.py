from datetime import date, datetime

import pytest

# Deterministic clock at or after every bundled snapshot review date.
# Bump it when a newly reviewed row would otherwise be in the future.
SNAPSHOT_REVIEW_DAY = date(2026, 10, 15)


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
