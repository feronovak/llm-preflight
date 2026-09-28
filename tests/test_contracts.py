import hashlib

import pytest

from llm_preflight.contracts import check_contract
from llm_preflight.runner import run_benchmark, validate_config_validations


@pytest.mark.parametrize(
    "entry", [check_contract, validate_config_validations, run_benchmark]
)
@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize(
    "keyword",
    ["additionalProperties", "minimum", "maximum", "$ref", "description", "anyOf"],
)
def test_unsupported_nested_output_schema_stops_before_provider_work(
    monkeypatch, entry, named, keyword
):
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"confidence": {"type": "number", keyword: False}},
        },
    }
    validation = {"json_schema": schema}
    config = {"prompt": "test", "models": [{"provider": "mock", "model": "local"}]}
    if named:
        config["prompts"] = [
            {"name": "routing", "prompt": "test", "validation": validation}
        ]
    else:
        config["validation"] = validation
    calls = []
    monkeypatch.setattr(
        "llm_preflight.runner.create_client", lambda *args: calls.append(args)
    )
    with pytest.raises(
        ValueError,
        match=rf"items.*properties.*confidence.*{keyword.replace('$', chr(92) + '$')}",
    ):
        entry(config)
    assert calls == []


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", "properties": {}},
        {"type": "number", "required": []},
        {"type": "object", "items": {"type": "string"}},
        {"type": "string", "minItems": 1},
        {"type": "array", "minItems": True},
        {"type": "array", "maxItems": -1},
        {"type": "array", "minItems": 1.5},
        {"type": "array", "minItems": 2, "maxItems": 1},
        {"type": "string", "enum": "billing"},
        {"type": "string", "enum": []},
        {"type": "number", "enum": [True]},
        {"type": "object", "required": ["queue", "queue"]},
        {"type": ["string", "null"]},
    ],
)
def test_output_schema_rejects_invalid_or_inapplicable_supported_rules(schema):
    with pytest.raises(ValueError, match="json_schema"):
        validate_config_validations({"validation": {"json_schema": schema}})


def test_contract_check_exercises_accept_and_reject_fixtures_without_a_provider_call():
    report = check_contract(
        {
            "validation": {
                "json_schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"type": "string"}},
                }
            },
            "validation_fixtures": [
                {"name": "accepted", "response": '{"status":"ok"}', "expect": "pass"},
                {
                    "name": "missing status",
                    "response": '{"detail":"no"}',
                    "expect": "fail",
                },
            ],
            "tools": [
                {
                    "name": "lookup_order",
                    "description": "Look up an order by ID.",
                    "parameters": {
                        "type": "object",
                        "required": ["order_id"],
                        "properties": {"order_id": {"type": "string"}},
                    },
                }
            ],
        }
    )

    assert report == {
        "ok": True,
        "fixtures": [
            {"name": "accepted", "expected": "pass", "actual": "pass"},
            {"name": "missing status", "expected": "fail", "actual": "fail"},
        ],
        "tools": [{"name": "lookup_order", "ok": True}],
    }


def test_contract_check_reports_a_fixture_that_the_validator_wrongly_accepts():
    report = check_contract(
        {
            "validation": {"contains": "ok"},
            "validation_fixtures": [
                {"name": "expected good", "response": "ok", "expect": "pass"},
                {"name": "too weak", "response": "not ok", "expect": "fail"},
            ],
        }
    )

    assert report["ok"] is False
    assert report["fixtures"][1] == {
        "name": "too weak",
        "expected": "fail",
        "actual": "pass",
        "error": "fixture expectation did not match validator result",
    }


def test_benchmark_refuses_a_failed_configured_contract_fixture_before_requests():
    with pytest.raises(ValueError, match="validation fixtures failed"):
        run_benchmark(
            {
                "prompt": "Reply with ok.",
                "validation": {"contains": "ok"},
                "validation_fixtures": [
                    {"name": "accepted", "response": "ok", "expect": "pass"},
                    {"name": "too weak", "response": "not ok", "expect": "fail"},
                ],
                "models": [{"provider": "mock", "model": "local", "response": "ok"}],
            }
        )


def test_validation_fixtures_require_a_positive_and_negative_case_and_tools_are_strict():
    with pytest.raises(ValueError, match="pass and fail fixture"):
        validate_config_validations(
            {
                "validation": {"exact": "ok"},
                "validation_fixtures": [
                    {"name": "only positive", "response": "ok", "expect": "pass"}
                ],
            }
        )

    with pytest.raises(ValueError, match=r"tools\[0\]\.parameters.type must be object"):
        validate_config_validations(
            {
                "tools": [
                    {
                        "name": "bad_tool",
                        "description": "Bad schema.",
                        "parameters": {"type": "array", "items": {"type": "string"}},
                    }
                ]
            }
        )


def test_result_has_secret_safe_provenance_fingerprints_for_contract_routes_and_limits():
    config = {
        "prompt": "Reply with ok.",
        "validation": {"exact": "ok"},
        "models": [
            {
                "provider": "mock",
                "model": "local",
                "response": "ok",
                "base_url": "https://mock.example/v1",
            }
        ],
        "max_requests": 2,
        "max_estimated_cost_usd": 0.01,
        "warmups": 0,
        "repetitions": 1,
    }

    result = run_benchmark(config)
    provenance = result["provenance"]

    assert provenance["schema_version"] == 1
    assert provenance["prompts"] == [
        {
            "name": "config-prompt",
            "sha256": hashlib.sha256(b"Reply with ok.").hexdigest(),
            "chars": 14,
        }
    ]
    assert provenance["limits"] == {
        "max_requests": 2,
        "max_estimated_cost_usd": 0.01,
    }
    assert provenance["pricing_sha256"] == result["pricing_fingerprint"]
    for key in ("config_sha256", "contract_sha256", "routes_sha256", "evidence_sha256"):
        assert len(provenance[key]) == 64
    assert "mock.example" not in str(provenance)
