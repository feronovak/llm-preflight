"""Stable, machine-readable benchmark decisions for automation clients."""

from __future__ import annotations

import re
import shlex
from typing import Any

SCHEMA_VERSION = 1
SAFE_NEXT_COMMAND = "llm-preflight CONFIG --doctor --json"
_SAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9._:/@+\-]")
_MAX_IDENTIFIER_LENGTH = 120


def build_decision(result: dict[str, Any]) -> dict[str, Any]:
    """Return the v1 decision contract without changing the enclosing schema."""
    warnings = _blocking_warnings(result)
    failure = _failure_kind(result)
    if failure is not None:
        is_contract_failure = failure == "contract_failure"
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "fail",
            "reason_code": failure,
            "reason": (
                "One or more requested models failed the configured output contract."
                if is_contract_failure
                else "One or more requested models failed an API request."
            ),
            "safe_next_command": _safe_next_command(
                result, contract_failure=is_contract_failure
            ),
            "blocking_warnings": warnings,
        }
    if warnings:
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "inconclusive",
            "reason_code": "degraded_evidence",
            "reason": "Evidence is degraded; resolve blocking warnings before using this result.",
            "safe_next_command": _safe_next_command(result),
            "blocking_warnings": warnings,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "pass",
        "reason_code": "benchmark_passed",
        "reason": "All requested models passed with complete, uninterrupted evidence.",
        "safe_next_command": _safe_next_command(result),
        "blocking_warnings": [],
    }


def _blocking_warnings(result: dict[str, Any]) -> list[str]:
    warnings = []
    coverage = result.get("pricing_coverage", {})
    billable = coverage.get("summary", {}).get("billable")
    if billable == 0 and result.get("models"):
        warnings.append("Mock-only runs do not provide live-provider evidence.")
    for entry in coverage.get("models", []):
        if entry.get("pricing_exempt") or entry.get("status") not in {
            "unknown",
            "stale",
        }:
            continue
        warnings.append(
            f"Pricing is {entry['status']} for {_identifier(entry['provider'])}:"
            f"{_identifier(entry['model'])}; "
            "resolve its pricing before using this result."
        )
    confidence = result.get("cost_confidence")
    if billable != 0 and confidence != "complete":
        warnings.append(
            f"Cost confidence is {confidence or 'unknown'}; complete cost evidence is required."
        )
    return warnings


def _safe_next_command(
    result: dict[str, Any], *, contract_failure: bool = False
) -> str:
    path = result.get("source_config_path")
    suffix = "--dry-run --json" if contract_failure else "--doctor --json"
    if not isinstance(path, str) or not path:
        return (
            SAFE_NEXT_COMMAND
            if not contract_failure
            else "llm-preflight CONFIG --dry-run --json"
        )
    return f"llm-preflight {shlex.quote(path)} {suffix}"


def _identifier(value: Any) -> str:
    return _SAFE_IDENTIFIER.sub("?", str(value))[:_MAX_IDENTIFIER_LENGTH]


def _failure_kind(result: dict[str, Any]) -> str | None:
    contract_failure = False
    for model in result.get("models", []):
        for summary in _summaries(model):
            if summary.get("requests", 0) == 0 or summary.get("failed", 0):
                return "api_failure"
            if summary.get("valid_output_rate", 1) < 1:
                contract_failure = True
        if not model.get("profiles") and any(
            sample.get("valid_output") is False for sample in model.get("samples", [])
        ):
            contract_failure = True
    return "contract_failure" if contract_failure else None


def _summaries(model: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = model.get("profiles") or []
    if profiles:
        return [profile.get("summary", {}) for profile in profiles]
    return [model.get("summary", {})]
