"""Safe, offline renderers for saved benchmark results."""

from __future__ import annotations

import html
import math
import re
import textwrap
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import PurePath
from typing import Any

from .attestation import printable
from .client import observed_model
from .decision import build_decision, legacy_cost_evidence
from .retirements import retirement_verdict

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
CARD_LIMITS = "Does not certify: accuracy · safety · production behaviour"
_CARD_WIDTH = 600
_CARD_MARGIN = 20
_CARD_VALUE_X = 132
_CARD_LINE = 22
# A 14px monospace glyph is about 8.4px wide; 52 of them fill the value column.
_CARD_VALUE_CHARS = 52
_CARD_SANS = "Helvetica, Arial, sans-serif"
_CARD_MONO = "ui-monospace, Menlo, Consolas, DejaVu Sans Mono, monospace"
# The band is the card's only colour. Its word carries the verdict, so the
# card reads the same in grayscale; each pair keeps at least 4.5:1 contrast.
_CARD_BANDS = {
    "pass": ("PASS", "#1a7f37", "#ffffff"),
    "inconclusive": ("INCONCLUSIVE", "#f2c94c", "#000000"),
    "fail": ("FAIL", "#cf222e", "#ffffff"),
    "expired": ("EXPIRED", "#6e7781", "#ffffff"),
}
# The step that clears each blocking warning decision.py raises, matched on
# the warning's opening words; a new warning falls back to a generic step.
_CARD_REMEDIATIONS = (
    ("Mock-only runs", "run the bounded check against a live provider route"),
    ("Pricing is ", "price every route (--pricing-check), then rerun the check"),
    ("Legacy artifact", "rerun the check with a current llm-preflight"),
    ("Unobserved retry usage", "rerun until every request reports its usage"),
    ("Missing or invalid usage", "rerun until every request reports its usage"),
    (
        "Cost confidence is ",
        "rerun with every route priced and every request reporting usage",
    ),
)
_CARD_FALLBACK_REMEDIATION = "resolve this warning, then rerun the bounded check"


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
                    "input_tokens": _usage_value(summary, "input_tokens"),
                    "output_tokens": _usage_value(summary, "output_tokens"),
                    "cost": _number(summary.get("estimated_cost_usd")),
                }
            )
    return rows


def _usage_value(summary: dict[str, Any], field: str) -> float | None:
    if summary.get("cost_coverage", {}).get("unobserved_retry_requests", 0):
        return None
    coverage = summary.get("usage_coverage")
    if isinstance(coverage, dict) and coverage.get(field, 0) < summary.get(
        "requests", 0
    ):
        return None
    return _number(summary.get(field))


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
    legacy = legacy_cost_evidence(result)
    if legacy:
        for row in rows:
            row["cost"] = None
            row["input_tokens"] = row["output_tokens"] = None
    requests = sum(row["requests"] or 0 for row in rows)
    input_tokens = (
        None
        if any(row["input_tokens"] is None for row in rows)
        else sum(row["input_tokens"] for row in rows)
    )
    output_tokens = (
        None
        if any(row["output_tokens"] is None for row in rows)
        else sum(row["output_tokens"] for row in rows)
    )
    costs = [row["cost"] for row in rows]
    cost = None if not costs or any(value is None for value in costs) else sum(costs)
    if "cost_coverage" in result:
        # Modern results account for warmups and partial evidence at sample level.
        cost = _number(result.get("total_estimated_cost_usd"))
        requests = sum(
            model.get(phase, {}).get("requests", 0)
            for model in result["models"]
            for phase in ("summary", "warmup_summary")
        )
        usage_summary = {
            "requests": requests,
            "usage_coverage": result.get("usage_coverage", {}),
            "cost_coverage": result.get("cost_coverage", {}),
        }
        input_tokens = _usage_value(
            {**usage_summary, "input_tokens": result.get("total_input_tokens")},
            "input_tokens",
        )
        output_tokens = _usage_value(
            {**usage_summary, "output_tokens": result.get("total_output_tokens")},
            "output_tokens",
        )
    subtotal = (
        _number(result.get("priced_cost_usd")) if cost is None and not legacy else None
    )
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
        "priced_cost": subtotal,
        "legacy_cost_evidence": legacy,
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
    if data["legacy_cost_evidence"]:
        lines.append("Legacy artifact: cost completeness is unverified.")
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
    if data["priced_cost"] is not None:
        cost_text += f" · Known cost subtotal: ${data['priced_cost']:.6f} (incomplete)"
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
    legacy_note = (
        "<p>Legacy artifact: cost completeness is unverified.</p>"
        if data["legacy_cost_evidence"]
        else ""
    )
    if data["priced_cost"] is not None:
        cost += f"; Known cost subtotal: ${data['priced_cost']:.6f} (incomplete)"
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
{legacy_note}
<p>Requests: {escaped(_format_number(data["requests"], 0))}; usage: {escaped(_format_number(data["input_tokens"], 0))} input / {escaped(_format_number(data["output_tokens"], 0))} output tokens; estimated cost: {escaped(cost)}</p>
<h2>Pricing provenance</h2>
<ul>{pricing}</ul>
<p class="limitations">Limitations: results reflect this configured workload and provider route; small samples are directional, not a universal model ranking.</p>
</body>
</html>
"""


def render_card_svg(
    payload: Any, *, today: date, record: Mapping[str, Any] | None = None
) -> str:
    """Render a self-contained SVG card of a schema-v1 result.

    `record` is the verifier's report (`verify_record`) for a record of this
    result: it adds the valid-until date, and a stale or superseded record
    turns the band EXPIRED. The card depends only on its inputs and `today`,
    and, like the other reports, recomputes the decision from the evidence.
    """
    result = _validate_result(payload)
    decision = build_decision(result)
    state = decision["state"]
    freshness = record["freshness"] if record is not None else None
    expired = freshness is not None and freshness["state"] != "fresh"
    word = _CARD_BANDS[state][0]
    complete_cost = result.get("cost_confidence") == "complete"
    complete_cost = complete_cost and not legacy_cost_evidence(result)
    rows: list[tuple[str, str, str]] = [
        ("row", "Config", _card_text(result.get("benchmark")))
    ]
    for model in result["models"]:
        rows.append(("rule", "", ""))
        rows.extend(_card_model_rows(model, today, complete_cost))
    rows.append(("rule", "", ""))
    if freshness is not None:
        rows.append(("row", "Valid until", _card_valid_until(freshness)))
    if record is not None and (repository := _card_repository(record)):
        rows.append(("row", "Repository", repository))
    if state == "inconclusive":
        warnings = decision["blocking_warnings"]
        steps = dict.fromkeys(_card_remediation(text) for text in warnings)
        rows.extend(
            ("row", "" if index else "Why:", _card_text(text, 240))
            for index, text in enumerate(warnings)
        )
        rows.extend(
            ("row", "" if index else "To pass:", step)
            for index, step in enumerate(steps)
        )
    elif state == "fail":
        rows.append(("row", "Why:", _card_text(decision["reason"], 240)))
    provenance = result.get("provenance")
    evidence = (
        provenance.get("evidence_sha256") if isinstance(provenance, dict) else None
    )
    footer = [
        f"evidence {evidence[:12]}"
        if isinstance(evidence, str) and re.fullmatch(r"[0-9a-f]{64}", evidence)
        else "evidence: no provenance fingerprint",
        f"llm-preflight verify {_card_text(PurePath(record['record']).name)}"
        if record is not None
        else "Not attested: no preflight record was given",
    ]
    title = f"LLM Preflight: {'EXPIRED (was ' + word + ')' if expired else word}"
    return _card_svg(
        title=f"{title} · {_card_text(result.get('benchmark'))}",
        band=_CARD_BANDS["expired" if expired else state],
        subtitle=f"was {word}" if expired else "",
        checked=f"checked {_card_date(result.get('timestamp'))}",
        rows=rows,
        footer=footer,
    )


def _card_model_rows(
    model: Mapping[str, Any], today: date, complete_cost: bool
) -> list[tuple[str, str, str]]:
    provider = model.get("provider", "openai_compatible")
    summary = model.get("summary", {})
    rows = [
        (
            "row",
            "Model",
            f"{_identifier(model.get('model'))} ({_identifier(provider)})",
        )
    ]
    # Normalised as attest records it: a disagreeing set is shown as a set,
    # and no usable value means no row, never the configured model.
    observed = observed_model([model.get("observed_model")])
    if isinstance(observed, list):
        rows.append(
            (
                "row",
                "Observed",
                f"{_card_text(', '.join(observed), 240)} (responses disagreed)",
            )
        )
    elif observed is not None:
        rows.append(("row", "Observed", _card_text(observed, 240)))
    latency = summary.get("latency_seconds")
    p95 = _number(latency.get("p95")) if isinstance(latency, dict) else None
    cost = _number(summary.get("estimated_cost_usd"))
    requests = summary.get("requests", 0)
    rows.extend(
        [
            ("row", "Probes", _card_probes(model)),
            ("row", "p95 latency", "unknown" if p95 is None else f"{p95:.3f} s"),
            (
                "row",
                "Cost",
                f"{_card_money(cost / requests * 1000)} per 1,000 calls"
                if complete_cost and cost is not None and requests
                else "cost unknown",
            ),
            (
                "row",
                "Retirement",
                _card_retirement(provider, model.get("model"), today),
            ),
        ]
    )
    return rows


def _card_probes(model: Mapping[str, Any]) -> str:
    """Probe counts, never a bare percentage; a profile run counts every profile."""
    profiles = model.get("profiles") or []
    summaries = (
        [profile.get("summary", {}) for profile in profiles]
        if profiles
        else [model.get("summary", {})]
    )
    total = passed = 0
    for summary in summaries:
        requests = summary.get("requests", 0)
        rate = _rate(summary.get("valid_output_rate"))
        if rate is None:
            rate = _rate(summary.get("success_rate"))
        if rate is None:
            return f"{total + requests} probes, outcomes not recorded"
        total += requests
        passed += round(rate * requests)
    if total == 0:
        return "no probes ran"
    if passed == total:
        return "1 probe, passed" if total == 1 else f"{total} probes, all passed"
    return f"{passed} of {total} passed"


def _card_money(value: float) -> str:
    if value == 0:
        return "$0.00"
    if value < 0.0001:
        return "under $0.0001"
    return f"${value:,.2f}" if value >= 1 else f"${value:.4f}"


def _card_retirement(provider: Any, model: Any, today: date) -> str:
    if not isinstance(provider, str) or not isinstance(model, str):
        return "not in the bundled snapshot"
    verdict = retirement_verdict(provider, model, today)
    status = verdict["status"]
    retirement_date = verdict.get("retirement_date")
    if status == "retired":
        return (
            f"retired on {retirement_date}" if retirement_date else "listed as retired"
        )
    if status == "retiring":
        return (
            f"retiring on {retirement_date}"
            if retirement_date
            else "deprecated, date not recorded"
        )
    if status == "stale":
        return f"snapshot row of {verdict['as_of']} is stale"
    if status == "active":
        return "active in the bundled snapshot"
    return "not in the bundled snapshot"


def _card_valid_until(freshness: Mapping[str, Any]) -> str:
    valid_until = freshness["valid_until"]
    if freshness["state"] == "fresh":
        return str(valid_until)
    if freshness["state"] == "superseded":
        return f"{valid_until}, expired: a checked route has since retired"
    return f"{valid_until}, expired: older than {freshness['max_age_days']} days"


def _card_repository(record: Mapping[str, Any]) -> str | None:
    """Where the record was made, worded as `verify` prints it."""
    if record["origin"] == "local":
        return "none — a local record, which the gate never accepts"
    if record["repository"] is None:
        return None
    return _card_text(f"{record['repository']} on {record['server_url']}", 240)


def _card_remediation(warning: str) -> str:
    return next(
        (step for prefix, step in _CARD_REMEDIATIONS if warning.startswith(prefix)),
        _CARD_FALLBACK_REMEDIATION,
    )


def _card_date(value: Any) -> str:
    if not isinstance(value, str):
        return "date unknown"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return "date unknown"


def _card_text(value: Any, limit: int = _CARD_VALUE_CHARS) -> str:
    """Printable text only: XML forbids control characters even when escaped,
    and a bidirectional override could reorder what the card claims. Each one
    shows as its backslash escape, as `verify` and `gate` print it."""
    if not isinstance(value, str) or not value:
        return "unknown"
    text = printable(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _svg_text(
    x: int,
    y: int,
    text: str,
    *,
    size: int,
    mono: bool = False,
    bold: bool = False,
    fill: str | None = None,
    end: bool = False,
) -> str:
    """One text element; only attributes that differ from the card's defaults."""
    attributes = [f'x="{x}"', f'y="{y}"', f'font-size="{size}"']
    if mono:
        attributes.append(f'font-family="{_CARD_MONO}"')
    if bold:
        attributes.append('font-weight="700"')
    if fill:
        attributes.append(f'fill="{fill}"')
    if end:
        attributes.append('text-anchor="end"')
    return f"<text {' '.join(attributes)}>{html.escape(text)}</text>"


def _card_svg(
    *,
    title: str,
    band: tuple[str, str, str],
    subtitle: str,
    checked: str,
    rows: list[tuple[str, str, str]],
    footer: list[str],
) -> str:
    word, fill, ink = band
    right = _CARD_WIDTH - _CARD_MARGIN
    elements = [
        _svg_text(_CARD_MARGIN, 32, "LLM Preflight", size=16, bold=True),
        _svg_text(right, 32, checked, size=13, mono=True, end=True),
        f'<rect x="2" y="46" width="{_CARD_WIDTH - 4}" height="56" fill="{fill}"/>',
        _svg_text(_CARD_MARGIN, 84, word, size=28, bold=True, fill=ink),
    ]
    if subtitle:
        elements.append(_svg_text(right, 82, subtitle, size=14, fill=ink, end=True))
    described = [word + (f" ({subtitle})" if subtitle else ""), checked]
    y = 108
    for kind, label, value in rows:
        if kind == "rule":
            y += 8
            elements.append(
                f'<line x1="{_CARD_MARGIN}" y1="{y}" x2="{right}" y2="{y}" '
                'stroke="#000000" stroke-width="1"/>'
            )
            y += 4
            continue
        lines = textwrap.wrap(value, _CARD_VALUE_CHARS) or [value]
        y += _CARD_LINE
        if label:
            elements.append(_svg_text(_CARD_MARGIN, y, label, size=13, bold=True))
        for index, line in enumerate(lines):
            if index:
                y += _CARD_LINE - 4
            elements.append(_svg_text(_CARD_VALUE_X, y, line, size=14, mono=True))
        sentence = value.rstrip(".")
        described.append(f"{label.rstrip(':')}: {sentence}" if label else sentence)
    y += _CARD_LINE + 6
    elements.append(_svg_text(_CARD_MARGIN, y, CARD_LIMITS, size=13, bold=True))
    for line in footer:
        y += 20
        elements.append(_svg_text(_CARD_MARGIN, y, line, size=12, mono=True))
    described.extend([CARD_LIMITS, *footer])
    height = y + _CARD_MARGIN
    opening = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_CARD_WIDTH}" '
        f'height="{height}" viewBox="0 0 {_CARD_WIDTH} {height}" role="img" '
        f'aria-labelledby="card-title card-desc" font-family="{_CARD_SANS}" '
        'fill="#000000">'
    )
    frame = (
        f'<rect x="1" y="1" width="{_CARD_WIDTH - 2}" height="{height - 2}" '
        'fill="#ffffff" stroke="#000000" stroke-width="2"/>'
    )
    return "\n".join(
        [
            opening,
            f'<title id="card-title">{html.escape(title)}</title>',
            f'<desc id="card-desc">{html.escape("; ".join(described))}</desc>',
            frame,
            *elements,
            "</svg>",
            "",
        ]
    )
