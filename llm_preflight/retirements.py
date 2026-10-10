"""Bundled model-retirement snapshot and the three-state verdict built on it.

Rows are hand-reviewed against the official provider deprecation pages. The
verdict is pure: callers pass today's date. Absence from the table is not a
verdict; it is reported as unknown.
"""

from __future__ import annotations

from datetime import date
from typing import Any

ANTHROPIC_DEPRECATIONS_URL = (
    "https://platform.claude.com/docs/en/about-claude/model-deprecations"
)
OPENAI_DEPRECATIONS_URL = "https://developers.openai.com/api/docs/deprecations"
RETIREMENT_PROVIDERS: tuple[str, ...] = ("anthropic", "openai")
DEFAULT_MAX_AGE_DAYS = 30
_REVIEWED = "2026-10-09"

PUBLIC_RETIREMENTS: dict[tuple[str, str], dict[str, Any]] = {}


def _catalog_id(model: str) -> str:
    return model.rsplit("/", 1)[-1]


def next_command(provider: str, model: str, replacement: str) -> str:
    return (
        'llm-preflight --quick "<your prompt>" '
        f"--models {provider}:{model},{provider}:{replacement} --dry-run"
    )


def _row_status(row: dict[str, Any] | None, today: date) -> str:
    """Status of a row ignoring freshness; used for the replacement look-up."""
    if row is None:
        return "unknown"
    retirement_date = row.get("retirement_date")
    if row["status"] == "retired" or (
        retirement_date and date.fromisoformat(retirement_date) <= today
    ):
        return "retired"
    if row["status"] == "deprecated":
        return "retiring"
    return "active"


def retirement_verdict(
    provider: str | None,
    model: str,
    today: date,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> dict[str, Any]:
    """Classify one model against the bundled snapshot for the given day."""
    catalog_model = _catalog_id(model)
    row = PUBLIC_RETIREMENTS.get((provider, catalog_model)) if provider else None
    if row is None:
        covered = ", ".join(RETIREMENT_PROVIDERS)
        return {
            "status": "unknown",
            "decision": "none",
            "reason": "no retirement snapshot row for this model",
            "next_step": (
                "no retirement snapshot for this provider or model; the bundled "
                f"snapshot covers {covered} text-generation models"
            ),
        }
    assert provider is not None
    verdict: dict[str, Any] = {
        key: row[key]
        for key in ("retirement_date", "replacement", "as_of", "source_url")
        if key in row
    }
    source_url = row["source_url"]
    as_of = row["as_of"]
    age_days = (today - date.fromisoformat(as_of)).days
    stale = age_days > max_age_days
    stale_note = f"; snapshot row is {age_days} days old, review {source_url}"
    replacement = row.get("replacement")
    if replacement:
        verdict["replacement_status"] = _row_status(
            PUBLIC_RETIREMENTS.get((provider, replacement)), today
        )
        verdict["next_command"] = next_command(provider, catalog_model, replacement)
    base_status = _row_status(row, today)
    retirement_date = row.get("retirement_date")
    if base_status == "retired":
        status, decision = "retired", "fail"
        reason = (
            f"retired on {retirement_date}" if retirement_date else "listed as retired"
        ) + (stale_note if stale else "")
    elif stale:
        status, decision = "stale", "inconclusive"
        reason = (
            f"snapshot row reviewed {as_of} is {age_days} days old, "
            f"older than {max_age_days} days"
        )
    elif base_status == "retiring":
        status, decision = "retiring", "inconclusive"
        reason = (
            f"retirement announced for {retirement_date}"
            if retirement_date
            else "deprecated; retirement date to be announced"
        )
    else:
        status, decision = "active", "pass"
        reason = f"listed active as of {as_of}"
    if status == "stale":
        next_step = f"update llm-preflight or review {source_url}"
    elif status in {"retired", "retiring"} and replacement:
        next_step = (
            f"provider names {replacement} as the replacement; preview it with "
            f"the next command ({source_url})"
        )
        if verdict["replacement_status"] in {"retired", "retiring"}:
            next_step += f"; {replacement} is itself {verdict['replacement_status']}"
    elif status in {"retired", "retiring"}:
        next_step = (
            f"no replacement announced; choose one and preflight it ({source_url})"
        )
    else:
        next_step = f"listed active as of {as_of} ({source_url})"
    verdict.update(
        {
            "status": status,
            "decision": decision,
            "reason": reason,
            "next_step": next_step,
        }
    )
    return verdict
