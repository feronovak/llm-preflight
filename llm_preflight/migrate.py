"""Report which provider-named replacement applies to each retired config model.

Read-only: the source config is never written, no provider is called and no
replacement is inferred. The replacement is the bundled retirement row's
`replacement` field and nothing else.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from . import retirements
from .features import apply_model_aliases
from .retirements import DEFAULT_MAX_AGE_DAYS, retirement_verdict, worst_decision

SCHEMA_VERSION = 1
EXIT_CODES = {"fail": 1, "inconclusive": 3}
_AFFECTED = {"retired", "retiring", "stale"}
_UNUSABLE = {"retired", "retiring"}


def _load(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(config, dict):
        raise ValueError(f"{path} must hold a JSON object")  # noqa: TRY004
    config = apply_model_aliases(config)
    models = config.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("config must list at least one entry under 'models'")
    for model in models:
        if not isinstance(model, dict) or not isinstance(model.get("model"), str):
            raise ValueError(  # noqa: TRY004
                "every 'models' entry must be an object with a 'model'"
            )
        if not isinstance(model.get("provider", ""), str):
            raise ValueError("'provider' must be a string")  # noqa: TRY004
    return config


def _is_stale(verdict: dict[str, Any], today: date) -> bool:
    as_of = verdict.get("as_of")
    if as_of is None:
        return False
    return (today - date.fromisoformat(as_of)).days > DEFAULT_MAX_AGE_DAYS


def _outcome(
    verdict: dict[str, Any],
    model: dict[str, Any],
    listed: set[tuple[str, str]],
    today: date,
) -> str:
    replacement = verdict.get("replacement")
    if verdict["status"] not in _AFFECTED:
        return "not_affected"
    if _is_stale(verdict, today):
        return "snapshot_stale"
    if not replacement:
        return "no_named_replacement"
    if verdict["replacement_status"] in _UNUSABLE:
        return "replacement_unusable"
    if (model.get("provider", "openai_compatible"), replacement) in listed:
        return "replacement_in_config"
    if model.get("headers"):
        return "route_headers"
    return "candidate"


_NEXT = {
    "candidate": "{replacement} is the provider-named replacement; preview it with: {command}",
    "replacement_in_config": "{replacement} is already in this config; preview it with: {command}",
    "route_headers": (
        "this row sets custom headers that are not copied; add {replacement} by hand, "
        "then preview it with: {command}"
    ),
    "replacement_unusable": (
        "{replacement} is itself {replacement_status}; read {source_url} and choose "
        "a replacement by hand"
    ),
}


def _next_step(outcome: str, verdict: dict[str, Any]) -> str:
    if outcome == "snapshot_stale":
        return f"update llm-preflight or review {verdict['source_url']}"
    template = _NEXT.get(outcome)
    if template is None:
        return verdict["next_step"]
    return template.format_map({**verdict, "command": verdict.get("next_command")})


def _entry(
    model: dict[str, Any],
    verdict: dict[str, Any],
    listed: set[tuple[str, str]],
    today: date,
) -> dict[str, Any]:
    outcome = _outcome(verdict, model, listed, today)
    return {
        "provider": model.get("provider", "openai_compatible"),
        "model": model["model"],
        "status": verdict["status"],
        "retirement_date": verdict.get("retirement_date"),
        "source_url": verdict.get("source_url"),
        "outcome": outcome,
        "replacement": verdict.get("replacement"),
        "replacement_status": verdict.get("replacement_status"),
        "replaced_by_existing_row": outcome == "replacement_in_config",
        "smoke": None,
        "next_step": _next_step(outcome, verdict),
    }


def build_report(path: Path, today: date) -> dict[str, Any]:
    """The outcome table for one config; raises ValueError on a bad config."""
    config = _load(path)
    models = config["models"]
    listed = {
        (m.get("provider", "openai_compatible"), retirements._catalog_id(m["model"]))
        for m in models
    }
    verdicts = [
        retirement_verdict(m.get("provider", "openai_compatible"), m["model"], today)
        for m in models
    ]
    entries = [_entry(m, v, listed, today) for m, v in zip(models, verdicts)]
    warnings = []
    if "discovery" in config:
        warnings.append("discovery is ignored; only explicit models are read")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "migrate",
        "decision": worst_decision(v["decision"] for v in verdicts),
        "models": entries,
        "candidate_config": None,
        "plan": None,
        "approval": {"state": "missing"},
        "smoke": None,
        "paid_requests_made": 0,
        "warnings": warnings,
        "next_steps": list(dict.fromkeys(entry["next_step"] for entry in entries)),
    }


def exit_code(decision: str, ci: bool) -> int:
    return EXIT_CODES.get(decision, 0) if ci else 0


def _exit_line(decision: str, ci: bool) -> str:
    code = EXIT_CODES.get(decision, 0)
    if ci:
        return f"Exit {code} (--ci)."
    if code:
        return f"Exit 0 — add --ci to exit {code} on this decision."
    return "Exit 0 — --ci also exits 0 on this decision."


def format_report(report: dict[str, Any], ci: bool = False) -> str:
    """Text rendered from the report dict only."""
    lines = [
        f"Decision: {report['decision']}",
        _exit_line(report["decision"], ci),
        "Source config unchanged; nothing was written and no provider was called.",
    ]
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    for entry in report["models"]:
        replacement = entry["replacement"]
        arrow = (
            f" -> {replacement} ({entry['replacement_status']})" if replacement else ""
        )
        lines.append(
            f"  {entry['provider']}:{entry['model']} — {entry['status']} "
            f"[{entry['outcome']}]{arrow}"
        )
        lines.append(f"    Next: {entry['next_step']}")
    return "\n".join(lines) + "\n"
