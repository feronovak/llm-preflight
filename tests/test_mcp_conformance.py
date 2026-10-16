"""Tool schemas match what official MCP SDK clients accept and what tools return.

The validator below implements only the JSON Schema keywords `mcp.py` uses, so
the suite stays dependency-free; a schema keyword outside that set fails the
coverage test instead of being silently skipped.
"""

import json
from typing import Any

import pytest

from llm_preflight import mcp

SUPPORTED_KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "oneOf",
    "const",
    "enum",
    "minimum",
    "minLength",
    "description",
}
_TYPES = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    return left == right


def schema_errors(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Return every violation of the supported keyword subset."""
    errors: list[str] = []
    if "type" in schema:
        allowed = (
            schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        )
        if not any(_TYPES[name](instance) for name in allowed):
            return [f"{path}: expected type {schema['type']}"]
    if "const" in schema and not _same(instance, schema["const"]):
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and not any(_same(instance, item) for item in schema["enum"]):
        errors.append(f"{path}: not one of {schema['enum']!r}")
    if (
        "minimum" in schema
        and _TYPES["number"](instance)
        and instance < schema["minimum"]
    ):
        errors.append(f"{path}: below minimum {schema['minimum']}")
    if (
        "minLength" in schema
        and isinstance(instance, str)
        and len(instance) < schema["minLength"]
    ):
        errors.append(f"{path}: shorter than {schema['minLength']}")
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required {key!r}")
        for key, value in instance.items():
            if key in properties:
                errors.extend(schema_errors(value, properties[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {key!r}")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(
                    schema_errors(
                        value, schema["additionalProperties"], f"{path}.{key}"
                    )
                )
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors.extend(schema_errors(item, schema["items"], f"{path}[{index}]"))
    if "oneOf" in schema:
        branches = [schema_errors(instance, branch, path) for branch in schema["oneOf"]]
        matches = sum(not branch for branch in branches)
        if matches != 1:
            errors.append(f"{path}: matches {matches} oneOf branches: {branches}")
    return errors


def schema_keywords(schema: dict[str, Any]) -> set[str]:
    """Every keyword used anywhere in a schema; property names are not keywords."""
    keywords = set(schema)
    for value in schema.get("properties", {}).values():
        keywords |= schema_keywords(value)
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            keywords |= schema_keywords(schema[key])
    for branch in schema.get("oneOf", []):
        keywords |= schema_keywords(branch)
    return keywords


def _tools() -> dict[str, dict[str, Any]]:
    return {tool["name"]: tool for tool in mcp._tools()}


def _call(workspace, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = mcp._response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        workspace,
    )
    return response["result"]


_BAD_INSTANCES = [
    ("type", {"type": "object"}, []),
    ("type", {"type": ["number", "null"]}, "1"),
    ("type", {"type": "integer"}, True),
    ("type", {"type": "integer"}, 1.5),
    ("properties", {"properties": {"a": {"type": "string"}}}, {"a": 1}),
    ("required", {"type": "object", "required": ["a"]}, {}),
    ("additionalProperties", {"additionalProperties": False}, {"b": 1}),
    (
        "additionalProperties",
        {"additionalProperties": {"type": "string"}},
        {"b": 1},
    ),
    ("items", {"type": "array", "items": {"type": "string"}}, [{"a": 1}]),
    ("oneOf", {"oneOf": [{"type": "string"}, {"type": "integer"}]}, None),
    ("oneOf", {"oneOf": [{"type": "number"}, {"type": "integer"}]}, 1),
    ("const", {"const": True}, 1),
    ("const", {"const": True}, False),
    ("enum", {"enum": ["pass", "fail"]}, "maybe"),
    ("minimum", {"type": "integer", "minimum": 1}, 0),
    ("minLength", {"type": "string", "minLength": 1}, ""),
]


@pytest.mark.parametrize(("keyword", "schema", "instance"), _BAD_INSTANCES)
def test_validator_rejects_known_bad_instances(keyword, schema, instance):
    assert keyword in SUPPORTED_KEYWORDS
    assert schema_errors(instance, schema)


def test_validator_rejection_cases_cover_every_constraining_keyword():
    covered = {keyword for keyword, _schema, _instance in _BAD_INSTANCES}

    assert covered == SUPPORTED_KEYWORDS - {"description"}


def test_validator_accepts_instances_that_satisfy_the_schema():
    schema = {
        "type": "object",
        "properties": {
            "ok": {"const": True},
            "state": {"enum": ["pass", "fail"]},
            "count": {"type": "integer", "minimum": 0},
            "cost": {"type": ["number", "null"]},
            "path": {"type": "string", "minLength": 1},
            "rows": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["ok"],
        "additionalProperties": False,
        "description": "annotation only",
    }

    assert not schema_errors(
        {
            "ok": True,
            "state": "fail",
            "count": 0,
            "cost": None,
            "path": "a",
            "rows": [],
        },
        schema,
    )


def test_every_tool_schema_is_a_top_level_object_using_only_supported_keywords():
    for name, tool in _tools().items():
        for key in ("inputSchema", "outputSchema"):
            schema = tool[key]
            assert schema["type"] == "object", (name, key)
            assert schema_keywords(schema) <= SUPPORTED_KEYWORDS, (name, key)


def test_every_tool_result_validates_against_its_output_schema(tmp_path):
    (tmp_path / "mock.json").write_text(
        json.dumps(
            {
                "name": "mock",
                "prompt": "Reply with ok.",
                "validation": {"exact": "ok"},
                "models": [{"provider": "mock", "model": "local", "response": "ok"}],
            }
        )
    )
    (tmp_path / "retired.json").write_text(
        json.dumps(
            {
                "prompt": "Reply with ok.",
                "models": [
                    {"provider": "anthropic", "model": "claude-3-haiku-20240307"}
                ],
            }
        )
    )
    (tmp_path / "presets.json").write_text(
        json.dumps(
            {
                "prompt": "Reply with ok.",
                "presets": ["json"],
                "models": [{"provider": "anthropic", "model": "claude-test"}],
            }
        )
    )
    (tmp_path / "discovery.json").write_text(
        json.dumps(
            {"prompt": "Reply with ok.", "discovery": [{"provider": "openrouter"}]}
        )
    )
    (tmp_path / "live.json").write_text(
        json.dumps(
            {"prompt": "ok", "models": [{"provider": "openai", "model": "gpt-test"}]}
        )
    )
    run = _call(tmp_path, "run_preflight", {"config": "mock.json"})
    (tmp_path / "baseline.json").write_text(json.dumps(run["structuredContent"]))
    (tmp_path / "unknown").mkdir()
    (tmp_path / "unknown" / "app.py").write_text('model = "gpt-unlisted"\n')
    (tmp_path / "empty").mkdir()
    calls = {
        "audit_source": [
            ({}, False),
            ({"path": "retired.json"}, False),
            ({"path": "unknown"}, False),
            ({"path": "empty"}, False),
            ({"path": "missing"}, True),
            ({"path": ".."}, True),
        ],
        "validate_config": [
            ({"config": "mock.json"}, False),
            ({"config": "missing.json"}, True),
        ],
        "dry_run_plan": [
            ({"config": "mock.json"}, False),
            ({"config": "retired.json"}, False),
            ({"config": "presets.json"}, False),
            ({"config": "discovery.json"}, True),
        ],
        "run_preflight": [
            ({"config": "mock.json"}, False),
            ({"config": "live.json"}, True),
        ],
        "diff_baseline": [
            ({"baseline": "baseline.json", "current": "baseline.json"}, False),
            ({"baseline": "baseline.json", "current": "missing.json"}, True),
        ],
    }
    tools = _tools()

    assert set(calls) == set(tools)
    for name, cases in calls.items():
        for arguments, is_error in cases:
            result = _call(tmp_path, name, arguments)
            assert result["isError"] is is_error, (name, arguments, result)
            errors = schema_errors(
                result["structuredContent"], tools[name]["outputSchema"]
            )
            assert not errors, (name, arguments, errors)
    retired = _call(tmp_path, "dry_run_plan", {"config": "retired.json"})
    assert retired["structuredContent"]["retirements"]["decision"] == "fail"
    assert retired["structuredContent"]["pricing_warnings"]
    presets = _call(tmp_path, "dry_run_plan", {"config": "presets.json"})
    assert presets["structuredContent"]["configuration_warnings"]
    audits = {
        path: _call(tmp_path, "audit_source", {"path": path})["structuredContent"]
        for path in (".", "retired.json", "unknown", "empty")
    }
    assert audits["."]["file_selection_reason"] is not None
    assert audits["."]["decision"] == "fail"
    assert audits["retired.json"]["file_selection"] == "file"
    assert audits["retired.json"]["file_selection_reason"] is None
    assert audits["unknown"]["decision"] == "none"
    assert audits["empty"]["decision"] == "inconclusive"
