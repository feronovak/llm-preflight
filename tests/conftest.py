from datetime import datetime

import pytest


@pytest.fixture
def august_catalog_review(monkeypatch):
    """Keep the August catalogue fixtures independent of wall-clock expiry."""

    class ReviewDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 31, tzinfo=tz)

    monkeypatch.setattr("llm_preflight.pricing.datetime", ReviewDatetime)
