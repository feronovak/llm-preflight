import json
from pathlib import Path

import pytest

from llm_preflight.pricing import PUBLIC_PRICING
from llm_preflight.retirements import PUBLIC_RETIREMENTS

IMPORTANCE_FILE = (
    Path(__file__).resolve().parents[1] / "docs" / "data" / "model-importance.json"
)


def _rows() -> list[dict]:
    return json.loads(IMPORTANCE_FILE.read_text(encoding="utf-8"))["models"]


def _bundled() -> set[tuple[str, str]]:
    return set(PUBLIC_PRICING) | set(PUBLIC_RETIREMENTS)


def test_every_bundled_model_has_a_tier():
    rated = {(row["provider"], row["model"]) for row in _rows()}
    missing = sorted(_bundled() - rated)
    assert not missing, (
        f"bundled models without a tier in model-importance.json: {missing}"
    )


def test_every_listed_model_is_bundled():
    rated = {(row["provider"], row["model"]) for row in _rows()}
    unknown = sorted(rated - _bundled())
    assert not unknown, (
        f"model-importance.json lists models that are not bundled: {unknown}"
    )


def test_each_model_is_listed_once():
    keys = [(row["provider"], row["model"]) for row in _rows()]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    "row", _rows(), ids=lambda row: f"{row['provider']}/{row['model']}"
)
def test_row_has_tier_and_reason(row):
    assert row["tier"] in (1, 2, 3)
    assert isinstance(row["reason"], str) and row["reason"].strip()
