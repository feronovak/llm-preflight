"""Report which provider-named replacement applies to each retired config model.

The source config is never written, no provider is called and no replacement is
inferred. The replacement is the bundled retirement row's `replacement` field
and nothing else. With an output path the replacement rows are also written to
a separate candidate config, which a human then previews and approves.
"""

from __future__ import annotations

import copy
import json
import os
import shlex
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import retirements
from .features import apply_model_aliases, apply_smoke_mode
from .providers import PROVIDER_DEFAULTS
from .redaction import redact_secrets
from .retirements import DEFAULT_MAX_AGE_DAYS, retirement_verdict, worst_decision

SCHEMA_VERSION = 1
EXIT_CODES = {"fail": 1, "inconclusive": 3}
_AFFECTED = {"retired", "retiring", "stale"}
_UNUSABLE = {"retired", "retiring"}
_COPIED = ("provider", "base_url", "api_key_env", "api_version")
_DROPPED = ("aliases", "environments", "discovery")


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


def _key_label(row: dict[str, Any]) -> str:
    env = row.get("api_key_env")
    return _printable(str(env)) if env else "the provider default"


def _row_for(
    model: dict[str, Any], entry: dict[str, Any], models: list[dict[str, Any]]
) -> tuple[tuple[str, str, str], dict[str, Any]] | None:
    """The candidate row for one entry: a new row, or the user's own, verbatim."""
    replacement = entry["replacement"]
    if entry["outcome"] == "candidate":
        key = (_provider(model), replacement, _route(model))
        return key, {"model": replacement} | {
            k: model[k] for k in _COPIED if k in model
        }
    if entry["outcome"] == "replacement_in_config":
        want = (_provider(model), replacement, _route(model))
        own = next(m for m in models if _listed_key(m) == want)
        return want, copy.deepcopy(own)
    return None


def _hand_added(row: dict[str, Any]) -> str | None:
    """Why an own row cannot be copied: redaction cannot make it safe to send."""
    if row.get("headers"):
        return "sets headers"
    url = row.get("base_url")
    if url is None:
        return None
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        bad = parts is None or bool(
            parts.username or parts.password or parts.query or parts.fragment
        )
    except ValueError:
        bad = True
    return "sets a base_url with credentials or a query" if bad else None


def _unique_rows(
    models: list[dict[str, Any]], entries: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """One row per provider and replacement; the first row wins."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    warnings: list[str] = []
    for model, entry in zip(models, entries):
        found = _row_for(model, entry, models)
        if found is None:
            continue
        (provider, replacement, _), row = found
        name = _printable(row["model"])
        reason = _hand_added(row)
        if reason:
            warnings.append(
                f"{name} {reason}, which is not copied; add it to a candidate "
                "config by hand"
            )
            continue
        kept = rows.setdefault((provider, replacement), row)
        if _route(kept) != _route(row):
            warnings.append(
                f"{name} is named on another route; the first row was kept and "
                "this route was not kept"
            )
        elif kept.get("api_key_env") != row.get("api_key_env"):
            warnings.append(
                f"{name} is named for several rows with different api_key_env; "
                f"kept {_key_label(kept)}, dropped {_key_label(row)}"
            )
    return list(rows.values()), warnings


def _candidate_config(
    config: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    if not isinstance(config.get("name", ""), str):
        raise ValueError("'name' must be a string")  # noqa: TRY004
    candidate = {k: copy.deepcopy(v) for k, v in config.items() if k not in _DROPPED}
    candidate["models"] = rows
    candidate = apply_smoke_mode(candidate)
    candidate.setdefault("save_responses", "failures")
    return candidate


def check_output(config_path: Path, output: Path, replace: bool) -> None:
    """Refuse an output path that could clobber or escape the config directory."""
    if output.parent.resolve() != config_path.parent.resolve():
        raise ValueError("--output must be in the config's directory")
    if output.resolve() == config_path.resolve():
        raise ValueError("--output cannot be the source config")
    if output.is_symlink():
        raise ValueError("--output cannot be a symbolic link")
    if output.exists() and not replace:
        raise ValueError(f"{output} exists; add --replace to overwrite it")


def _publish(temp: Path, output: Path, replace: bool) -> None:
    if replace:
        os.replace(temp, output)
        return
    os.link(temp, output)
    temp.unlink()


def _write_checked(
    output: Path,
    candidate: dict[str, Any],
    replace: bool,
    plan_for: Callable[[Path], dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Write beside `output`, plan from that file, and only then publish it."""
    handle, name = tempfile.mkstemp(
        dir=output.parent, prefix=".migrate-", suffix=".json"
    )
    temp = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(candidate, indent=2) + "\n")
        plan = plan_for(temp) if plan_for else None
        _publish(temp, output, replace)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return plan


def _quoted(path: Path) -> str:
    return shlex.quote(_printable(str(path)))


def _commands(config_path: Path, output: Path) -> tuple[str, str]:
    receipt = _quoted(output.parent / f"{output.stem}.approval.json")
    record = (
        f"llm-preflight {_quoted(output)} --dry-run --approval-receipt {receipt} "
        '--approval-note "<why you approve this spend>" '
        "--approval-expires-at <ISO-8601 time with timezone>"
    )
    run = (
        f"llm-preflight migrate {_quoted(config_path)} --output {_quoted(output)} "
        f"--run --verify-approval-receipt {receipt}"
    )
    return record, run


_UNBOUNDED_STEP = (
    "the plan is unbounded: a replacement has no bundled price; add that model to "
    "the source config with your own input_cost_per_million and "
    "output_cost_per_million, then run migrate again"
)


def build_report(
    path: Path,
    today: date,
    output: Path | None = None,
    replace: bool = False,
    plan_for: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The outcome table for one config; raises ValueError on a bad config.

    With `output`, the replacement rows are written there and `plan_for` builds
    the dry-run plan from that file, the way `--dry-run` would load it.
    """
    config = _load(path)
    if output is not None:
        check_output(path, output, replace)
    models = config["models"]
    listed = {_listed_key(m) for m in models}
    verdicts = [retirement_verdict(_provider(m), m["model"], today) for m in models]
    entries = [_entry(m, v, listed, today) for m, v in zip(models, verdicts)]
    warnings = []
    if "discovery" in config:
        warnings.append("discovery is ignored; only explicit models are read")
    rows, row_warnings = _unique_rows(models, entries)
    warnings.extend(row_warnings)
    next_steps = list(dict.fromkeys(entry["next_step"] for entry in entries))
    candidate_config = plan = None
    approval: dict[str, Any] = {"state": "missing"}
    if rows:
        candidate = _candidate_config(config, rows)
        safe = redact_secrets(candidate)
        if safe != candidate:
            warnings.append(
                "secret-shaped values were redacted in the candidate config"
            )
        candidate_config = {"path": None, "config": safe}
        if output is None:
            next_steps.append(
                "add --output PATH to write the candidate config and see its plan"
            )
        else:
            plan = _write_checked(output, safe, replace, plan_for)
            candidate_config["path"] = str(output)
            record, run = _commands(path, output)
            approval |= {"record_command": record, "run_command": run}
            if plan and plan["maximum_estimated_cost_usd"] is None:
                next_steps.append(_UNBOUNDED_STEP)
            next_steps += [f"record approval: {record}", f"then run the smoke: {run}"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "migrate",
        "decision": worst_decision(v["decision"] for v in verdicts),
        "models": entries,
        "candidate_config": candidate_config,
        "plan": plan,
        "approval": approval,
        "smoke": None,
        "paid_requests_made": 0,
        "warnings": warnings,
        "next_steps": next_steps,
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


def _written_line(report: dict[str, Any]) -> str:
    candidate = report["candidate_config"]
    if candidate and candidate["path"]:
        return (
            "Source config unchanged; only the candidate config was written "
            "and no provider was called."
        )
    return "Source config unchanged; nothing was written and no provider was called."


def _plan_line(plan: dict[str, Any]) -> str:
    maximum = plan["maximum_estimated_cost_usd"]
    estimated = plan["estimated_cost_usd"]
    return (
        f"Plan: {plan['requests']} requests, estimated "
        f"{'unknown' if estimated is None else f'${estimated}'}, maximum "
        f"{'unbounded (a model has no price)' if maximum is None else f'${maximum}'}"
    )


def _candidate_lines(report: dict[str, Any]) -> list[str]:
    candidate = report["candidate_config"]
    if not candidate:
        return []
    if not candidate["path"]:
        return ["Candidate config: not written (add --output PATH)"]
    approval = report["approval"]
    lines = [f"Candidate config: {_printable(candidate['path'])}"]
    if report["plan"]:
        lines.append(_plan_line(report["plan"]))
        if report["plan"]["maximum_estimated_cost_usd"] is None:
            lines.append(f"Next: {_UNBOUNDED_STEP}")
    lines += [
        f"Approval: {approval['state']} — no receipt is recorded for this plan",
        f"  Record approval: {approval['record_command']}",
        f"  Then run the smoke: {approval['run_command']}",
    ]
    return lines


def format_report(report: dict[str, Any], ci: bool = False) -> str:
    """Text rendered from the report dict only."""
    lines = [
        f"Decision: {report['decision']}",
        _exit_line(report["decision"], ci),
        _written_line(report),
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
    lines.extend(_candidate_lines(report))
    return "\n".join(lines) + "\n"
