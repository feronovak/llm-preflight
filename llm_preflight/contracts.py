"""No-spend checks and fingerprints for the configured application contract."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .profiles import (
    OUTPUT_VALIDATOR_VERSION,
    evaluate_consumer_response,
    evaluate_response,
)
from .redaction import redact_secrets, without_private_fields

_TOOL_NAME = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
_SCHEMA_TYPES = {"object", "array", "string", "number", "integer", "boolean"}


def validation_evaluator(validation: dict[str, Any]) -> dict[str, Any]:
    """Translate the public validation configuration to the profile evaluator."""
    evaluators: list[dict[str, Any]] = []
    if "json_schema" in validation:
        evaluator = {"type": "json_schema", "schema": validation["json_schema"]}
        if "allow_fenced_json" in validation:
            evaluator["allow_fenced_json"] = validation["allow_fenced_json"]
        evaluators.append(evaluator)
    for key, evaluator_type in (
        ("json_object", "json_object"),
        ("json_array", "json_array"),
    ):
        if validation.get(key):
            evaluator = {"type": evaluator_type}
            if "allow_fenced_json" in validation:
                evaluator["allow_fenced_json"] = validation["allow_fenced_json"]
            evaluators.append(evaluator)
    if "exact_count" in validation:
        evaluator = {"type": "exact_count", "expected": validation["exact_count"]}
        if "allow_fenced_json" in validation:
            evaluator["allow_fenced_json"] = validation["allow_fenced_json"]
        evaluators.append(evaluator)
    if "json_set" in validation:
        evaluator = {"type": "json_set", **validation["json_set"]}
        if "allow_fenced_json" in validation:
            evaluator["allow_fenced_json"] = validation["allow_fenced_json"]
        evaluators.append(evaluator)
    if validation.get("no_markdown"):
        evaluators.append({"type": "no_markdown"})
    if "allowed_values" in validation:
        evaluators.append(
            {"type": "allowed_values", "values": validation["allowed_values"]}
        )
    if "numeric_answer" in validation:
        evaluator = {"type": "numeric_answer", "expected": validation["numeric_answer"]}
        if "numeric_tolerance" in validation:
            evaluator["tolerance"] = validation["numeric_tolerance"]
        evaluators.append(evaluator)
    if "max_chars" in validation:
        evaluators.append({"type": "max_chars", "maximum": validation["max_chars"]})
    if "regex" in validation:
        evaluators.append({"type": "regex", "regex": validation["regex"]})
    if "contains" in validation:
        evaluators.append({"type": "contains", "contains": validation["contains"]})
    if "exact" in validation:
        evaluators.append({"type": "exact", "expected": validation["exact"]})
    if "golden" in validation:
        evaluators.append({"type": "golden", "expected": validation["golden"]})
    if not evaluators:
        return {"type": "nonempty"}
    evaluator = (
        evaluators[0]
        if len(evaluators) == 1
        else {"type": "all", "evaluators": evaluators}
    )
    if "consumer" in validation:
        evaluator["consumer_parser"] = validation["consumer"]
    return evaluator


def validate_contract_config(config: dict[str, Any]) -> None:
    """Validate optional response fixtures and canonical tool definitions."""
    _validate_output_contract(config.get("validation"), "validation")
    _validate_fixtures(config.get("validation_fixtures"), "validation_fixtures")
    if config.get("validation_fixtures") and "validation" not in config:
        raise ValueError(
            "validation_fixtures require a validation at the same level; "
            "place fixtures for a custom prompt inside that prompt"
        )
    for prompt in config.get("prompts", []):
        if isinstance(prompt, dict):
            name = prompt.get("name", "<unnamed>")
            _validate_output_contract(
                prompt.get("validation"), f"prompt {name}.validation"
            )
            _validate_fixtures(
                prompt.get("validation_fixtures"),
                f"prompt {name}.validation_fixtures",
            )
            if prompt.get("validation_fixtures") and "validation" not in prompt:
                raise ValueError(
                    f"prompt {name}.validation_fixtures require prompt {name}.validation"
                )
    _validate_tools(config.get("tools", []))


def contract_fixtures_declared(config: dict[str, Any]) -> bool:
    """Return whether any fixture or tool declaration exists for --contract-check."""
    if config.get("validation_fixtures") or config.get("tools"):
        return True
    return any(
        isinstance(prompt, dict) and prompt.get("validation_fixtures")
        for prompt in config.get("prompts", [])
    )


def _validate_output_contract(validation: Any, location: str) -> None:
    if isinstance(validation, dict) and "json_schema" in validation:
        validate_output_schema(validation["json_schema"], f"{location}.json_schema")


def validate_output_schema(schema: Any, location: str) -> None:
    """Reject output constraints that the portable validator cannot enforce."""
    if not isinstance(schema, dict):
        raise ValueError(f"{location} must be an object")  # noqa: TRY004
    allowed = {
        "type",
        "properties",
        "required",
        "items",
        "minItems",
        "maxItems",
        "enum",
        "additionalProperties",
        "minimum",
        "maximum",
    }
    unknown = sorted(set(schema) - allowed)
    if unknown:
        raise ValueError(
            f"{location}: unsupported output-schema keywords: {', '.join(unknown)}; "
            "use the documented subset or a validator that enforces these constraints"
        )
    schema_type = schema.get("type")
    if not isinstance(schema_type, str) or schema_type not in _SCHEMA_TYPES:
        raise ValueError(
            f"{location}.type must be one of: {', '.join(sorted(_SCHEMA_TYPES))}"
        )
    for key in ("properties", "required", "additionalProperties"):
        if key in schema and schema_type != "object":
            raise ValueError(f"{location}.{key} requires an object schema")
    for key in ("items", "minItems", "maxItems"):
        if key in schema and schema_type != "array":
            raise ValueError(f"{location}.{key} requires an array schema")
    if "required" in schema:
        required = schema["required"]
        if (
            not isinstance(required, list)
            or any(not isinstance(key, str) or not key for key in required)
            or len(set(required)) != len(required)
        ):
            raise ValueError(f"{location}.required must be unique non-empty strings")
    if "properties" in schema:
        if not isinstance(schema["properties"], dict):
            raise ValueError(f"{location}.properties must be an object")
        for key, child in schema["properties"].items():
            if not isinstance(key, str):
                raise ValueError(f"{location}.properties names must be strings")  # noqa: TRY004
            validate_output_schema(child, f"{location}.properties.{key}")
    if "additionalProperties" in schema:
        if not isinstance(schema["additionalProperties"], bool):
            raise ValueError(f"{location}.additionalProperties must be a boolean")
        if schema["additionalProperties"] is False and any(
            key not in schema.get("properties", {})
            for key in schema.get("required", [])
        ):
            raise ValueError(
                f"{location}.required names must exist in properties when additionalProperties is false"
            )
    for key in ("minimum", "maximum"):
        if key not in schema:
            continue
        if schema_type not in {"number", "integer"}:
            raise ValueError(f"{location}.{key} requires a number or integer schema")
        bound = schema[key]
        if (
            isinstance(bound, bool)
            or not isinstance(bound, (int, float))
            or (isinstance(bound, float) and not math.isfinite(bound))
        ):
            raise ValueError(f"{location}.{key} must be a finite number")
    if (
        "minimum" in schema
        and "maximum" in schema
        and schema["minimum"] > schema["maximum"]
    ):
        raise ValueError(f"{location}.minimum must not exceed maximum")
    if "items" in schema:
        validate_output_schema(schema["items"], f"{location}.items")
    for key in ("minItems", "maxItems"):
        if key in schema and (
            not isinstance(schema[key], int)
            or isinstance(schema[key], bool)
            or schema[key] < 0
        ):
            raise ValueError(f"{location}.{key} must be a non-negative integer")
    if schema.get("minItems", 0) > schema.get("maxItems", float("inf")):
        raise ValueError(f"{location}.minItems must not exceed maxItems")
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values:
            raise ValueError(f"{location}.enum must be a non-empty list")
        constraints = {key: value for key, value in schema.items() if key != "enum"}
        for value in values:
            try:
                response = json.dumps(value, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{location}.enum must contain finite JSON values"
                ) from exc
            if not evaluate_response(
                response, {"type": "json_schema", "schema": constraints}
            )["valid"]:
                raise ValueError(f"{location}.enum values must satisfy the schema")


def _validate_fixtures(fixtures: Any, location: str) -> None:
    if fixtures is None:
        return
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError(f"{location} must be a non-empty list")
    outcomes: set[str] = set()
    names: set[str] = set()
    for index, fixture in enumerate(fixtures):
        item_location = f"{location}[{index}]"
        if not isinstance(fixture, dict) or set(fixture) != {
            "name",
            "response",
            "expect",
        }:
            raise ValueError(f"{item_location} requires name, response, and expect")
        if not isinstance(fixture["name"], str) or not fixture["name"].strip():
            raise ValueError(f"{item_location}.name must be a non-empty string")
        if fixture["name"] in names:
            raise ValueError(f"{location} fixture names must be unique")
        names.add(fixture["name"])
        if not isinstance(fixture["response"], str):
            raise ValueError(  # noqa: TRY004 - configuration errors share one public type
                f"{item_location}.response must be a string"
            )
        if fixture["expect"] not in {"pass", "fail"}:
            raise ValueError(f"{item_location}.expect must be pass or fail")
        outcomes.add(fixture["expect"])
    if outcomes != {"pass", "fail"}:
        raise ValueError(f"{location} requires at least one pass and fail fixture")


def _validate_tools(tools: Any) -> None:
    if not isinstance(tools, list):
        raise ValueError("tools must be a list")  # noqa: TRY004 - public config error
    names: set[str] = set()
    for index, tool in enumerate(tools):
        location = f"tools[{index}]"
        if not isinstance(tool, dict) or set(tool) != {
            "name",
            "description",
            "parameters",
        }:
            raise ValueError(f"{location} requires name, description, and parameters")
        name = tool["name"]
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 64
            or name[0] not in _TOOL_NAME[:52]
            or any(character not in _TOOL_NAME for character in name)
        ):
            raise ValueError(
                f"{location}.name must be a 1-64 character tool identifier"
            )
        if name in names:
            raise ValueError("tool names must be unique")
        names.add(name)
        if not isinstance(tool["description"], str) or not tool["description"].strip():
            raise ValueError(f"{location}.description must be a non-empty string")
        _validate_tool_schema(tool["parameters"], f"{location}.parameters", root=True)


def _validate_tool_schema(schema: Any, location: str, *, root: bool = False) -> None:
    if not isinstance(schema, dict):
        raise ValueError(  # noqa: TRY004 - public config error
            f"{location} must be an object"
        )
    if schema.get("type") not in _SCHEMA_TYPES:
        raise ValueError(f"{location}.type must be a supported JSON Schema type")
    if root and schema["type"] != "object":
        raise ValueError(f"{location}.type must be object")
    allowed = {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "additionalProperties",
    }
    unknown = sorted(set(schema) - allowed)
    if unknown:
        raise ValueError(
            f"{location} has unsupported JSON Schema keys: {', '.join(unknown)}"
        )
    if "properties" in schema:
        if schema["type"] != "object" or not isinstance(schema["properties"], dict):
            raise ValueError(f"{location}.properties requires an object schema")
        for key, child in schema["properties"].items():
            if not isinstance(key, str) or not key:
                raise ValueError(
                    f"{location}.properties keys must be non-empty strings"
                )
            _validate_tool_schema(child, f"{location}.properties.{key}")
    if "required" in schema:
        if (
            schema["type"] != "object"
            or not isinstance(schema["required"], list)
            or any(not isinstance(key, str) or not key for key in schema["required"])
            or len(set(schema["required"])) != len(schema["required"])
        ):
            raise ValueError(
                f"{location}.required must be unique non-empty property names"
            )
        properties = schema.get("properties", {})
        if any(key not in properties for key in schema["required"]):
            raise ValueError(f"{location}.required names must exist in properties")
    if "items" in schema:
        if schema["type"] != "array":
            raise ValueError(f"{location}.items requires an array schema")
        _validate_tool_schema(schema["items"], f"{location}.items")
    if "enum" in schema and (
        not isinstance(schema["enum"], list) or not schema["enum"]
    ):
        raise ValueError(f"{location}.enum must be a non-empty list")
    if "additionalProperties" in schema and not isinstance(
        schema["additionalProperties"], bool
    ):
        raise ValueError(f"{location}.additionalProperties must be a boolean")


def check_contract(config: dict[str, Any]) -> dict[str, Any]:
    """Run configured validation fixtures and tool linting without provider access."""
    validate_contract_config(config)
    evaluator = validation_evaluator(config.get("validation", {}))
    fixture_results = [
        _check_fixture(fixture, evaluator)
        for fixture in config.get("validation_fixtures", [])
    ]
    prompt_results = []
    for prompt in config.get("prompts", []):
        if not isinstance(prompt, dict) or not prompt.get("validation_fixtures"):
            continue
        prompt_evaluator = validation_evaluator(prompt["validation"])
        prompt_results.append(
            {
                "prompt": prompt["name"],
                "fixtures": [
                    _check_fixture(fixture, prompt_evaluator)
                    for fixture in prompt["validation_fixtures"]
                ],
            }
        )
    tool_results = [
        {"name": tool["name"], "ok": True} for tool in config.get("tools", [])
    ]
    all_fixtures = fixture_results + [
        item for entry in prompt_results for item in entry["fixtures"]
    ]
    return {
        "ok": all(item.get("actual") == item.get("expected") for item in all_fixtures),
        "fixtures": fixture_results,
        "prompt_fixtures": prompt_results,
        "tools": tool_results,
    }


def _check_fixture(
    fixture: dict[str, str], evaluator: dict[str, Any]
) -> dict[str, str]:
    evaluation = evaluate_response(fixture["response"], evaluator)
    valid = evaluation["valid"]
    consumer_evaluation = evaluate_consumer_response(fixture["response"], evaluator)
    if consumer_evaluation is not None and not consumer_evaluation["valid"]:
        valid = False
    actual = "pass" if valid else "fail"
    result = {"name": fixture["name"], "expected": fixture["expect"], "actual": actual}
    if actual != fixture["expect"]:
        result["error"] = "fixture expectation did not match validator result"
    return result


def provenance(
    config: dict[str, Any], models: list[dict[str, Any]], pricing_fingerprint: str
) -> dict[str, Any]:
    """Return non-secret, stable evidence fingerprints for a completed run."""
    prompts = _prompt_fingerprints(config)
    clean_config = without_private_fields(config)
    contract = {
        "validator_version": OUTPUT_VALIDATOR_VERSION,
        "validation": config.get("validation", {}),
        "validation_fixtures": config.get("validation_fixtures", []),
        "prompts": [
            {
                key: prompt[key]
                for key in ("name", "prompt", "validation", "validation_fixtures")
                if key in prompt
            }
            for prompt in config.get("prompts", [])
            if isinstance(prompt, dict)
        ],
        "tools": config.get("tools", []),
        "profiles": config.get("profiles", []),
    }
    routes = [
        {
            "provider": model.get("provider", "openai_compatible"),
            "model": model.get("model"),
            "base_url": _safe_base_url(model.get("base_url")),
            "api_version": model.get("api_version"),
            "max_tokens_parameter": model.get("max_tokens_parameter"),
            "supports_temperature": model.get("supports_temperature"),
            "header_names": sorted(str(key) for key in (model.get("headers") or {})),
        }
        for model in models
    ]
    limits = {
        "max_requests": config.get("max_requests"),
        "max_estimated_cost_usd": config.get("max_estimated_cost_usd"),
    }
    result = {
        "schema_version": 1,
        "validator_version": OUTPUT_VALIDATOR_VERSION,
        "config_sha256": _fingerprint(redact_secrets(clean_config)),
        "contract_sha256": _fingerprint(redact_secrets(contract)),
        "routes_sha256": _fingerprint(redact_secrets(routes)),
        "pricing_sha256": pricing_fingerprint,
        "prompts": prompts,
        "limits": limits,
    }
    result["evidence_sha256"] = _fingerprint(result)
    return result


def _prompt_fingerprints(config: dict[str, Any]) -> list[dict[str, Any]]:
    prompts = []
    if "prompt" in config:
        prompts.append((config.get("prompt_name") or "config-prompt", config["prompt"]))
    prompts.extend(
        (prompt["name"], prompt["prompt"])
        for prompt in config.get("prompts", [])
        if isinstance(prompt, dict)
        and isinstance(prompt.get("name"), str)
        and isinstance(prompt.get("prompt"), str)
    )
    return [
        {
            "name": name,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "chars": len(text),
        }
        for name, text in prompts
    ]


def _safe_base_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()
