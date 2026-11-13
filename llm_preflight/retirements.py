"""Bundled model-retirement snapshot and the three-state verdict built on it.

Rows are hand-reviewed against the official provider deprecation pages. The
verdict is pure: callers pass today's date. Absence from the table is not a
verdict; it is reported as unknown.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any

ANTHROPIC_DEPRECATIONS_URL = (
    "https://platform.claude.com/docs/en/about-claude/model-deprecations"
)
OPENAI_DEPRECATIONS_URL = "https://developers.openai.com/api/docs/deprecations"
GEMINI_DEPRECATIONS_URL = "https://aistudio.google.com/docs/deprecations"
RETIREMENT_PROVIDERS: tuple[str, ...] = ("anthropic", "gemini", "openai")
GEMINI_MODEL_REDIRECTS = {
    "gemini-3.5-flash": "gemini-3.6-flash",
    "gemini-3.7-flash": "gemini-3.8-flash",
}
DEFAULT_MAX_AGE_DAYS = 30
_DATED_SUFFIX = {
    "anthropic": re.compile(r"-\d{8}$"),
    "openai": re.compile(r"-\d{4}-\d{2}-\d{2}$"),
}
_ANTHROPIC_ALIAS_TAIL = re.compile(r"-(?:latest|0)$")
EXPIRY_NOTICE_DAYS = 7
_REVIEWED = "2026-11-04"


def _row(
    status: str,
    *,
    source_url: str,
    retirement_date: str | None = None,
    replacement: str | None = None,
    as_of: str = _REVIEWED,
) -> dict[str, Any]:
    row: dict[str, Any] = {"status": status, "as_of": as_of, "source_url": source_url}
    if retirement_date is not None:
        row["retirement_date"] = retirement_date
    if replacement is not None:
        row["replacement"] = replacement
    return row


def _anthropic(
    status: str,
    retirement_date: str | None = None,
    replacement: str | None = None,
    as_of: str = _REVIEWED,
) -> dict[str, Any]:
    return _row(
        status,
        source_url=ANTHROPIC_DEPRECATIONS_URL,
        retirement_date=retirement_date,
        replacement=replacement,
        as_of=as_of,
    )


def _openai(
    status: str,
    retirement_date: str | None = None,
    replacement: str | None = None,
    as_of: str = _REVIEWED,
) -> dict[str, Any]:
    return _row(
        status,
        source_url=OPENAI_DEPRECATIONS_URL,
        retirement_date=retirement_date,
        replacement=replacement,
        as_of=as_of,
    )


# Anthropic: "Model status" table and "Deprecation history" on the official
# page. Active rows carry no retirement date; the page's "not sooner than"
# dates are floors, not retirements. Partner platforms (Bedrock, Vertex) set
# their own schedules and are not represented.
_ANTHROPIC: dict[str, dict[str, Any]] = {
    "claude-fable-5-2": _anthropic("active", as_of="2026-11-09"),
    "claude-mythos-5-2": _anthropic("active", as_of="2026-11-09"),
    "claude-fable-5-1": _anthropic("active"),
    "claude-mythos-5-1": _anthropic("active"),
    "claude-fable-5": _anthropic("active"),
    "claude-mythos-5": _anthropic("active"),
    "claude-mythos-preview": _anthropic("deprecated"),
    "claude-opus-5-5": _anthropic("active"),
    "claude-opus-5": _anthropic("active"),
    "claude-opus-4-8": _anthropic("active"),
    "claude-opus-4-7": _anthropic("active"),
    "claude-opus-4-6": _anthropic("active"),
    "claude-opus-4-5-20251101": _anthropic("active"),
    "claude-opus-4-1-20250805": _anthropic("retired", "2026-08-05", "claude-opus-4-8"),
    "claude-opus-4-20250514": _anthropic("retired", "2026-06-15", "claude-opus-4-8"),
    "claude-sonnet-5-5": _anthropic("active"),
    "claude-sonnet-5": _anthropic("active"),
    "claude-sonnet-4-6": _anthropic("active"),
    "claude-sonnet-4-5-20250929": _anthropic(
        "deprecated", "2026-11-30", "claude-sonnet-5-5"
    ),
    "claude-sonnet-4-20250514": _anthropic(
        "retired", "2026-06-15", "claude-sonnet-5-5"
    ),
    "claude-3-7-sonnet-20250219": _anthropic(
        "retired", "2026-02-19", "claude-sonnet-5-5"
    ),
    "claude-haiku-5-5": _anthropic("active"),
    "claude-haiku-4-5-20251001": _anthropic("active"),
    "claude-3-5-haiku-20241022": _anthropic(
        "retired", "2026-02-19", "claude-haiku-4-5-20251001"
    ),
    "claude-3-haiku-20240307": _anthropic(
        "retired", "2026-04-20", "claude-haiku-4-5-20251001"
    ),
    "claude-3-5-sonnet-20240620": _anthropic(
        "retired", "2025-10-28", "claude-sonnet-5-5"
    ),
    "claude-3-5-sonnet-20241022": _anthropic(
        "retired", "2025-10-28", "claude-sonnet-5-5"
    ),
    "claude-3-opus-20240229": _anthropic("retired", "2026-01-05", "claude-opus-4-8"),
    "claude-2.0": _anthropic("retired", "2025-07-21", "claude-opus-4-8"),
    "claude-2.1": _anthropic("retired", "2025-07-21", "claude-opus-4-8"),
    "claude-3-sonnet-20240229": _anthropic(
        "retired", "2025-07-21", "claude-sonnet-5-5"
    ),
    "claude-1.0": _anthropic("retired", "2024-11-06", "claude-haiku-4-5-20251001"),
    "claude-1.1": _anthropic("retired", "2024-11-06", "claude-haiku-4-5-20251001"),
    "claude-1.2": _anthropic("retired", "2024-11-06", "claude-haiku-4-5-20251001"),
    "claude-1.3": _anthropic("retired", "2024-11-06", "claude-haiku-4-5-20251001"),
    "claude-instant-1.0": _anthropic(
        "retired", "2024-11-06", "claude-haiku-4-5-20251001"
    ),
    "claude-instant-1.1": _anthropic(
        "retired", "2024-11-06", "claude-haiku-4-5-20251001"
    ),
    "claude-instant-1.2": _anthropic(
        "retired", "2024-11-06", "claude-haiku-4-5-20251001"
    ),
}

# OpenAI: the official deprecations page lists announcements, not active
# models, so no OpenAI row is "active"; an OpenAI ID absent here is unknown.
# Only text-generation IDs the source scanner recognises are listed. A row
# whose page entry names more than one replacement, or a replacement that is
# itself deprecated, carries none.
_OPENAI: dict[str, dict[str, Any]] = {
    # 2026-11-05 announcement: no replacement named on the page
    "gpt-5.5-cyber-preview": _openai("deprecated", "2027-02-01", as_of="2026-11-12"),
    # 2026-10-14 announcement; aliases map to these dated snapshots on the
    # official model pages. The older gpt-4o-2024-05-13 keeps its October date.
    "gpt-4o": _openai("deprecated", "2027-01-14", "gpt-6-luna"),
    "gpt-4o-2024-08-06": _openai("deprecated", "2027-01-14", "gpt-6-luna"),
    "gpt-4o-2024-11-20": _openai("deprecated", "2027-01-14", "gpt-6-luna"),
    "gpt-4o-mini": _openai("deprecated", "2027-01-14", "gpt-6-luna"),
    "gpt-4o-mini-2024-07-18": _openai("deprecated", "2027-01-14", "gpt-6-luna"),
    "gpt-4.1": _openai("deprecated", "2027-01-14", "gpt-6-luna"),
    "gpt-4.1-2025-04-14": _openai("deprecated", "2027-01-14", "gpt-6-luna"),
    "gpt-4.1-mini": _openai("deprecated", "2027-01-14", "gpt-6-luna"),
    "gpt-4.1-mini-2025-04-14": _openai("deprecated", "2027-01-14", "gpt-6-luna"),
    # 2026-10-01 announcement
    "gpt-5.3-codex": _openai("deprecated", "2027-04-01", "gpt-6-sol"),
    "gpt-5.4-nano": _openai("deprecated", "2027-04-01", "gpt-6-luna"),
    "gpt-5.4-nano-2026-03-17": _openai("deprecated", "2027-04-01", "gpt-6-luna"),
    "gpt-5.1": _openai("deprecated", "2027-04-01", "gpt-6-sol"),
    "gpt-5.1-2025-11-13": _openai("deprecated", "2027-04-01", "gpt-6-sol"),
    # 2026-09-11: no replacement named on the page
    "gpt-5.4-cyber": _openai("deprecated", "2026-10-01"),
    # 2026-06-11 announcement
    "gpt-5-2025-08-07": _openai(
        "deprecated", "2026-12-11", "gpt-6.1-sol", as_of="2026-11-13"
    ),
    "gpt-5-mini-2025-08-07": _openai(
        "deprecated", "2026-12-11", "gpt-6.1-terra", as_of="2026-11-13"
    ),
    "gpt-5-nano-2025-08-07": _openai(
        "deprecated", "2026-12-11", "gpt-6-luna", as_of="2026-11-13"
    ),
    # The page names gpt-6.1-sol with reasoning.mode: pro; a replacement that needs a mode setting is not recorded.
    "gpt-5-pro-2025-10-06": _openai("deprecated", "2026-12-11"),
    "o3-pro-2025-06-10": _openai("deprecated", "2026-12-11"),
    "o3-2025-04-16": _openai(
        "deprecated", "2026-12-11", "gpt-6.1-sol", as_of="2026-11-13"
    ),
    # 2026-05-08 announcement
    "gpt-5.2-chat-latest": _openai("deprecated", "2026-08-10", "gpt-5.6-sol"),
    "gpt-5.3-chat-latest": _openai("deprecated", "2026-08-10", "gpt-5.6-sol"),
    # 2026-04-22 announcement, shutdown 2026-10-23
    "gpt-3.5-turbo-0125": _openai("deprecated", "2026-10-23", "gpt-5.6-terra"),
    "gpt-3.5-turbo": _openai("deprecated", "2026-10-23", "gpt-5.6-terra"),
    "gpt-3.5-turbo-completions": _openai("deprecated", "2026-10-23", "gpt-5.6-terra"),
    "gpt-4-0613": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "gpt-4": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "gpt-4-0613-completions": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "gpt-4-completions": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "gpt-4-turbo": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "gpt-4-turbo-2024-04-09": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "gpt-4-turbo-completions": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "gpt-4o-2024-05-13": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "o1-2024-12-17": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "o1": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "o3-mini-2025-01-31": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "o3-mini": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    # The page lists gpt-4-1106-preview once, in this 2026-04-22 batch.
    "gpt-4-1106-preview": _openai("deprecated", "2026-10-23", "gpt-5.6-sol"),
    "gpt-4.1-nano": _openai("deprecated", "2026-10-23", "gpt-5.6-luna"),
    "gpt-4.1-nano-2025-04-14": _openai("deprecated", "2026-10-23", "gpt-5.6-luna"),
    # The page names gpt-5.6-sol with reasoning.mode: pro; a replacement that needs a mode setting is not recorded.
    "o1-pro-2025-03-19": _openai("deprecated", "2026-10-23"),
    "o1-pro": _openai("deprecated", "2026-10-23"),
    "o4-mini-2025-04-16": _openai("deprecated", "2026-10-23", "gpt-5.6-terra"),
    "o4-mini": _openai("deprecated", "2026-10-23", "gpt-5.6-terra"),
    # 2026-04-22 announcement, shutdown 2026-07-23
    "gpt-4o-mini-search-preview-2025-03-11": _openai(
        "deprecated", "2026-07-23", "gpt-5.6-terra"
    ),
    "gpt-4o-search-preview-2025-03-11": _openai(
        "deprecated", "2026-07-23", "gpt-5.6-terra"
    ),
    "gpt-5.1-codex-mini": _openai("deprecated", "2026-07-23", "gpt-5.6-terra"),
    "gpt-5-chat-latest": _openai("deprecated", "2026-07-23", "gpt-5.6-sol"),
    "gpt-5-codex": _openai("deprecated", "2026-07-23", "gpt-5.6-sol"),
    "gpt-5.1-chat-latest": _openai("deprecated", "2026-07-23", "gpt-5.6-sol"),
    "gpt-5.1-codex": _openai("deprecated", "2026-07-23", "gpt-5.6-sol"),
    "gpt-5.1-codex-max": _openai("deprecated", "2026-07-23", "gpt-5.6-sol"),
    "gpt-5.2-codex": _openai("deprecated", "2026-07-23", "gpt-5.6-sol"),
    "o3-deep-research-2025-06-26": _openai("deprecated", "2026-07-23", "gpt-5.6-sol"),
    "o3-deep-research": _openai("deprecated", "2026-07-23", "gpt-5.6-sol"),
    "o4-mini-deep-research-2025-06-26": _openai(
        "deprecated", "2026-07-23", "gpt-5.6-sol"
    ),
    "o4-mini-deep-research": _openai("deprecated", "2026-07-23", "gpt-5.6-sol"),
    # 2025-09-26 announcement
    "gpt-3.5-turbo-instruct": _openai("deprecated", "2026-09-28", "gpt-5.6-terra"),
    "gpt-3.5-turbo-1106": _openai("deprecated", "2026-09-28", "gpt-5.6-terra"),
    # 2025-09-26 announcement; the page names "gpt-5 or gpt-4.1*", so no
    # single replacement is recorded.
    "gpt-4-0314": _openai("deprecated", "2026-03-26"),
    "gpt-4-0125-preview": _openai("deprecated", "2026-03-26"),
    "gpt-4-turbo-preview": _openai("deprecated", "2026-03-26"),
    "gpt-4-turbo-preview-completions": _openai("deprecated", "2026-03-26"),
    # 2025-04-28 and earlier announcements
    # The page names o3, whose only dated snapshot retires on 2026-12-11; not
    # recorded.
    "o1-preview": _openai("deprecated", "2025-07-28"),
    # The page names o4-mini, itself retiring on 2026-10-23; not recorded.
    "o1-mini": _openai("deprecated", "2025-10-27"),
    # The page names gpt-4.1, now deprecated itself; not recorded.
    "gpt-4.5-preview": _openai("deprecated", "2025-07-14"),
    "gpt-4-32k": _openai("deprecated", "2025-06-06"),
    "gpt-4-32k-0613": _openai("deprecated", "2025-06-06"),
    "gpt-4-32k-0314": _openai("deprecated", "2025-06-06"),
    "gpt-4-vision-preview": _openai("deprecated", "2024-12-06"),
    "gpt-4-1106-vision-preview": _openai("deprecated", "2024-12-06"),
    # The page names gpt-3.5-turbo, itself retiring on 2026-10-23; not recorded.
    "gpt-3.5-turbo-0613": _openai("deprecated", "2024-09-13"),
    "gpt-3.5-turbo-16k-0613": _openai("deprecated", "2024-09-13"),
    "gpt-3.5-turbo-0301": _openai("deprecated", "2024-09-13"),
}

_GEMINI = {
    **{
        model: _row("active", source_url=GEMINI_DEPRECATIONS_URL)
        for model in ("gemini-3.6-flash", "gemini-3.8-flash")
    },
    "gemini-4-argon": _row(
        "active",
        source_url="https://aistudio.google.com/docs/models/gemini-4-argon",
    ),
    **{
        model: {
            **_row("active", source_url=GEMINI_DEPRECATIONS_URL),
            "redirected": True,
            "routes_to": route,
        }
        for model, route in GEMINI_MODEL_REDIRECTS.items()
    },
    "gemini-3.1-flash-lite": _row(
        "deprecated",
        source_url=GEMINI_DEPRECATIONS_URL,
        retirement_date="2027-05-07",
        replacement="gemini-3.5-flash-lite",
    ),
}

PUBLIC_RETIREMENTS: dict[tuple[str, str], dict[str, Any]] = {
    **{("anthropic", model): row for model, row in _ANTHROPIC.items()},
    **{("openai", model): row for model, row in _OPENAI.items()},
    **{("gemini", model): row for model, row in _GEMINI.items()},
}


def snapshot_summary() -> dict[str, Any]:
    """Describe the bundled snapshot so reports can state its coverage."""
    as_of_dates = sorted(row["as_of"] for row in PUBLIC_RETIREMENTS.values())
    valid_until = date.fromisoformat(as_of_dates[0]) + timedelta(
        days=DEFAULT_MAX_AGE_DAYS
    )
    return {
        "providers": list(RETIREMENT_PROVIDERS),
        "rows": len(PUBLIC_RETIREMENTS),
        "oldest_as_of": as_of_dates[0],
        "newest_as_of": as_of_dates[-1],
        "valid_until": valid_until.isoformat(),
    }


def selected_snapshot(
    entries: list[dict[str, Any]], max_age_days: int = DEFAULT_MAX_AGE_DAYS
) -> dict[str, Any]:
    """The snapshot summary with `valid_until` taken from the selected rows.

    The bundled-wide date can differ from the rows a config uses. A retired
    row's verdict does not change when it goes stale, so it does not count;
    with no other selected row nothing goes stale, so the key is absent.
    """
    summary = snapshot_summary()
    reviewed = [
        entry["as_of"]
        for entry in entries
        if entry.get("as_of") and entry.get("status") != "retired"
    ]
    if not reviewed:
        summary.pop("valid_until")
        return summary
    oldest = date.fromisoformat(min(reviewed))
    summary["valid_until"] = (oldest + timedelta(days=max_age_days)).isoformat()
    return summary


def expiry_notice(snapshot: dict[str, Any], today: date) -> str | None:
    """Text-only warning that the bundled rows go stale soon; never a verdict."""
    valid_until = snapshot.get("valid_until")
    if not valid_until:
        return None
    days_left = (date.fromisoformat(valid_until) - today).days
    if not 0 <= days_left <= EXPIRY_NOTICE_DAYS:
        return None
    return (
        f"The bundled retirement rows for these models are valid until "
        f"{valid_until} ({days_left} {'day' if days_left == 1 else 'days'} left). After that, --ci returns "
        "inconclusive for them until you update llm-preflight."
    )


def _catalog_id(model: str) -> str:
    return model.rsplit("/", 1)[-1]


def next_command(provider: str, model: str, replacement: str) -> str:
    return (
        'llm-preflight --quick "<your prompt>" '
        f"--models {provider}:{model},{provider}:{replacement} --dry-run"
    )


def unique_next_commands(verdicts: Iterable[dict[str, Any]]) -> list[str]:
    """Each distinct next command in first-seen order, skipping verdicts without one."""
    return list(
        dict.fromkeys(
            verdict["next_command"] for verdict in verdicts if "next_command" in verdict
        )
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


def today_utc() -> date:
    """Return today's UTC calendar date, the clock the pricing snapshot uses."""
    return datetime.now(timezone.utc).date()


_DATED_INDEX: tuple[Any, dict[tuple[str, str], list[str]]] | None = None


def _dated_index() -> dict[tuple[str, str], list[str]]:
    """Dated rows by (provider, stem), built once per snapshot table."""
    global _DATED_INDEX
    if _DATED_INDEX is None or _DATED_INDEX[0] is not PUBLIC_RETIREMENTS:
        index: dict[tuple[str, str], list[str]] = {}
        for provider, row_id in PUBLIC_RETIREMENTS:
            suffix = _DATED_SUFFIX.get(provider)
            match = suffix and suffix.search(row_id)
            if match:
                stem = row_id[: match.start()]
                index.setdefault((provider, stem), []).append(row_id)
        _DATED_INDEX = (PUBLIC_RETIREMENTS, index)
    return _DATED_INDEX[1]


def _alias_candidates(provider: str, model_id: str) -> list[str]:
    """Dated snapshot rows that an alias without a row of its own may stand for."""
    if provider not in _DATED_SUFFIX:
        return []
    stems = {model_id}
    if provider == "anthropic":
        stems.add(_ANTHROPIC_ALIAS_TAIL.sub("", model_id))
    index = _dated_index()
    return sorted({row for stem in stems for row in index.get((provider, stem), [])})


def _same_finding(rows: list[dict[str, Any]]) -> bool:
    return (
        len(
            {
                (r["status"], r.get("retirement_date"), r.get("replacement"))
                for r in rows
            }
        )
        == 1
    )


def _unmapped_verdict(candidates: list[str]) -> dict[str, Any]:
    return {
        "status": "alias_unmapped",
        "decision": "inconclusive",
        "reason": "alias without a safe mapping to one snapshot row",
        "next_step": (
            "name the dated snapshot ID your provider routes this alias to; "
            f"snapshot rows that may apply: {', '.join(candidates)}"
        ),
        "alias_candidates": candidates,
    }


def retirement_verdict(
    provider: str | None,
    model: str,
    today: date,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> dict[str, Any]:
    """Classify one model against the bundled snapshot for the given day."""
    catalog_model = _catalog_id(model).lower()
    row = PUBLIC_RETIREMENTS.get((provider, catalog_model)) if provider else None
    matched_id = None
    if provider and row is None:
        candidates = _alias_candidates(provider, catalog_model)
        rows = [PUBLIC_RETIREMENTS[(provider, c)] for c in candidates]
        if rows and provider == "anthropic" and _same_finding(rows):
            matched_id = min(
                candidates, key=lambda c: PUBLIC_RETIREMENTS[(provider, c)]["as_of"]
            )
            row = PUBLIC_RETIREMENTS[(provider, matched_id)]
        elif candidates:
            return _unmapped_verdict(candidates)
    if provider is None or row is None:
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
    verdict: dict[str, Any] = {
        key: row[key]
        for key in ("retirement_date", "replacement", "as_of", "source_url")
        if key in row
    }
    if matched_id:
        verdict["matched_id"] = matched_id
    source_url = row["source_url"]
    as_of = row["as_of"]
    age_days = (today - date.fromisoformat(as_of)).days
    stale = age_days > max_age_days
    stale_note = (
        f"; snapshot row reviewed {as_of} is older than {max_age_days} days, "
        f"review {source_url}"
    )
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
        reason = f"snapshot row reviewed {as_of} is older than {max_age_days} days"
    elif base_status == "retiring":
        status, decision = "retiring", "inconclusive"
        reason = (
            f"retirement announced for {retirement_date}"
            if retirement_date
            else "deprecated; retirement date to be announced"
        )
    else:
        status, decision = "active", "pass"
        reason = (
            f"no shutdown date listed; requests automatically route to {row['routes_to']}; "
            "the endpoint is not shutting down"
            if row.get("redirected")
            else f"listed active as of {as_of}"
        )
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
        next_step = f"no single replacement recorded; read the page, choose one and preflight it ({source_url})"
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


# Bandit B105 misreads the "pass" key as a hard-coded password; without the
# suppression, `make audit` fails.
_DECISION_RANK = {"fail": 3, "inconclusive": 2, "pass": 1}  # nosec B105


def worst_decision(decisions: Iterable[str]) -> str:
    """Worst of fail > inconclusive > pass; "none" when nothing was verified."""
    ranked = [decision for decision in decisions if decision in _DECISION_RANK]
    if not ranked:
        return "none"
    return max(ranked, key=_DECISION_RANK.__getitem__)


def retirement_report(
    models: list[dict[str, Any]],
    today: date,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> dict[str, Any]:
    """Verdicts for a selected model list, for the doctor and the dry-run."""
    entries = []
    for model in models:
        provider = model.get("provider", "openai_compatible")
        verdict = retirement_verdict(provider, model["model"], today, max_age_days)
        entries.append({"provider": provider, "model": model["model"], **verdict})
    summary = {
        status: sum(entry["status"] == status for entry in entries)
        for status in (
            "retired",
            "retiring",
            "stale",
            "active",
            "alias_unmapped",
            "unknown",
        )
    }
    return {
        "decision": worst_decision(entry["decision"] for entry in entries),
        "summary": summary,
        "models": entries,
        "next_commands": unique_next_commands(entries),
        "snapshot": selected_snapshot(entries, max_age_days),
    }
