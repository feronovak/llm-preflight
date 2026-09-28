import json

import pytest

from llm_preflight.contracts import check_contract, provenance
from llm_preflight.features import compare_results
from llm_preflight.profiles import evaluate_response
from llm_preflight.runner import validate_config_validations


def routing_schema():
    return {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["queue", "confidence"],
            "additionalProperties": False,
            "properties": {
                "queue": {"type": "string", "enum": ["billing"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    }


@pytest.mark.parametrize(
    ("expected", "output", "valid"),
    [
        ({"enabled": True}, {"enabled": 1}, False),
        ({"enabled": False}, {"enabled": 0}, False),
        ([True], [1], False),
        ([False], [0.0], False),
        ({"nested": [{"enabled": True}]}, {"nested": [{"enabled": 1}]}, False),
        ({"value": 1}, {"value": True}, False),
        ([0], [False], False),
        ({"enabled": True}, {"enabled": True}, True),
        ([False], [False], True),
        ({"count": 1}, {"count": 1.0}, True),
        ([0], [-0.0], True),
        ({"a": 1, "b": 2}, {"b": 2.0, "a": 1.0}, True),
        ([1, 2], [2, 1], False),
        ([1], [1, 2], False),
        ({"a": 1}, {"a": 1, "b": 2}, False),
        ({"value": None}, {"value": 0}, False),
        ({"value": None}, {"value": None}, True),
        (["1"], [1], False),
    ],
)
def test_enum_uses_json_value_equality_recursively(expected, output, valid):
    schema = {
        "type": "object" if isinstance(expected, dict) else "array",
        "enum": [expected],
    }
    config = {"validation": {"json_schema": schema}}
    validate_config_validations(config)
    assert (
        evaluate_response(
            json.dumps(output), {"type": "json_schema", "schema": schema}
        )["valid"]
        is valid
    )
    config["validation_fixtures"] = [
        {"name": "enum member", "response": json.dumps(expected), "expect": "pass"},
        {
            "name": "candidate",
            "response": json.dumps(output),
            "expect": "pass" if valid else "fail",
        },
        {"name": "wrong type", "response": '"unexpected"', "expect": "fail"},
    ]
    assert check_contract(config)["ok"]


@pytest.mark.parametrize(
    ("output", "valid", "rule"),
    [
        ([{"queue": "billing", "confidence": 0}], True, None),
        ([{"queue": "billing", "confidence": 1}], True, None),
        ([{"queue": "billing", "confidence": 0.95}], True, None),
        ([{"queue": "billing", "confidence": 2}], False, "maximum"),
        ([{"queue": "billing", "confidence": -0.1}], False, "minimum"),
        (
            [{"queue": "billing", "confidence": 0.95, "extra": "private value"}],
            False,
            "additionalProperties",
        ),
        ([{"queue": "billing", "confidence": float("nan")}], False, "invalid JSON"),
        ([{"queue": "billing", "confidence": float("inf")}], False, "invalid JSON"),
    ],
)
def test_nested_output_rules_enforce_the_consumer_contract(output, valid, rule):
    result = evaluate_response(
        json.dumps(output), {"type": "json_schema", "schema": routing_schema()}
    )
    assert result["valid"] is valid
    if rule:
        assert rule in result["error"]
        if rule != "invalid JSON":
            assert "value[0]" in result["error"]
        assert "private value" not in result["error"]


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize(
    ("parsing_policy", "wrap"),
    [
        ("raw_json", lambda value: value),
        ("single_fenced_block", lambda value: f"```json\n{value}\n```"),
        ("first_fenced_block", lambda value: f"```json\n{value}\n```"),
        ("prose_tolerant", lambda value: f"Result: {value}"),
        ("first_json_value", lambda value: f"Result: {value}"),
    ],
)
def test_non_json_numeric_constants_cannot_pass_structured_output(
    constant, parsing_policy, wrap
):
    response = wrap('{"queue":"billing","extra":' + constant + "}")
    evaluator = {
        "type": "json_schema",
        "schema": {"type": "object", "required": ["queue"]},
        "parsing_policy": parsing_policy,
    }
    result = evaluate_response(response, evaluator)
    assert result["valid"] is False
    assert "invalid JSON" in result["error"]
    assert constant not in result["error"]


@pytest.mark.parametrize(
    "number", ["1e999", "-1e999", "1e-9999999999999999999999999999"]
)
@pytest.mark.parametrize(
    ("parsing_policy", "wrap"),
    [
        ("raw_json", lambda value: value),
        ("single_fenced_block", lambda value: f"```json\n{value}\n```"),
        ("first_fenced_block", lambda value: f"```json\n{value}\n```"),
        ("prose_tolerant", lambda value: f"Result: {value}"),
        ("first_json_value", lambda value: f"Result: {value}"),
    ],
)
def test_overflowing_json_number_cannot_pass_structured_output(
    number, parsing_policy, wrap
):
    response = wrap('{"queue":"billing","extra":' + number + "}")
    result = evaluate_response(
        response,
        {
            "type": "json_schema",
            "schema": {"type": "object", "required": ["queue"]},
            "parsing_policy": parsing_policy,
        },
    )
    assert result["valid"] is False
    assert "invalid JSON" in result["error"]
    assert number not in result["error"]


@pytest.mark.parametrize(
    ("response", "enum"),
    [("1e-999", [0]), ("0.9999999999999999999", [1])],
)
def test_rounded_json_number_cannot_impersonate_enum_member(response, enum):
    result = evaluate_response(
        response,
        {"type": "json_schema", "schema": {"type": "number", "enum": enum}},
    )
    assert result["valid"] is False
    assert "invalid JSON" in result["error"]


@pytest.mark.parametrize(
    ("parsing_policy", "wrap"),
    [
        ("raw_json", lambda value: value),
        ("single_fenced_block", lambda value: f"```json\n{value}\n```"),
        ("first_fenced_block", lambda value: f"```json\n{value}\n```"),
        ("prose_tolerant", lambda value: f"Result: {value}"),
        ("first_json_value", lambda value: f"Result: {value}"),
    ],
)
def test_json_integer_over_decoder_limit_returns_failure(parsing_policy, wrap):
    response = wrap('{"queue":"billing","extra":' + "9" * 5000 + "}")
    result = evaluate_response(
        response,
        {
            "type": "json_schema",
            "schema": {"type": "object", "required": ["queue"]},
            "parsing_policy": parsing_policy,
        },
    )
    assert result["valid"] is False
    assert "invalid JSON" in result["error"]


@pytest.mark.parametrize("parsing_policy", ["prose_tolerant", "first_json_value"])
@pytest.mark.parametrize("invalid", ["NaN", "1e999"])
def test_prose_parser_does_not_salvage_nested_value_from_invalid_outer_json(
    parsing_policy, invalid
):
    response = 'Result: {"outer":{"queue":"billing"},"extra":' + invalid + "}"
    result = evaluate_response(
        response,
        {
            "type": "json_schema",
            "schema": {"type": "object", "required": ["queue"]},
            "parsing_policy": parsing_policy,
        },
    )
    assert result["valid"] is False
    assert "invalid JSON" in result["error"]


@pytest.mark.parametrize("parsing_policy", ["prose_tolerant", "first_json_value"])
def test_prose_parser_can_use_separate_value_after_invalid_candidate(parsing_policy):
    result = evaluate_response(
        'Result: {"note":"}","extra":NaN}; final: {"queue":"billing"}',
        {
            "type": "json_schema",
            "schema": {"type": "object", "required": ["queue"]},
            "parsing_policy": parsing_policy,
        },
    )
    assert result["valid"] is True


@pytest.mark.parametrize("constraint", [{}, {"additionalProperties": True}])
def test_omitted_or_true_extra_field_rule_preserves_permissive_behavior(constraint):
    schema = {
        "type": "object",
        "properties": {"queue": {"type": "string"}},
        **constraint,
    }
    validate_config_validations({"validation": {"json_schema": schema}})
    assert evaluate_response(
        '{"queue":"billing","extra":1}', {"type": "json_schema", "schema": schema}
    )["valid"]


def test_output_rule_configuration_and_negative_fixtures_are_accepted():
    config = {
        "validation": {"json_schema": routing_schema()},
        "validation_fixtures": [
            {
                "name": "accepted",
                "response": '[{"queue":"billing","confidence":0.95}]',
                "expect": "pass",
            },
            {
                "name": "extra",
                "response": '[{"queue":"billing","confidence":0.95,"extra":1}]',
                "expect": "fail",
            },
            {
                "name": "range",
                "response": '[{"queue":"billing","confidence":2}]',
                "expect": "fail",
            },
        ],
    }
    validate_config_validations(config)
    assert check_contract(config)["ok"]


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "additionalProperties": {}},
        {"type": "object", "additionalProperties": "false"},
        {"type": "number", "additionalProperties": False},
        {"type": "object", "additionalProperties": False, "required": ["undeclared"]},
        {"type": "string", "minimum": 0},
        {"type": "number", "minimum": True},
        {"type": "number", "maximum": "1"},
        {"type": "number", "minimum": float("nan")},
        {"type": "number", "maximum": float("inf")},
        {"type": "number", "minimum": 2, "maximum": 1},
        {"type": "number", "exclusiveMinimum": 0},
        {"type": "number", "minimum": 0, "enum": [-1]},
    ],
)
def test_invalid_bounded_rules_are_configuration_errors(schema):
    with pytest.raises(ValueError, match="json_schema"):
        validate_config_validations({"validation": {"json_schema": schema}})


@pytest.mark.parametrize("value", [-1, 0, 1, 2])
def test_integer_bounds_are_inclusive(value):
    schema = {"type": "integer", "minimum": 0, "maximum": 1}
    validate_config_validations({"validation": {"json_schema": schema}})
    assert evaluate_response(str(value), {"type": "json_schema", "schema": schema})[
        "valid"
    ] is (0 <= value <= 1)


def test_validator_semantics_are_bound_to_contract_provenance(monkeypatch):
    original = provenance(
        {"validation": {"json_schema": routing_schema()}}, [], "price"
    )
    assert original["validator_version"] == "output-schema-3"
    monkeypatch.setattr(
        "llm_preflight.contracts.OUTPUT_VALIDATOR_VERSION", "output-schema-4"
    )
    changed = provenance({"validation": {"json_schema": routing_schema()}}, [], "price")
    assert original["config_sha256"] == changed["config_sha256"]
    assert original["contract_sha256"] != changed["contract_sha256"]
    assert original["evidence_sha256"] != changed["evidence_sha256"]


@pytest.mark.parametrize(
    ("old_version", "new_version", "state"),
    [
        (None, None, "unknown"),
        (None, "output-schema-1", "unknown"),
        ("output-schema-1", "output-schema-1", "compatible"),
        ("output-schema-1", "output-schema-2", "incompatible"),
        ("output-schema-2", "output-schema-3", "incompatible"),
    ],
)
def test_baselines_require_matching_known_validator_semantics(
    old_version, new_version, state
):
    def result(version):
        identity = {"schema_version": 1, "contract_sha256": "same"}
        if version is not None:
            identity["validator_version"] = version
        return {"provenance": identity, "models": []}

    comparison = compare_results(result(old_version), result(new_version))
    assert comparison["comparability"] == state
    if state != "compatible":
        assert any("validator" in warning for warning in comparison["warnings"])
