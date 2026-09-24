"""Safe, offline renderers for saved benchmark results."""

from __future__ import annotations

import html
import math
import re
from collections.abc import Mapping
from typing import Any

from .decision import build_decision

_SCHEMA_VERSION = 1
_SOURCE_LABELS = {
    "official snapshot": "official provider snapshot",
    "live catalog": "live provider catalogue",
    "openrouter catalog": "OpenRouter catalogue",
    "user override": "explicit price override",
    "synthetic fixture": "synthetic fixture data",
    "unknown": "source unavailable",
}
_REGRESSION_LABELS = {
    "latency_p95",
    "success_rate",
    "valid_output_rate",
    "cost",
    "removed",
}


def _validate_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TypeError("saved result must be a JSON object")
    if (
        type(result.get("schema_version")) is not int
        or result.get("schema_version") != _SCHEMA_VERSION
    ):
        raise ValueError(
            "saved result schema version 1 is required; unknown major schemas are not supported"
        )
    models = result.get("models")
    if (
        not isinstance(models, list)
        or not models
        or any(not isinstance(model, dict) for model in models)
    ):
        raise ValueError("saved result models must be a non-empty list of objects")
    for model in models:
        if "summary" in model and not isinstance(model["summary"], dict):
            raise ValueError("saved result model summary must be an object")
        samples = model.get("samples", [])
        if not isinstance(samples, list) or any(
            not isinstance(sample, dict) for sample in samples
        ):
            raise ValueError("saved result model samples must be a list of objects")
        profiles = model.get("profiles", [])
        if not isinstance(profiles, list) or any(
            not isinstance(profile, dict)
            or not isinstance(profile.get("summary", {}), dict)
            for profile in profiles
        ):
            raise ValueError("saved result model profiles must contain summary objects")
        summaries = (
            [profile.get("summary", {}) for profile in profiles]
            if profiles
            else [model.get("summary", {})]
        )
        for summary in summaries:
            for field in ("requests", "failed", "contract_only_failures"):
                if field == "contract_only_failures" and field not in summary:
                    continue
                value = summary.get(field, 0)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(
                        f"saved result model summary {field} must be a non-negative integer"
                    )
            if "valid_output_rate" in summary:
                value = summary["valid_output_rate"]
                if value is not None and _rate(value) is None:
                    raise ValueError(
                        "saved result valid_output_rate must be between 0 and 1"
                    )
    coverage = result.get("pricing_coverage", {})
    if not isinstance(coverage, dict):
        raise TypeError("saved result pricing_coverage must be an object")
    if not isinstance(coverage.get("summary", {}), dict):
        raise TypeError("saved result pricing_coverage summary must be an object")
    billable = coverage.get("summary", {}).get("billable")
    if billable is not None and (
        isinstance(billable, bool) or not isinstance(billable, int) or billable < 0
    ):
        raise ValueError("saved result pricing billable count must be non-negative")
    coverage_models = coverage.get("models", [])
    if not isinstance(coverage_models, list) or any(
        not isinstance(model, dict) for model in coverage_models
    ):
        raise ValueError(
            "saved result pricing_coverage models must be a list of objects"
        )
    if any(
        entry.get("status") is not None and not isinstance(entry.get("status"), str)
        for entry in coverage_models
    ):
        raise ValueError("saved result pricing status must be a string")
    baseline = result.get("baseline_diff")
    if baseline is not None and not isinstance(baseline, dict):
        raise ValueError("saved result baseline_diff must be an object")
    if isinstance(baseline, dict):
        baseline_models = baseline.get("models", [])
        if not isinstance(baseline_models, list) or any(
            not isinstance(model, dict) for model in baseline_models
        ):
            raise ValueError(
                "saved result baseline_diff models must be a list of objects"
            )
    return result


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _rate(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and 0 <= number <= 1 else None


def _text(value: Any, limit: int = 120) -> str:
    if not isinstance(value, str):
        return "unknown"
    return value[:limit]


def _identifier(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._:/@+\-]", "?", _text(value))


def _model_id(model: Mapping[str, Any]) -> str:
    provider = _identifier(model.get("provider", "unknown"))
    model_id = _identifier(model.get("model", "unknown"))
    return f"{provider}/{model_id}"


def _model_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for model in result["models"]:
        profiles = model.get("profiles") or []
        summaries = (
            [
                (f"profile {index}", profile.get("summary", {}))
                for index, profile in enumerate(profiles, 1)
            ]
            if profiles
            else [("", model.get("summary", {}))]
        )
        for profile_label, summary in summaries:
            if not isinstance(summary, dict):
                continue
            rows.append(
                {
                    "model": _model_id(model),
                    "profile": profile_label,
                    "requests": _number(summary.get("requests")),
                    "failed": _number(summary.get("failed")),
                    "contract_failures": _number(summary.get("contract_only_failures")),
                    "valid_rate": _rate(summary.get("valid_output_rate")),
                    "success_rate": _rate(summary.get("success_rate")),
                    "latency_p50": _number(
                        (summary.get("latency_seconds") or {}).get("p50")
                        if isinstance(summary.get("latency_seconds", {}), dict)
                        else None
                    ),
                    "latency_p95": _number(
                        (summary.get("latency_seconds") or {}).get("p95")
                        if isinstance(summary.get("latency_seconds", {}), dict)
                        else None
                    ),
                    "input_tokens": _number(summary.get("input_tokens")),
                    "output_tokens": _number(summary.get("output_tokens")),
                    "cost": _number(summary.get("estimated_cost_usd")),
                }
            )
    return rows


def _decision(result: dict[str, Any]) -> tuple[str, str]:
    # Recompute from the schema-v1 evidence; never render free-form decision text.
    decision = build_decision(result)
    state = decision.get("state", "inconclusive")
    reason = decision.get("reason_code", "unknown")
    return _text(state, 24), _text(reason, 60)


def _comparability(result: dict[str, Any]) -> tuple[str, list[str], str]:
    baseline = result.get("baseline_diff")
    if not isinstance(baseline, dict):
        return "not compared", [], "not compared"
    comparability = baseline.get("comparability")
    if not isinstance(comparability, str) or comparability not in {
        "compatible",
        "incompatible",
    }:
        comparability = "unknown"
    baseline_state = (
        "inconclusive"
        if comparability != "compatible"
        else "regression"
        if baseline.get("ok") is False
        else "pass"
        if baseline.get("ok") is True
        else "unknown"
    )
    regressions: set[str] = set()
    for row in baseline.get("models", []):
        if not isinstance(row, dict):
            continue
        values = row.get("regressions", [])
        if isinstance(values, list):
            regressions.update(
                value
                for value in values
                if isinstance(value, str) and value in _REGRESSION_LABELS
            )
    return str(comparability), sorted(regressions), baseline_state


def _pricing_rows(result: dict[str, Any]) -> list[dict[str, str]]:
    coverage = result.get("pricing_coverage") or {}
    entries = coverage.get("models", [])
    if not isinstance(entries, list):
        return []
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if not isinstance(status, str):
            continue
        source = entry.get("source")
        if not isinstance(source, str):
            source = "unknown"
        source_label = _SOURCE_LABELS.get(source, "recorded pricing source")
        as_of = entry.get("as_of")
        rows.append(
            {
                "model": _model_id(entry),
                "status": status[:40],
                "source": source_label,
                "as_of": _text(as_of, 40) if isinstance(as_of, str) else "undated",
            }
        )
    return rows


def _format_number(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _format_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _markdown_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _report_data(payload: Any) -> dict[str, Any]:
    result = _validate_result(payload)
    state, reason = _decision(result)
    comparability, regressions, baseline_state = _comparability(result)
    rows = _model_rows(result)
    requests = sum(row["requests"] or 0 for row in rows)
    input_tokens = sum(row["input_tokens"] or 0 for row in rows)
    output_tokens = sum(row["output_tokens"] or 0 for row in rows)
    costs = [row["cost"] for row in rows]
    cost = None if not costs or any(value is None for value in costs) else sum(costs)
    contract_failures = (
        None
        if not rows or any(row["contract_failures"] is None for row in rows)
        else sum(row["contract_failures"] for row in rows)
    )
    weighted_valid = sum(
        (row["requests"] or 0) * row["valid_rate"]
        for row in rows
        if row["valid_rate"] is not None and row["requests"] is not None
    )
    valid_requests = sum(
        row["requests"] or 0
        for row in rows
        if row["valid_rate"] is not None and row["requests"] is not None
    )
    return {
        "decision": state,
        "reason": reason,
        "comparability": comparability,
        "baseline_state": baseline_state,
        "regressions": regressions,
        "models": rows,
        "requests": requests,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
        "valid_rate": weighted_valid / valid_requests if valid_requests else None,
        "contract_failures": contract_failures,
        "pricing": _pricing_rows(result),
    }


def render_job_summary(payload: Any) -> str:
    """Return a compact GitHub-flavored Markdown summary with no prompt content."""
    data = _report_data(payload)
    lines = [
        "## LLM Preflight",
        "",
        f"**Decision:** {data['decision']} (`{data['reason']}`)",
        f"**Comparability:** {data['comparability']}",
        f"**Baseline comparison:** {data['baseline_state']}",
    ]
    if data["regressions"]:
        lines.append(f"**Baseline regressions:** {', '.join(data['regressions'])}")
    lines.extend(
        [
            "",
            "| Model | Contract validity | Requests | Latency p95 | Input/output tokens | Est. cost |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in data["models"]:
        label = _markdown_text(row["model"])
        if row["profile"]:
            label += f" ({row['profile']})"
        tokens = f"{_format_number(row['input_tokens'], 0)}/{_format_number(row['output_tokens'], 0)}"
        row_cost = row["cost"]
        cost = "n/a" if row_cost is None else f"${row_cost:.6f}"
        lines.append(
            f"| `{label}` | {_format_percent(row['valid_rate'])} | "
            f"{_format_number(row['requests'], 0)} | "
            f"{_format_number(row['latency_p95'])}s | {tokens} | {cost} |"
        )
    total_cost = data["cost"]
    cost_text = "n/a" if total_cost is None else f"${total_cost:.6f}"
    lines.extend(
        [
            "",
            (
                f"Requests: {_format_number(data['requests'], 0)} · "
                f"Contract-only failures: {_format_number(data['contract_failures'], 0)} · "
                f"Usage: {_format_number(data['input_tokens'], 0)} input / "
                f"{_format_number(data['output_tokens'], 0)} output tokens · "
                f"Estimated cost: {cost_text}"
            ),
            "",
            "Pricing provenance:",
        ]
    )
    if data["pricing"]:
        lines.extend(
            f"- `{_markdown_text(item['model'])}`: "
            f"{_markdown_text(item['status'])}; {_markdown_text(item['source'])}; "
            f"{_markdown_text(item['as_of'])}"
            for item in data["pricing"]
        )
    else:
        lines.append("- No pricing provenance recorded.")
    lines.extend(
        [
            "",
            (
                "Limitations: results reflect this configured workload and provider route; "
                "small samples are directional, not a universal model ranking."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def render_report_html(payload: Any) -> str:
    """Render a self-contained offline report from a schema-v1 result."""
    data = _report_data(payload)
    escaped = html.escape
    rows = []
    for row in data["models"]:
        label = row["model"]
        if row["profile"]:
            label += f" (profile {row['profile'].split()[-1]})"
        row_cost = row["cost"]
        row_cost_text = "n/a" if row_cost is None else f"${row_cost:.6f}"
        rows.append(
            "<tr>"
            f'<th scope="row">{escaped(label)}</th>'
            f"<td>{escaped(_format_percent(row['valid_rate']))}</td>"
            f"<td>{escaped(_format_number(row['requests'], 0))}</td>"
            f"<td>{escaped(_format_number(row['latency_p50']))} / {escaped(_format_number(row['latency_p95']))} s</td>"
            f"<td>{escaped(_format_number(row['input_tokens'], 0))} / {escaped(_format_number(row['output_tokens'], 0))}</td>"
            f"<td>{escaped(row_cost_text)}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="6">No model measurements recorded.</td></tr>')
    pricing = (
        "".join(
            "<li>"
            f"<code>{escaped(item['model'])}</code>: {escaped(item['status'])}; "
            f"{escaped(item['source'])}; {escaped(item['as_of'])}"
            "</li>"
            for item in data["pricing"]
        )
        or "<li>No pricing provenance recorded.</li>"
    )
    regressions = (
        "<p>Baseline regressions: " + escaped(", ".join(data["regressions"])) + "</p>"
        if data["regressions"]
        else ""
    )
    cost = "n/a" if data["cost"] is None else f"${data['cost']:.6f}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LLM Preflight report</title>
<style>
body {{ font: 16px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 72rem; padding: 0 1rem; color: #17202a; }}
h1, h2 {{ line-height: 1.2; }}
.decision {{ border-left: .35rem solid #6b46c1; padding: .75rem 1rem; background: #f5f1ff; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #d8dee8; padding: .6rem; text-align: left; }}
th {{ background: #f4f6f8; }}
code {{ overflow-wrap: anywhere; }}
.limitations {{ color: #485563; }}
</style>
</head>
<body>
<h1>LLM Preflight report</h1>
<section class="decision" aria-label="Decision">
<h2>Decision: {escaped(data["decision"])}</h2>
<p>Reason: <code>{escaped(data["reason"])}</code></p>
<p>Comparability: {escaped(data["comparability"])}</p>
<p>Baseline comparison: {escaped(data["baseline_state"])}</p>
{regressions}
</section>
<h2>Results</h2>
<p>Contract validity: {escaped(_format_percent(data["valid_rate"]))}; contract-only failures: {escaped(_format_number(data["contract_failures"], 0))}</p>
<table>
<thead><tr><th>Provider/model</th><th>Contract validity</th><th>Requests</th><th>Latency p50 / p95</th><th>Input / output tokens</th><th>Estimated cost</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
<h2>Totals</h2>
<p>Requests: {escaped(_format_number(data["requests"], 0))}; usage: {escaped(_format_number(data["input_tokens"], 0))} input / {escaped(_format_number(data["output_tokens"], 0))} output tokens; estimated cost: {escaped(cost)}</p>
<h2>Pricing provenance</h2>
<ul>{pricing}</ul>
<p class="limitations">Limitations: results reflect this configured workload and provider route; small samples are directional, not a universal model ranking.</p>
</body>
</html>
"""
