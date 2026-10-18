"""Modern (2026-07-28) local stdio MCP server for LLM Preflight."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import __version__
from .attestation import (
    DEFAULT_MAX_AGE_DAYS,
    gate,
    load_record,
    verify_record,
)
from .cli import (
    _format_audit_source,
    _format_gate,
    _format_verify,
    _verify_exit_code,
    dry_run_plan,
)
from .env import load_env_file, resolve_config_env_file
from .features import (
    apply_model_aliases,
    apply_provider_presets,
    check_budget,
    compare_results,
)
from .redaction import redact_secrets
from .retirements import today_utc
from .runner import (
    canonical_test_selector,
    load_config,
    run_benchmark,
    validate_config_validations,
)
from .source_audit import audit_source

PROTOCOL_VERSION = "2026-07-28"
STANDARD_PROTOCOL_VERSION = "2025-06-18"
SAFE_WORKFLOW_URI = "llm-preflight://guides/safe-workflow"
_MAX_AGE_DAYS = 3650
SAFE_WORKFLOW = """# Safe LLM Preflight workflow

In a repository with no benchmark config, call `audit_source` first. It
reports the literal model IDs in workspace source files with retirement and
pricing verdicts, without a config, credentials, or provider requests. Report
its `decision`: `fail` means a referenced model is retired, `inconclusive`
means one is retiring, its snapshot row is stale, or no file was read, `pass`
means every referenced model the snapshot lists is active, and `none` means
no reference is in the retirement snapshot. It covers only literal model IDs;
a model chosen at run time needs review.

Start a preflight with a benchmark config that reflects the application's
prompt and response contract. The other MCP tools use an existing
workspace-relative config; they do not create or approve one. Use the CLI's
`--contract-check` to prove accepted and rejected response fixtures locally
before a live run.

1. Call `validate_config` after an LLM integration change. This validates any
   local image fixture path, MIME type, size, and content fingerprint without a
   provider call.
2. Call `dry_run_plan` and report the request bound, estimated cost (which is
   intentionally unavailable for image inputs), pricing
   coverage, every non-eligible smoke reason, and the `retirements` decision:
   `fail` means a selected model is retired, `inconclusive` means one is
   retiring or its snapshot row is stale. `ok` does not reflect it.
3. Stop for explicit user approval before any live provider request. Do not
   infer approval from a plan, tool call, or configuration file.
4. Only then call `run_preflight` with `confirm_paid_run: true`; retain the
   returned decision evidence or compare it with `diff_baseline`.

Source audit, mock and dry-run tools never load credentials or contact
providers. A live run does not approve a model, increase a budget, or replace
production approval.
Use `llm-preflight report` on saved JSON for offline HTML or Markdown export;
CI setup and report export are CLI workflows, not MCP tools.

To check proof of preflight, call `verify` on a record CI attested and report
its integrity and freshness separately, or call `gate` with the config, the
downloaded records, the selection CI runs (`prompt`, `tests`,
`environment`, `migration_check`, `smoke`) and the `repository` (OWNER/NAME)
the workspace belongs to; without it or GITHUB_REPOSITORY, or when the two
disagree, the gate cannot decide. Both read only workspace files and never contact a provider. Report the gate's `decision`, `why` and each `next` step.
A gate `pass` is not approval: it shows that a fresh passing record matches
this contract, never that a model, a budget, a merge or paid work is
approved. Never attest a record; that stays a CI step.
"""
_SELECTION_ARGUMENTS = {"prompt", "tests", "environment", "migration_check", "smoke"}


class ProtocolError(ValueError):
    def __init__(self, code: int, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.data = data


def _path(value: str, workspace: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError("paths must be relative to the MCP workspace")
    resolved = (workspace / candidate).resolve()
    if workspace != resolved and workspace not in resolved.parents:
        raise ValueError("path must stay within the MCP workspace")
    return resolved


def _env_path(
    arguments: dict[str, Any],
    config_path: Path,
    workspace: Path,
    config: dict[str, Any],
) -> Path:
    """Return a workspace-contained explicit or config-selected env file."""
    if "env_file" in arguments:
        return _path(arguments["env_file"], workspace)
    env_path, _source = resolve_config_env_file(config_path, config)
    if env_path is None:
        raise ValueError("MCP live runs require an env-file resolution")
    resolved_workspace = workspace.resolve()
    if env_path != resolved_workspace and resolved_workspace not in env_path.parents:
        raise ValueError("path must stay within the MCP workspace")
    return env_path


def _meta(params: dict[str, Any]) -> dict[str, Any]:
    metadata = params.get("_meta")
    if (
        not isinstance(metadata, dict)
        or metadata.get("io.modelcontextprotocol/protocolVersion") != PROTOCOL_VERSION
    ):
        raise ProtocolError(
            -32022,
            "unsupported protocol version",
            {"supported": [PROTOCOL_VERSION]},
        )
    return metadata


def _arguments(name: str, arguments: Any) -> dict[str, Any]:
    allowed = {
        "audit_source": {"path"},
        "validate_config": {"config"},
        "dry_run_plan": {"config"},
        "run_preflight": {"config", "env_file", "confirm_paid_run"},
        "diff_baseline": {"baseline", "current"},
        "verify": {"record", "max_age_days"},
        "gate": {
            "config",
            "records",
            "max_age_days",
            "repository",
            *_SELECTION_ARGUMENTS,
        },
    }
    required: dict[str, set[str]] = {
        "audit_source": set(),
        "validate_config": {"config"},
        "dry_run_plan": {"config"},
        "run_preflight": {"config"},
        "diff_baseline": {"baseline", "current"},
        "verify": {"record"},
        "gate": {"records"},
    }
    if name not in allowed:
        raise ProtocolError(-32602, f"unknown tool: {name}")
    if not isinstance(arguments, dict):
        raise ProtocolError(-32602, "tool arguments must be an object")
    if set(arguments) - allowed[name] or required[name] - set(arguments):
        raise ProtocolError(-32602, "tool arguments do not match the declared schema")
    if any(
        not isinstance(arguments[key], str) or not arguments[key]
        for key in arguments
        if key
        in {
            "path",
            "config",
            "env_file",
            "baseline",
            "current",
            "record",
            "prompt",
            "tests",
            "environment",
            "repository",
        }
    ):
        raise ProtocolError(-32602, "path arguments must be non-empty strings")
    if "records" in arguments and (
        not isinstance(arguments["records"], list)
        or not arguments["records"]
        or not all(isinstance(item, str) and item for item in arguments["records"])
    ):
        raise ProtocolError(-32602, "records must be a non-empty list of paths")
    if "max_age_days" in arguments and (
        not isinstance(arguments["max_age_days"], int)
        or isinstance(arguments["max_age_days"], bool)
        or not 1 <= arguments["max_age_days"] <= _MAX_AGE_DAYS
    ):
        raise ProtocolError(-32602, "max_age_days must be a whole number, 1 to 3650")
    for flag in ("migration_check", "smoke"):
        if flag in arguments and not isinstance(arguments[flag], bool):
            raise ProtocolError(-32602, f"{flag} must be a boolean")
    if "confirm_paid_run" in arguments and not isinstance(
        arguments["confirm_paid_run"], bool
    ):
        raise ProtocolError(-32602, "confirm_paid_run must be a boolean")
    return arguments


@contextmanager
def _temporary_env(path: Path):
    before = dict(os.environ)
    try:
        load_env_file(path)
        yield
    finally:
        os.environ.clear()
        os.environ.update(before)


def _config(path: Path) -> dict[str, Any]:
    config = apply_provider_presets(apply_model_aliases(load_config(path)))
    validate_config_validations(config)
    return config


def _readonly_config(path: Path) -> dict[str, Any]:
    config = _config(path)
    if config.get("discovery"):
        raise ValueError("read-only MCP tools do not resolve provider discovery")
    return config


def _gate_selection(arguments: dict[str, Any]) -> dict[str, Any]:
    """The gate's selection, refusing the combinations a run refuses."""
    if arguments.get("migration_check") and (
        "tests" in arguments or "prompt" in arguments
    ):
        raise ValueError("migration_check cannot be combined with tests or prompt")
    if "tests" in arguments and "prompt" in arguments:
        raise ValueError("tests cannot be combined with prompt")
    return {
        "prompt": arguments.get("prompt"),
        "tests": canonical_test_selector(arguments["tests"])
        if "tests" in arguments
        else None,
        "environment": arguments.get("environment"),
        "migrationCheck": arguments.get("migration_check", False),
        "smoke": arguments.get("smoke", False),
    }


def _tool_result(
    value: dict[str, Any],
    *,
    error: bool = False,
    standard: bool = False,
    summary: str | None = None,
) -> dict[str, Any]:
    safe = redact_secrets(value)
    # A summary leads the text content; the serialized JSON stays for clients
    # that read text instead of structured content.
    content = [{"type": "text", "text": redact_secrets(summary)}] if summary else []
    content.append({"type": "text", "text": json.dumps(safe, sort_keys=True)})
    result: dict[str, Any] = {
        "content": content,
        "structuredContent": safe,
        "isError": error,
    }
    if not standard:
        result["resultType"] = "complete"
    return result


def _output_schema(
    success_properties: dict[str, Any], success_required: list[str], description: str
) -> dict[str, Any]:
    """Describe stable response fields while allowing benchmark extensions."""
    return {
        "type": "object",
        "oneOf": [
            {
                "type": "object",
                "properties": {"error": {"type": "string"}},
                "required": ["error"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "description": description,
                "properties": success_properties,
                "required": success_required,
                "additionalProperties": True,
            },
        ],
    }


def _tools() -> list[dict[str, Any]]:
    path_schema = {"type": "string", "minLength": 1}
    optional_number_schema = {"type": ["number", "null"]}
    strings_schema = {"type": "array", "items": {"type": "string"}}
    retirement_schema = {
        "type": "object",
        "properties": {
            "status": {"enum": ["active", "retiring", "retired", "stale", "unknown"]},
            "decision": {"enum": ["pass", "inconclusive", "fail", "none"]},
            "reason": {"type": "string"},
            "next_step": {"type": "string"},
            "retirement_date": {"type": "string"},
            "replacement": {"type": "string"},
            "replacement_status": {
                "enum": ["active", "retiring", "retired", "unknown"]
            },
            "next_command": {"type": "string"},
            "as_of": {"type": "string"},
            "source_url": {"type": "string"},
        },
        "required": ["status", "decision", "reason", "next_step"],
        "additionalProperties": True,
    }
    reference_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "line": {"type": "integer", "minimum": 1},
            "provider": {"type": ["string", "null"]},
            "model": {"type": "string"},
            "status": {"enum": ["pricing_known", "pricing_unknown"]},
            "confidence": {"enum": ["official_snapshot", "unknown"]},
            "retirement": retirement_schema,
        },
        "required": [
            "path",
            "line",
            "provider",
            "model",
            "status",
            "confidence",
            "retirement",
        ],
        "additionalProperties": True,
    }
    error_or_audit = _output_schema(
        {
            "root": {"type": "string"},
            "network_accessed": {"const": False},
            "files_scanned": {"type": "integer", "minimum": 0},
            "file_selection": {"enum": ["git", "filesystem", "file"]},
            "file_selection_reason": {
                "type": ["string", "null"],
                "description": "Why Git did not select the files; null unless file_selection is filesystem.",
            },
            "files_unreadable": {"type": "integer", "minimum": 0},
            "references": {"type": "array", "items": reference_schema},
            "findings": {"type": "array", "items": reference_schema},
            "ok": {"const": True},
            "decision": {"enum": ["fail", "inconclusive", "pass", "none"]},
            "next_commands": strings_schema,
            "retirement_snapshot": {
                "type": "object",
                "properties": {
                    "providers": strings_schema,
                    "rows": {"type": "integer", "minimum": 0},
                    "oldest_as_of": {"type": "string"},
                    "newest_as_of": {"type": "string"},
                },
                "required": ["providers", "rows", "oldest_as_of", "newest_as_of"],
                "additionalProperties": True,
            },
            "confidence": {"type": "string"},
            "notes": strings_schema,
        },
        [
            "root",
            "network_accessed",
            "files_scanned",
            "file_selection",
            "file_selection_reason",
            "files_unreadable",
            "references",
            "findings",
            "ok",
            "decision",
            "next_commands",
            "retirement_snapshot",
            "confidence",
            "notes",
        ],
        "The CLI --audit-source --json object. decision is the worst retirement decision across references; none means no reference is in the retirement snapshot, and an audit that read no file is inconclusive. ok does not reflect it.",
    )
    error_or_validate = _output_schema(
        {
            "ok": {"const": True},
            "name": {
                "type": ["string", "null", "number", "boolean", "object", "array"],
                "description": "Configured label, preserved as accepted JSON metadata.",
            },
            "models": {"type": "integer", "minimum": 0},
        },
        ["ok", "name", "models"],
        "Validated local configuration summary.",
    )
    error_or_dry_run = _output_schema(
        {
            "ok": {"const": True},
            "models": {"type": "array", "items": {"type": "object"}},
            "requests": {"type": "integer", "minimum": 0},
            "possible_requests": {"type": "integer", "minimum": 0},
            "retry_max_attempts": {"type": "integer", "minimum": 1},
            "estimated_cost_usd": optional_number_schema,
            "maximum_estimated_cost_usd": optional_number_schema,
            "pricing_ledger": {"type": "array", "items": {"type": "object"}},
            "pricing_fingerprint": {"type": "string"},
            "pricing_warnings": {"type": "array", "items": {"type": "object"}},
            "pricing_coverage": {"type": "object"},
            "smoke_eligibility": {"type": "object"},
            "retirements": {"type": "object"},
            "benchmark": {"description": "Configured benchmark name."},
            "tests": {"type": "array", "items": {"type": "string"}},
            "test_breakdown": {"type": "array", "items": {"type": "object"}},
            "configuration_warnings": {"type": "array", "items": {"type": "object"}},
            "presets": {"type": "array", "items": {"type": "string"}},
            "request": {"type": "object"},
            "save_responses": {"description": "Configured response retention."},
            "stop_on": {"description": "Configured stop condition."},
        },
        [
            "ok",
            "models",
            "requests",
            "possible_requests",
            "retry_max_attempts",
            "estimated_cost_usd",
            "maximum_estimated_cost_usd",
            "pricing_ledger",
            "pricing_fingerprint",
            "pricing_warnings",
            "pricing_coverage",
            "smoke_eligibility",
            "retirements",
            "benchmark",
            "tests",
            "test_breakdown",
            "configuration_warnings",
            "presets",
            "request",
            "save_responses",
            "stop_on",
        ],
        "The CLI --dry-run plan with the pricing ledger: resolved models, request bound, cost estimate, pricing evidence, and retirement verdicts.",
    )
    error_or_run = _output_schema(
        {
            "models": {"type": "array", "items": {"type": "object"}},
            "decision": {
                "type": "object",
                "properties": {
                    "schema_version": {"type": "integer"},
                    "state": {"enum": ["pass", "fail", "inconclusive"]},
                    "reason_code": {"type": "string"},
                    "reason": {"type": "string"},
                    "safe_next_command": {"type": "string"},
                    "blocking_warnings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "schema_version",
                    "state",
                    "reason_code",
                    "reason",
                    "safe_next_command",
                    "blocking_warnings",
                ],
                "additionalProperties": True,
            },
        },
        ["decision", "models"],
        "Completed local preflight evidence. A decision of inconclusive is not approval.",
    )
    error_or_diff = _output_schema(
        {
            "ok": {"type": "boolean"},
            "models": {"type": "array", "items": {"type": "object"}},
        },
        ["ok", "models"],
        "Comparison of two saved local result artifacts.",
    )
    nullable_string = {"type": ["string", "null"]}
    nullable_count = {"type": ["integer", "null"], "minimum": 0}
    max_age_schema = {"type": "integer", "minimum": 1, "maximum": _MAX_AGE_DAYS}
    record_results = ["PASSED", "WARNED", "FAILED", None]
    origins = ["github-actions", "local", None]
    route_schema = {
        "type": "object",
        "properties": {
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "observed_model": {
                "type": ["string", "array", "null"],
                "items": {"type": "string"},
                "description": "The model the provider reported answering: one string, the distinct strings when responses disagreed, or null when none was reported.",
            },
        },
        "required": ["provider", "model", "observed_model"],
        "additionalProperties": True,
    }
    retired_route_schema = {
        "type": "object",
        "properties": {
            "provider": nullable_string,
            "model": {"type": "string"},
            "retirement_date": nullable_string,
        },
        "required": ["provider", "model", "retirement_date"],
        "additionalProperties": True,
    }
    selection_schema = {
        "type": "object",
        "properties": {
            "prompt": nullable_string,
            "tests": nullable_string,
            "environment": nullable_string,
            "migrationCheck": {"type": "boolean"},
            "smoke": {"type": "boolean"},
            "repetitions": {"type": ["integer", "null"], "minimum": 1},
        },
        "required": [
            "prompt",
            "tests",
            "environment",
            "migrationCheck",
            "smoke",
            "repetitions",
        ],
        "additionalProperties": False,
    }
    blocked_codes = [
        "foreign_record",
        "selection_changed",
        "contract_changed",
        "routes_changed",
        "prompt_changed",
        "stale",
        "superseded",
        "inconclusive_record",
        "failed_record",
        "inconsistent_record",
        "committed_record",
        "local_record",
    ]
    error_or_verify = _output_schema(
        {
            "record": {"type": "string"},
            "result": {"enum": record_results},
            "integrity": {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "problems": strings_schema,
                    "subjects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "role": {"enum": ["config", "result"]},
                                "state": {"enum": ["matches", "differs", "absent"]},
                            },
                            "required": ["name", "role", "state"],
                            "additionalProperties": True,
                        },
                    },
                },
                "required": ["ok", "problems", "subjects"],
                "additionalProperties": True,
            },
            "routes": {"type": "array", "items": route_schema},
            "freshness": {
                "type": "object",
                "properties": {
                    "state": {"enum": ["fresh", "stale", "superseded", "unknown"]},
                    "checked_at": nullable_string,
                    "age_days": nullable_count,
                    "max_age_days": max_age_schema,
                    "valid_until": nullable_string,
                    "retired_routes": {"type": "array", "items": retired_route_schema},
                },
                "required": [
                    "state",
                    "checked_at",
                    "age_days",
                    "max_age_days",
                    "valid_until",
                    "retired_routes",
                ],
                "additionalProperties": True,
            },
            "retirement_snapshot": {"type": "string"},
            "origin": {"enum": origins},
            "repository": nullable_string,
            "server_url": nullable_string,
            "url": nullable_string,
            "signature": {"type": "string"},
        },
        [
            "record",
            "result",
            "integrity",
            "routes",
            "freshness",
            "retirement_snapshot",
            "origin",
            "repository",
            "server_url",
            "url",
            "signature",
        ],
        "The CLI verify --json report. Integrity and freshness are separate; neither is approval, and the signature is not checked here.",
    )
    error_or_gate = _output_schema(
        {
            "decision": {"enum": ["pass", "blocked", "undecided"]},
            "reason_code": {
                "enum": ["fresh_pass", "no_record", *blocked_codes]
                + ["config_error", "record_error", "repository_unknown"]
            },
            "why": {"type": "string"},
            "next": strings_schema,
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "verdict": {"enum": ["pass", *blocked_codes, "record_error"]},
                        "reason": {"type": "string"},
                        "result": {"enum": record_results},
                        "origin": {"enum": origins},
                        "run_id": nullable_string,
                        "repository": nullable_string,
                        "server_url": nullable_string,
                        "checked_at": nullable_string,
                        "age_days": nullable_count,
                        "valid_until": nullable_string,
                        "tests": {"type": ["object", "null"]},
                        "blocking_warnings": nullable_count,
                        "retired_routes": {
                            "type": "array",
                            "items": retired_route_schema,
                        },
                        "routes": {"type": "array", "items": route_schema},
                        "selection": {**selection_schema, "type": ["object", "null"]},
                        "selection_sha256": nullable_string,
                        "contract_sha256": nullable_string,
                        "routes_sha256": nullable_string,
                    },
                    "required": [
                        "path",
                        "verdict",
                        "reason",
                        "result",
                        "origin",
                        "run_id",
                        "repository",
                        "server_url",
                        "checked_at",
                        "age_days",
                        "valid_until",
                        "tests",
                        "blocking_warnings",
                        "retired_routes",
                        "routes",
                        "selection",
                        "selection_sha256",
                        "contract_sha256",
                        "routes_sha256",
                    ],
                    "additionalProperties": True,
                },
            },
            "config": {"type": "string"},
            "selection": selection_schema,
            "repository": {
                "type": ["string", "null"],
                "description": "The repository whose records count; null when unknown, and the gate is then undecided.",
            },
            "server_url": nullable_string,
            "contract_sha256": nullable_string,
            "routes_sha256": nullable_string,
            "max_age_days": max_age_schema,
            "retirement_snapshot": {"type": "string"},
            "signature": {"type": "string"},
            "network_accessed": {"const": False},
        },
        [
            "decision",
            "reason_code",
            "why",
            "next",
            "records",
            "config",
            "selection",
            "repository",
            "server_url",
            "contract_sha256",
            "routes_sha256",
            "max_age_days",
            "retirement_snapshot",
            "signature",
            "network_accessed",
        ],
        "The CLI gate --json report. A gate pass means a fresh passing CI record matches this contract under this selection; it is not approval of a model, a budget, a merge or paid work.",
    )
    readonly_annotations = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": False,
    }
    return [
        {
            "name": "audit_source",
            "description": (
                "Audit literal model IDs in workspace source files for retirement "
                "and pricing verdicts. Needs no benchmark config; makes no "
                "provider request."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"path": path_schema},
                "additionalProperties": False,
            },
            "outputSchema": error_or_audit,
            "annotations": {**readonly_annotations, "idempotentHint": True},
        },
        {
            "name": "validate_config",
            "description": "Validate a local benchmark config without provider access.",
            "inputSchema": {
                "type": "object",
                "properties": {"config": path_schema},
                "required": ["config"],
                "additionalProperties": False,
            },
            "outputSchema": error_or_validate,
            "annotations": readonly_annotations,
        },
        {
            "name": "dry_run_plan",
            "description": "Return a redacted local run and cost plan without provider access.",
            "inputSchema": {
                "type": "object",
                "properties": {"config": path_schema},
                "required": ["config"],
                "additionalProperties": False,
            },
            "outputSchema": error_or_dry_run,
            "annotations": readonly_annotations,
        },
        {
            "name": "run_preflight",
            "description": "Run a local preflight. Live provider requests require explicit paid-run confirmation.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "config": path_schema,
                    "env_file": path_schema,
                    "confirm_paid_run": {"type": "boolean"},
                },
                "required": ["config"],
                "additionalProperties": False,
            },
            "outputSchema": error_or_run,
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": True,
            },
        },
        {
            "name": "diff_baseline",
            "description": "Compare two saved local benchmark result files without provider access.",
            "inputSchema": {
                "type": "object",
                "properties": {"baseline": path_schema, "current": path_schema},
                "required": ["baseline", "current"],
                "additionalProperties": False,
            },
            "outputSchema": error_or_diff,
            "annotations": readonly_annotations,
        },
        {
            "name": "verify",
            "description": (
                "Report a proof-of-preflight record's integrity and freshness "
                "separately. Reads workspace files only; makes no provider "
                "request. An intact, fresh record is not approval."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"record": path_schema, "max_age_days": max_age_schema},
                "required": ["record"],
                "additionalProperties": False,
            },
            "outputSchema": error_or_verify,
            "annotations": {**readonly_annotations, "idempotentHint": True},
        },
        {
            "name": "gate",
            "description": (
                "Decide offline whether the workspace has a fresh passing CI "
                "record for its contract under the selection CI runs. Reads "
                "workspace files only; makes no provider request. A gate pass "
                "is not approval of a model, a budget, a merge or paid work."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "config": path_schema,
                    "records": {"type": "array", "items": path_schema, "minItems": 1},
                    "max_age_days": max_age_schema,
                    "prompt": path_schema,
                    "tests": path_schema,
                    "environment": path_schema,
                    "migration_check": {"type": "boolean"},
                    "smoke": {"type": "boolean"},
                    "repository": {
                        "type": "string",
                        "minLength": 1,
                        "description": "OWNER/NAME of the workspace repository; default GITHUB_REPOSITORY. Records from any other repository do not count.",
                    },
                },
                "required": ["records"],
                "additionalProperties": False,
            },
            "outputSchema": error_or_gate,
            "annotations": {**readonly_annotations, "idempotentHint": True},
        },
    ]


def _resources() -> list[dict[str, Any]]:
    return [
        {
            "uri": SAFE_WORKFLOW_URI,
            "name": "safe-workflow",
            "title": "Safe LLM Preflight Workflow",
            "description": "No-spend-first workflow and explicit paid-run boundary.",
            "mimeType": "text/markdown",
        }
    ]


def _call(
    name: str,
    arguments: dict[str, Any],
    workspace: Path,
    metadata: dict[str, Any],
    *,
    standard: bool,
) -> dict[str, Any]:
    if name == "audit_source":
        audit = audit_source(
            _path(arguments.get("path", "."), workspace), today=today_utc()
        )
        return _tool_result(
            audit,
            standard=standard,
            summary=_format_audit_source(audit).splitlines()[0],
        )
    if name == "validate_config":
        config = _readonly_config(_path(arguments["config"], workspace))
        return _tool_result(
            {
                "ok": True,
                "name": config.get("name"),
                "models": len(config.get("models", [])),
            },
            standard=standard,
        )
    if name == "dry_run_plan":
        config = _readonly_config(_path(arguments["config"], workspace))
        plan = dry_run_plan(config, today=today_utc(), pricing_evidence=True)
        return _tool_result({"ok": True, **plan}, standard=standard)
    if name == "diff_baseline":
        baseline = json.loads(_path(arguments["baseline"], workspace).read_text())
        current = json.loads(_path(arguments["current"], workspace).read_text())
        return _tool_result(compare_results(baseline, current), standard=standard)
    if name == "verify":
        record_path = _path(arguments["record"], workspace)
        report = verify_record(
            load_record(record_path),
            record_path,
            today_utc(),
            arguments.get("max_age_days", DEFAULT_MAX_AGE_DAYS),
            root=workspace,
        )
        summary = _format_verify(report, _verify_exit_code(report)).splitlines()[0]
        return _tool_result(report, standard=standard, summary=summary)
    if name == "gate":
        selection = _gate_selection(arguments)
        report = gate(
            _path(arguments.get("config", "benchmark.json"), workspace),
            [_path(item, workspace) for item in arguments["records"]],
            today_utc(),
            arguments.get("max_age_days", DEFAULT_MAX_AGE_DAYS),
            selection=selection,
            root=workspace,
            repository=arguments.get("repository"),
            environ=os.environ,
        )
        summary = _format_gate(report).splitlines()[0]
        return _tool_result(report, standard=standard, summary=summary)
    if name == "run_preflight":
        config_path = _path(arguments["config"], workspace)
        config = _config(config_path)
        config["_source_config_path"] = str(config_path)
        live = bool(config.get("discovery")) or any(
            model.get("provider") != "mock" for model in config.get("models", [])
        )
        if live and arguments.get("confirm_paid_run") is not True:
            if standard:
                return _tool_result(
                    {
                        "error": (
                            "live preflight requires explicit user approval; retry "
                            "with confirm_paid_run set to true after approval"
                        )
                    },
                    error=True,
                    standard=True,
                )
            capabilities = metadata.get(
                "io.modelcontextprotocol/clientCapabilities", {}
            )
            if not isinstance(capabilities, dict) or "elicitation" not in capabilities:
                raise ProtocolError(
                    -32021, "missing required client capability: elicitation"
                )
            return {
                "resultType": "input_required",
                "inputRequests": {
                    "paid_run": {
                        "method": "elicitation/create",
                        "params": {
                            "mode": "form",
                            "message": "This preflight can make paid provider requests. Continue?",
                            "requestedSchema": {
                                "type": "object",
                                "properties": {"confirm": {"type": "boolean"}},
                                "required": ["confirm"],
                            },
                        },
                    }
                },
                "requestState": json.dumps(
                    {
                        key: arguments[key]
                        for key in ("config", "env_file")
                        if key in arguments
                    }
                ),
            }
        if live:
            check_budget(config)
            env_path = _env_path(arguments, config_path, workspace, config)
            with _temporary_env(env_path):
                return _tool_result(run_benchmark(config), standard=standard)
        return _tool_result(run_benchmark(config), standard=standard)
    raise ValueError(f"unknown tool: {name}")


def _response(message: dict[str, Any], workspace: Path) -> dict[str, Any] | None:
    if "id" not in message:
        return None
    request_id = message["id"]
    try:
        method = message["method"]
        params = message.get("params", {})
        if not isinstance(params, dict):
            raise TypeError("params must be an object")
        era_metadata = params.get("_meta")
        standard = not (
            isinstance(era_metadata, dict)
            and "io.modelcontextprotocol/protocolVersion" in era_metadata
        )
        metadata = {} if standard or method == "initialize" else _meta(params)
        result: dict[str, Any]
        if method == "initialize":
            result = {
                "protocolVersion": STANDARD_PROTOCOL_VERSION,
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "llm-preflight", "version": __version__},
                "instructions": (
                    "In a repository with no benchmark config, call audit_source "
                    "first and report its decision; `pass` means every "
                    "referenced model the retirement snapshot lists is active. "
                    "It covers only literal model IDs. "
                    "Use validate_config and dry_run_plan before a live run, and "
                    "report the dry_run_plan `retirements` decision: `fail` for a "
                    "retired model, `inconclusive` for a retiring model or a "
                    "stale snapshot row. "
                    "Only call run_preflight for a paid config when the user "
                    "explicitly authorizes it and confirm_paid_run is true. "
                    "verify and gate check proof-of-preflight records offline; "
                    "a gate `pass` is not approval of a model, a budget, a "
                    "merge or paid work."
                ),
            }
        elif method == "ping":
            result = {}
        elif method == "server/discover":
            result = {
                "resultType": "complete",
                "supportedVersions": [PROTOCOL_VERSION],
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "llm-preflight", "version": __version__},
            }
        elif method == "tools/list":
            result = {"tools": _tools()}
            if not standard:
                result["resultType"] = "complete"
        elif method == "resources/list":
            result = {"resources": _resources()}
        elif method == "resources/read":
            if params.get("uri") != SAFE_WORKFLOW_URI:
                raise ProtocolError(-32602, "unknown resource URI")
            result = {
                "contents": [
                    {
                        "uri": SAFE_WORKFLOW_URI,
                        "mimeType": "text/markdown",
                        "text": SAFE_WORKFLOW,
                    }
                ]
            }
        elif method == "tools/call":
            name = str(params.get("name", ""))
            arguments = _arguments(name, params.get("arguments", {}))
            try:
                result = _call(name, arguments, workspace, metadata, standard=standard)
            except ProtocolError:
                raise
            except Exception as exc:  # noqa: BLE001 - MCP tools must return errors
                result = _tool_result(
                    {"error": str(exc)}, error=True, standard=standard
                )
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "method not found"},
            }
        if not standard and method in {
            "server/discover",
            "tools/list",
            "resources/list",
            "resources/read",
        }:
            result.update(resultType="complete", ttlMs=0, cacheScope="private")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except ProtocolError as exc:
        error: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if exc.data is not None:
            error["data"] = exc.data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}
    except Exception as exc:  # noqa: BLE001 - a request must not kill stdio
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32602, "message": redact_secrets(str(exc))},
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Local LLM Preflight MCP server")
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        parser.error("--workspace must be a directory")
    for raw in sys.stdin:
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise TypeError("JSON-RPC message must be an object")
            response = _response(message, workspace)
            if response is not None:
                print(
                    json.dumps(redact_secrets(response), separators=(",", ":")),
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001 - keep serving later requests
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": redact_secrets(str(exc))},
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
