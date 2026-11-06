"""Report which provider-named replacement applies to each retired config model.

The source config is never written and no replacement is inferred. No provider
is called unless `--run` finds a recorded approval receipt for the written plan.
The replacement is the bundled retirement row's `replacement` field and nothing
else. With an output path the replacement rows are also written to
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

from . import retirements
from .approval import load_approval_receipt, verify_approval_receipt
from .features import apply_model_aliases, apply_smoke_mode
from .providers import PROVIDER_DEFAULTS
from .redaction import redact_secrets
from .retirements import DEFAULT_MAX_AGE_DAYS, retirement_verdict, worst_decision

SCHEMA_VERSION = 1
EXIT_CODES = {"fail": 1, "inconclusive": 3}
_AFFECTED = {"retired", "retiring", "stale"}
_UNUSABLE = {"retired", "retiring"}
_COPIED = ("provider", "base_url", "api_key_env", "api_version")
_DROPPED = ("aliases", "environments", "discovery", "base_url")


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


def _field_label(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    return _printable(str(value)) if value else "the provider default"


def _row_for(
    model: dict[str, Any], entry: dict[str, Any], models: list[dict[str, Any]]
) -> tuple[tuple[str, str], dict[str, Any]] | None:
    """The candidate row for one entry: a new row, or the user's own, verbatim."""
    replacement = entry["replacement"]
    key = (_provider(model), replacement)
    if entry["outcome"] == "candidate":
        return key, {"model": replacement} | {
            k: model[k] for k in _COPIED if k in model
        }
    if entry["outcome"] == "replacement_in_config":
        want = (*key, _route(model))
        return key, copy.deepcopy(next(m for m in models if _listed_key(m) == want))
    return None


def _hand_added(row: dict[str, Any]) -> str | None:
    """Why an own row is not copied: only a public route can be copied safely."""
    if row.get("headers"):
        return "sets headers"
    if _custom_base_url(row):
        return "sets a custom base_url"
    return None


def _unique_rows(
    models: list[dict[str, Any]], entries: list[dict[str, Any]]
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    """One public-route row per provider and replacement; the first row wins."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    warnings: list[str] = []
    for model, entry in zip(models, entries):
        found = _row_for(model, entry, models)
        if found is None:
            continue
        key, row = found
        name = _printable(row["model"])
        reason = _hand_added(row)
        if reason:
            warnings.append(
                f"{name} {reason}, which is not copied; add it to a candidate "
                "config by hand"
            )
            continue
        kept = rows.setdefault(key, row)
        warnings.extend(
            f"{name} is named for several rows with different {field}; kept "
            f"{_field_label(kept, field)}, dropped {_field_label(row, field)}"
            for field in ("api_key_env", "api_version")
            if kept.get(field) != row.get(field)
        )
    return rows, list(dict.fromkeys(warnings))


def _redacted_structure(before: Any, after: Any, path: str = "") -> list[str]:
    """JSON paths whose non-string value redaction replaced, keys only."""
    if isinstance(before, dict) and isinstance(after, dict):
        found: list[str] = []
        for (_, value), (key, masked) in zip(before.items(), after.items()):
            found += _redacted_structure(value, masked, f"{path}.{key}".lstrip("."))
        return found
    if isinstance(before, list) and isinstance(after, list):
        found = []
        for index, (value, masked) in enumerate(zip(before, after)):
            found += _redacted_structure(value, masked, f"{path}[{index}]")
        return found
    return [] if isinstance(before, str) or before == after else [path]


def _structure_message(paths: list[str]) -> str:
    return (
        "redaction would replace non-string values in the candidate config "
        f"({_printable(', '.join(paths))}); no candidate is written"
    )


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


def check_output(
    config_path: Path, output: Path, replace: bool, reading: bool = False
) -> None:
    """Refuse an output path that could clobber or escape the config directory."""
    if output.parent.resolve() != config_path.parent.resolve():
        raise ValueError("--output must be in the config's directory")
    if output.exists() and output.samefile(config_path):
        raise ValueError("--output cannot be the source config")
    if output.is_symlink():
        raise ValueError("--output cannot be a symbolic link")
    if output.exists() and not replace and not reading:
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
_PROMPTS_ONLY_STEP = (
    "select a custom prompt before running the benchmark: this config has only "
    "'prompts', so the smoke would stop; add a 'prompt' to the source config, "
    "then run migrate again"
)


_ADOPT = (
    "smoke done for {replacement}; adopting it in your config and code is your "
    "step, migrate never edits them and the source config is unchanged"
)


def _after_smoke(replacement: str, smoke: dict[str, Any]) -> str:
    """Adoption only after a pass; otherwise the reason and the saved result."""
    if smoke["state"] == "pass":
        return _ADOPT.format(replacement=replacement)
    return (
        f"smoke {smoke['state']} for {replacement}: {smoke['reason']}; read the "
        f"saved result at {_printable(str(smoke['result_path']))} and do not adopt "
        f"{replacement} until a smoke passes"
    )


def _rewrite_command(config_path: Path, output: Path) -> str:
    return (
        f"llm-preflight migrate {_quoted(config_path)} --output {_quoted(output)} "
        "--replace"
    )


def _approval(receipt_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Receipt state against the plan; an unreadable receipt is reported."""
    try:
        receipt = load_approval_receipt(receipt_path)
    except FileNotFoundError:
        return {"state": "missing", "reason": "no receipt file at that path"}
    except (OSError, ValueError, RecursionError):
        return {"state": "invalid", "reason": "receipt file is unreadable"}
    try:
        verdict = verify_approval_receipt(receipt, plan)
    except (ValueError, OverflowError):
        return {"state": "invalid", "reason": "receipt expiry is invalid"}
    state, reason = verdict["state"], verdict["reason"]
    if state == "recorded":
        bounds = {
            "possible_requests": plan.get("possible_requests"),
            "maximum_estimated_cost_usd": plan.get("maximum_estimated_cost_usd"),
        }
        if receipt.get("bounds") != bounds:
            state, reason = "mismatch", "receipt bounds differ from the plan's"
        elif bounds["maximum_estimated_cost_usd"] is None:
            state, reason = "unbounded", "the plan has no maximum cost"
    return {"state": state, "reason": reason}


def _disk_difference(output: Path, candidate: dict[str, Any]) -> str | None:
    """Why the file on disk is not the derived candidate; None when it is."""
    if not output.exists():
        return "the candidate file does not exist"
    try:
        same = json.loads(output.read_text(encoding="utf-8")) == candidate
    except (OSError, ValueError, RecursionError):
        same = False
    return None if same else "the file on disk is not what migrate derives now"


def _smoked_rows(
    models: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    rows: dict[tuple[str, str], dict[str, Any]],
) -> list[int]:
    """Source rows a smoke covers: written row, same effective route."""
    covered = []
    for index, (model, entry) in enumerate(zip(models, entries)):
        if entry["outcome"] not in {"candidate", "replacement_in_config"}:
            continue
        row = rows.get((_provider(model), entry["replacement"]))
        if row is not None and _route(row) == _route(model):
            covered.append(index)
    return covered


def _attempts_sent(sample: dict[str, Any]) -> int:
    """Provider attempts one sample made; a missing key stops before any call.

    A rejected key (HTTP 401 or 403) shares the `credentials` category but was sent.
    """
    if sample.get(
        "failure_category"
    ) == "credentials" and "environment variable" in str(sample.get("error")):
        return 0
    return int(sample.get("attempts", 1))


def _smoke_summary(outcome: dict[str, Any]) -> dict[str, Any]:
    result = outcome["result"]
    decision = result["decision"]
    return {
        "state": decision["state"],
        "reason": decision.get("reason"),
        "result_path": outcome["path"],
        "requests": sum(
            _attempts_sent(sample)
            for model in result["models"]
            for sample in model.get("samples", [])
        ),
    }


def build_report(
    path: Path,
    today: date,
    output: Path | None = None,
    replace: bool = False,
    plan_for: Callable[[Path], dict[str, Any]] | None = None,
    run: bool = False,
    receipt: Path | None = None,
    smoke_for: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The outcome table for one config; raises ValueError on a bad config.

    With `output`, the replacement rows are written there and `plan_for` builds
    the dry-run plan from that file, the way `--dry-run` would load it. With
    `run` or `receipt` the file must already exist: it is compared, never
    written, and `smoke_for` runs only when the receipt gate passes.
    """
    reading = run or receipt is not None
    config = _load(path)
    if output is not None:
        check_output(path, output, replace, reading)
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
    candidate_config = plan = smoke = None
    approval: dict[str, Any] = {"state": "missing"}
    decisions = [v["decision"] for v in verdicts]
    if rows:
        candidate = _candidate_config(config, list(rows.values()))
        safe = redact_secrets(candidate)
        broken = _redacted_structure(candidate, safe)
        if broken and output is not None:
            raise ValueError(_structure_message(broken))
        if broken:
            warnings.append(_structure_message(broken))
        elif safe != candidate:
            warnings.append(
                "secret-shaped values were redacted in the candidate config"
            )
        if not broken:
            candidate_config = {"path": None, "config": safe}
            if output is None:
                next_steps.append(
                    "add --output PATH to write the candidate config and see its plan"
                )
            else:
                prompts_only = (
                    "prompts" in safe
                    and "prompt" not in safe
                    and "profiles" not in safe
                )
                difference = _disk_difference(output, safe) if reading else None
                if difference:
                    approval = {"state": "candidate_changed", "reason": difference}
                elif reading:
                    plan = plan_for(output) if plan_for else None
                else:
                    plan = _write_checked(output, safe, replace, plan_for)
                candidate_config["path"] = str(output)
                record, run_command = _commands(path, output)
                if plan and receipt is not None:
                    approval = _approval(receipt, plan)
                if plan and plan["maximum_estimated_cost_usd"] is None:
                    next_steps.append(_UNBOUNDED_STEP)
                if prompts_only:
                    warnings.append(_PROMPTS_ONLY_STEP)
                    next_steps.append(_PROMPTS_ONLY_STEP)
                if difference:
                    next_steps.append(
                        f"{difference}; rewrite it, then record a new approval: "
                        f"{_rewrite_command(path, output)}"
                    )
                else:
                    approval |= {"record_command": record, "run_command": run_command}
                    next_steps += [
                        f"record approval: {record}",
                        f"then run the smoke: {run_command}",
                    ]
                if run and approval["state"] == "recorded" and smoke_for:
                    smoke = _smoke_summary(smoke_for(output))
                    for index in _smoked_rows(models, entries, rows):
                        decisions[index] = smoke["state"]
                        entries[index]["smoke"] = {"state": smoke["state"]}
                        entries[index]["next_step"] = _after_smoke(
                            entries[index]["replacement"], smoke
                        )
                    next_steps = list(
                        dict.fromkeys(entry["next_step"] for entry in entries)
                    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "migrate",
        "decision": worst_decision(decisions),
        "models": entries,
        "candidate_config": candidate_config,
        "plan": plan,
        "approval": approval,
        "smoke": smoke,
        "paid_requests_made": smoke["requests"] if smoke else 0,
        "warnings": warnings,
        "next_steps": next_steps,
    }
    redacted: dict[str, Any] = redact_secrets(report)
    return redacted


def exit_code(decision: str, ci: bool, run: bool = False) -> int:
    return EXIT_CODES.get(decision, 0) if ci or run else 0


def _exit_line(decision: str, ci: bool, run: bool) -> str:
    code = EXIT_CODES.get(decision, 0)
    if run:
        return f"Exit {code} (--run)."
    if ci:
        return f"Exit {code} (--ci)."
    if code:
        return f"Exit 0 — add --ci to exit {code} on this decision."
    return "Exit 0 — --ci also exits 0 on this decision."


def _written_line(report: dict[str, Any], reading: bool) -> str:
    if report["smoke"]:
        return (
            "Source config unchanged; only the smoke result files were written and "
            f"{report['paid_requests_made']} provider requests were made."
        )
    if reading:
        return (
            "Source config unchanged; nothing was written and no provider was called."
        )
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
    reason = approval.get("reason", "no receipt is recorded for this plan")
    lines.append(f"Approval: {approval['state']} — {reason}")
    if report["smoke"]:
        smoke = report["smoke"]
        lines.append(
            f"Smoke: {smoke['state']} ({smoke['requests']} requests); "
            f"result {_printable(str(smoke['result_path']))}"
        )
        return lines
    if approval["state"] == "candidate_changed":
        lines.extend(
            f"Next: {step}"
            for step in report["next_steps"]
            if step.startswith(approval["reason"])
        )
    if "record_command" in approval:
        lines += [
            f"  Record approval: {approval['record_command']}",
            f"  Then run the smoke: {approval['run_command']}",
        ]
    return lines


def format_report(
    report: dict[str, Any], ci: bool = False, run: bool = False, reading: bool = False
) -> str:
    """Text rendered from the report dict only."""
    lines = [
        f"Decision: {report['decision']}",
        _exit_line(report["decision"], ci, run),
        _written_line(report, reading or run),
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
