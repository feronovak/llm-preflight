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
from .providers import PROVIDER_DEFAULTS
from .redaction import redact_secrets
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
    except RecursionError:
        raise ValueError(f"{path} is nested too deeply") from None
    if not isinstance(config, dict):
        raise ValueError(f"{path} must hold a JSON object")  # noqa: TRY004
    models = config.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("config must list at least one entry under 'models'")
    if not isinstance(config.get("aliases", {}), dict):
        raise ValueError("'aliases' must be an object")  # noqa: TRY004
    config = apply_model_aliases(config)
    models = config["models"]
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


def _provider(model: dict[str, Any]) -> str:
    return model.get("provider", "openai_compatible")


def _public(model: dict[str, Any], key: str) -> str | None:
    return PROVIDER_DEFAULTS.get(_provider(model), {}).get(key)


def _route(model: dict[str, Any]) -> str:
    """The effective base URL, compared the way pricing does."""
    return str(model.get("base_url", _public(model, "base_url"))).rstrip("/")


def _custom_base_url(model: dict[str, Any]) -> bool:
    return "base_url" in model and _route(model) != _public(model, "base_url")


def _custom_api_key_env(model: dict[str, Any]) -> bool:
    env = model.get("api_key_env")
    return bool(env) and env != _public(model, "api_key_env")


def _listed_key(model: dict[str, Any]) -> tuple[str, str, str]:
    return (_provider(model), retirements._catalog_id(model["model"]), _route(model))


def _outcome(
    verdict: dict[str, Any],
    model: dict[str, Any],
    listed: set[tuple[str, str, str]],
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
    if (_provider(model), replacement, _route(model)) in listed:
        return "replacement_in_config"
    if _custom_base_url(model):
        return "route_base_url"
    if model.get("headers"):
        return "route_headers"
    return "candidate"


_NEXT = {
    "candidate": "{replacement} is the provider-named replacement; preview it with: {command}",
    "replacement_in_config": "{replacement} is already in this config; run --dry-run on this config",
    "route_base_url": (
        "the provider names {replacement} for its public route, but this row sets "
        "a custom base_url; check that your route serves {replacement}, add it to "
        "this config by hand with your own prices, then run --dry-run on this config"
    ),
    "route_headers": (
        "this row sets custom headers that are not copied; add {replacement} by hand, "
        "then run --dry-run on this config"
    ),
    "replacement_unusable": (
        "{replacement} is itself {replacement_status}; read {source_url} and choose "
        "a replacement by hand"
    ),
}
_NEXT_CANDIDATE_KEY_ENV = (
    "{replacement} is the provider-named replacement; keep this row's api_key_env "
    "when you add it; preview it with: {command}"
)


def _next_step(outcome: str, verdict: dict[str, Any], model: dict[str, Any]) -> str:
    if outcome == "snapshot_stale":
        return f"update llm-preflight or review {verdict['source_url']}"
    template = _NEXT.get(outcome)
    if template is None:
        return verdict["next_step"]
    if outcome == "candidate" and _custom_api_key_env(model):
        template = _NEXT_CANDIDATE_KEY_ENV
    return template.format_map({**verdict, "command": verdict.get("next_command")})


def _printable(text: str) -> str:
    """Escape control characters so a model ID cannot forge report lines."""
    return "".join(
        ch if ch.isprintable() else ch.encode("unicode_escape").decode() for ch in text
    )


def _entry(
    model: dict[str, Any],
    verdict: dict[str, Any],
    listed: set[tuple[str, str, str]],
    today: date,
) -> dict[str, Any]:
    outcome = _outcome(verdict, model, listed, today)
    stale = outcome == "snapshot_stale"
    return {
        "provider": _printable(_provider(model)),
        "model": _printable(model["model"]),
        "status": verdict["status"],
        "retirement_date": verdict.get("retirement_date"),
        "source_url": verdict.get("source_url"),
        "outcome": outcome,
        "replacement": verdict.get("replacement"),
        "replacement_status": None if stale else verdict.get("replacement_status"),
        "replaced_by_existing_row": outcome == "replacement_in_config",
        "smoke": None,
        "next_step": _next_step(outcome, verdict, model),
    }


def build_report(path: Path, today: date) -> dict[str, Any]:
    """The outcome table for one config; raises ValueError on a bad config."""
    config = _load(path)
    models = config["models"]
    listed = {_listed_key(m) for m in models}
    verdicts = [retirement_verdict(_provider(m), m["model"], today) for m in models]
    entries = [_entry(m, v, listed, today) for m, v in zip(models, verdicts)]
    warnings = []
    if "discovery" in config:
        warnings.append("discovery is ignored; only explicit models are read")
    report = {
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
    redacted: dict[str, Any] = redact_secrets(report)
    return redacted


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
        arrow = f" -> {replacement}" if replacement else ""
        if entry["replacement_status"]:
            arrow += f" ({entry['replacement_status']})"
        lines.append(
            f"  {entry['provider']}:{entry['model']} — {entry['status']} "
            f"[{entry['outcome']}]{arrow}"
        )
        if entry["retirement_date"]:
            lines.append(f"    Date: {entry['retirement_date']}")
        if entry["source_url"]:
            lines.append(f"    Source: {entry['source_url']}")
        lines.append(f"    Next: {entry['next_step']}")
    return "\n".join(lines) + "\n"
