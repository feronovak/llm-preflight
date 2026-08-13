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
from .catalog import resolve_models
from .env import load_env_file
from .features import (
    apply_model_aliases,
    apply_provider_presets,
    compare_results,
    estimate_budget,
)
from .pricing import pricing_coverage_report, pricing_freshness_report
from .redaction import redact_secrets
from .runner import load_config, run_benchmark, validate_config_validations

PROTOCOL_VERSION = "2026-07-28"
STANDARD_PROTOCOL_VERSION = "2025-06-18"


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
        "validate_config": {"config"},
        "dry_run_plan": {"config"},
        "run_preflight": {"config", "env_file", "confirm_paid_run"},
        "diff_baseline": {"baseline", "current"},
    }
    required = {
        "validate_config": {"config"},
        "dry_run_plan": {"config"},
        "run_preflight": {"config"},
        "diff_baseline": {"baseline", "current"},
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
        if key in {"config", "env_file", "baseline", "current"}
    ):
        raise ProtocolError(-32602, "path arguments must be non-empty strings")
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


def _tool_result(
    value: dict[str, Any], *, error: bool = False, standard: bool = False
) -> dict[str, Any]:
    safe = redact_secrets(value)
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(safe, sort_keys=True)}],
        "structuredContent": safe,
        "isError": error,
    }
    if not standard:
        result["resultType"] = "complete"
    return result


def _tools() -> list[dict[str, Any]]:
    path_schema = {"type": "string", "minLength": 1}
    return [
        {
            "name": "validate_config",
            "description": "Validate a local benchmark config without provider access.",
            "inputSchema": {
                "type": "object",
                "properties": {"config": path_schema},
                "required": ["config"],
                "additionalProperties": False,
            },
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
        },
    ]


def _call(
    name: str,
    arguments: dict[str, Any],
    workspace: Path,
    metadata: dict[str, Any],
    *,
    standard: bool,
) -> dict[str, Any]:
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
        models = resolve_models(config)
        budget = estimate_budget(config, models)
        return _tool_result(
            {
                "ok": True,
                "models": models,
                **budget,
                "pricing_warnings": pricing_freshness_report(
                    models,
                    enforce_override_freshness=bool(
                        config.get("require_current_pricing")
                    ),
                )["warnings"],
                "pricing_coverage": pricing_coverage_report(
                    models,
                    require_current_pricing=bool(config.get("require_current_pricing")),
                ),
            },
            standard=standard,
        )
    if name == "diff_baseline":
        baseline = json.loads(_path(arguments["baseline"], workspace).read_text())
        current = json.loads(_path(arguments["current"], workspace).read_text())
        return _tool_result(compare_results(baseline, current), standard=standard)
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
                "requestState": json.dumps({"config": arguments["config"]}),
            }
        if live:
            env_path = (
                _path(arguments["env_file"], workspace)
                if arguments.get("env_file")
                else config_path.parent / ".env.production"
            )
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
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "llm-preflight", "version": __version__},
                "instructions": (
                    "Use validate_config and dry_run_plan before a live run. "
                    "Only call run_preflight for a paid config when the user "
                    "explicitly authorizes it and confirm_paid_run is true."
                ),
            }
        elif method == "ping":
            result = {}
        elif method == "server/discover":
            result = {
                "resultType": "complete",
                "supportedVersions": [PROTOCOL_VERSION],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "llm-preflight", "version": __version__},
            }
        elif method == "tools/list":
            result = {"tools": _tools()}
            if not standard:
                result["resultType"] = "complete"
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
