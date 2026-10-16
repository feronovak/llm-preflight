import copy
import hashlib
from pathlib import Path

import pytest

from llm_preflight.contracts import (
    check_contract,
    contract_fixtures_declared,
    provenance,
    validate_contract_config,
)
from llm_preflight.features import compare_results
from llm_preflight.runner import (
    load_config,
    run_benchmark,
    select_custom_prompt,
    validate_config_validations,
)


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
        "prompt_fixtures": [],
        "unproven_prompts": [],
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


def test_contract_check_evaluates_per_prompt_fixtures_against_that_prompts_validator():
    report = check_contract(
        {
            "prompts": [
                {
                    "name": "routing",
                    "prompt": "Route this ticket.",
                    "validation": {"exact": "billing"},
                    "validation_fixtures": [
                        {
                            "name": "right queue",
                            "response": "billing",
                            "expect": "pass",
                        },
                        {
                            "name": "wrong queue",
                            "response": "technical",
                            "expect": "fail",
                        },
                    ],
                },
                {
                    "name": "extraction",
                    "prompt": "Extract fields.",
                    "validation": {"json_object": True},
                    "validation_fixtures": [
                        {"name": "object", "response": "{}", "expect": "pass"},
                        {
                            "name": "fenced",
                            "response": "```json\n{}\n```",
                            "expect": "fail",
                        },
                    ],
                },
            ],
            "models": [{"provider": "mock", "model": "local", "response": "billing"}],
        }
    )

    assert report["ok"] is True
    assert report["fixtures"] == []
    assert report["tools"] == []
    assert report["prompt_fixtures"] == [
        {
            "prompt": "routing",
            "fixtures": [
                {"name": "right queue", "expected": "pass", "actual": "pass"},
                {"name": "wrong queue", "expected": "fail", "actual": "fail"},
            ],
        },
        {
            "prompt": "extraction",
            "fixtures": [
                {"name": "object", "expected": "pass", "actual": "pass"},
                {"name": "fenced", "expected": "fail", "actual": "fail"},
            ],
        },
    ]


def test_contract_check_reports_a_per_prompt_fixture_the_validator_wrongly_accepts():
    report = check_contract(
        {
            "prompts": [
                {
                    "name": "routing",
                    "prompt": "Route this ticket.",
                    "validation": {"contains": "ing"},
                    "validation_fixtures": [
                        {
                            "name": "right queue",
                            "response": "billing",
                            "expect": "pass",
                        },
                        {
                            "name": "wrong queue",
                            "response": "shipping",
                            "expect": "fail",
                        },
                    ],
                }
            ],
            "models": [{"provider": "mock", "model": "local", "response": "billing"}],
        }
    )

    assert report["ok"] is False
    assert report["prompt_fixtures"][0]["fixtures"][1] == {
        "name": "wrong queue",
        "expected": "fail",
        "actual": "pass",
        "error": "fixture expectation did not match validator result",
    }


def test_fixtures_without_a_validator_at_the_same_level_are_a_configuration_error():
    with pytest.raises(
        ValueError, match="validation_fixtures require a validation at the same level"
    ):
        validate_contract_config(
            {
                "prompts": [
                    {
                        "name": "routing",
                        "prompt": "Route.",
                        "validation": {"exact": "billing"},
                    }
                ],
                "validation_fixtures": [
                    {"name": "right queue", "response": "billing", "expect": "pass"},
                    {"name": "wrong queue", "response": "technical", "expect": "fail"},
                ],
                "models": [
                    {"provider": "mock", "model": "local", "response": "billing"}
                ],
            }
        )

    with pytest.raises(
        ValueError,
        match=r"prompt routing\.validation_fixtures require prompt routing\.validation",
    ):
        validate_contract_config(
            {
                "prompts": [
                    {
                        "name": "routing",
                        "prompt": "Route.",
                        "validation_fixtures": [
                            {"name": "a", "response": "billing", "expect": "pass"},
                            {"name": "b", "response": "technical", "expect": "fail"},
                        ],
                    }
                ],
                "models": [
                    {"provider": "mock", "model": "local", "response": "billing"}
                ],
            }
        )


def test_contract_fixtures_declared_recognises_every_scope():
    assert contract_fixtures_declared({"prompt": "x"}) is False
    assert (
        contract_fixtures_declared({"prompt": "x", "validation_fixtures": [{}]}) is True
    )
    assert contract_fixtures_declared({"tools": [{"name": "t"}]}) is True
    assert (
        contract_fixtures_declared(
            {
                "prompts": [
                    {"name": "a", "prompt": "x"},
                    {"name": "b", "prompt": "y", "validation_fixtures": [{}]},
                ]
            }
        )
        is True
    )


def test_benchmark_refuses_a_failed_per_prompt_contract_fixture_before_requests():
    with pytest.raises(ValueError, match="validation fixtures failed"):
        run_benchmark(
            {
                "prompts": [
                    {
                        "name": "routing",
                        "prompt": "Route.",
                        "validation": {"contains": "ing"},
                        "validation_fixtures": [
                            {"name": "ok", "response": "billing", "expect": "pass"},
                            {
                                "name": "too weak",
                                "response": "shipping",
                                "expect": "fail",
                            },
                        ],
                    }
                ],
                "models": [
                    {"provider": "mock", "model": "local", "response": "billing"}
                ],
            }
        )


def test_selected_prompt_copy_is_not_evaluated_twice_but_other_prompts_are():
    fixtures = [
        {"name": "ok", "response": "billing", "expect": "pass"},
        {"name": "bad", "response": "technical", "expect": "fail"},
    ]
    report = check_contract(
        {
            "prompt": "Route.",
            "prompt_name": "routing",
            "validation": {"exact": "billing"},
            "validation_fixtures": fixtures,
            "prompts": [
                {
                    "name": "routing",
                    "prompt": "Route.",
                    "validation": {"exact": "billing"},
                    "validation_fixtures": fixtures,
                },
                {
                    "name": "other",
                    "prompt": "Other.",
                    "validation": {"exact": "x"},
                    "validation_fixtures": [
                        {"name": "x", "response": "x", "expect": "pass"},
                        {"name": "y", "response": "y", "expect": "fail"},
                    ],
                },
            ],
            "models": [{"provider": "mock", "model": "local", "response": "billing"}],
        }
    )

    assert report["ok"] is True
    assert [entry["prompt"] for entry in report["prompt_fixtures"]] == ["other"]
    assert len(report["fixtures"]) == 2


def test_hand_set_prompt_name_cannot_turn_a_prompt_check_off():
    report = check_contract(
        {
            "prompt": "Main.",
            "prompt_name": "main",
            "validation": {"exact": "ok"},
            "validation_fixtures": [
                {"name": "ok", "response": "ok", "expect": "pass"},
                {"name": "no", "response": "no", "expect": "fail"},
            ],
            "prompts": [
                {
                    "name": "p1",
                    "prompt": "One.",
                    "validation": {"contains": "o"},
                    "validation_fixtures": [
                        {"name": "ok", "response": "ok", "expect": "pass"},
                        {
                            "name": "wrongly expected",
                            "response": "no",
                            "expect": "fail",
                        },
                    ],
                }
            ],
            "models": [{"provider": "mock", "model": "local", "response": "ok"}],
        }
    )

    assert report["ok"] is False


def test_contract_check_lists_prompts_that_declare_a_validator_but_no_fixtures():
    config = {
        "name": "mix",
        "repetitions": 1,
        "warmups": 0,
        "models": [
            {"name": "m", "provider": "mock", "model": "local", "response": "alpha"}
        ],
        "prompt": "say alpha",
        "validation": {"contains": "alpha"},
        "validation_fixtures": [
            {"name": "top-pass", "response": "alpha", "expect": "pass"},
            {"name": "top-fail", "response": "beta", "expect": "fail"},
        ],
        "prompts": [
            {
                "name": "p1",
                "prompt": "say beta",
                "validation": {"contains": "beta"},
                "validation_fixtures": [
                    {"name": "p1-pass", "response": "beta", "expect": "pass"},
                    {"name": "p1-fail", "response": "alpha", "expect": "fail"},
                ],
            },
            {"name": "p2", "prompt": "say gamma", "validation": {"regex": "^gamma$"}},
            {"name": "p3", "prompt": "say delta"},
        ],
    }

    report = check_contract(config)

    assert report["ok"] is True
    assert report["unproven_prompts"] == ["p2"]


def test_prompt_selection_lists_the_run_prompt_once_in_provenance():
    config = load_config(Path("tests/fixtures/two-prompts.json"))

    result = run_benchmark(select_custom_prompt(config, "p1"))

    assert result["prompt_name"] == "p1"
    assert result["provenance"]["prompts"] == [
        {
            "name": "p1",
            "sha256": result["prompt_sha256"],
            "chars": result["prompt_chars"],
        }
    ]


def _prompt_entry(name, text):
    return {
        "name": name,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "chars": len(text),
    }


def _provenance_shapes():
    configured = load_config(Path("tests/fixtures/two-prompts.json"))
    with_top_level = {**configured, "prompt": "solo", "validation": {"exact": "x"}}
    top_level_only = {k: v for k, v in with_top_level.items() if k != "prompts"}
    return {
        "configured prompts only": configured,
        "top-level prompt with configured prompts": with_top_level,
        "top-level prompt only": top_level_only,
    }


# Pinned from llm-preflight 2.21.2. Baseline comparison keys on the contract
# hash, so listing only the prompts that ran must never change it.
CONTRACT_SHA256 = {
    "configured prompts only": (
        "72d3e04d34843b2fae953e10fdacf27f4c2e943ce09cdf5bc0db1d06f8139554"
    ),
    "top-level prompt with configured prompts": (
        "87bb9da2644b9db7581be2a3d8bb791488910ca1fa26c531c34e8bbecf51b394"
    ),
    "top-level prompt only": (
        "9fe974807587de00ee73269859d16bee30cb513975792eb9555bec4e247e97dc"
    ),
}
# Pinned from llm-preflight 2.21.2. A run whose config has only a top-level
# prompt listed exactly that prompt, so its evidence hash must not move.
TOP_LEVEL_ONLY_EVIDENCE_SHA256 = (
    "f4c54b5cd7e4f4aaefcfb03974b356f7ff00ba5902f3c2ec44f8b6a720f845be"
)
# Pinned from llm-preflight 2.21.2, which also listed the configured prompts
# that did not run.
TOP_LEVEL_WITH_PROMPTS_2_21_EVIDENCE_SHA256 = (
    "b0c413e98e0b7b9830738617ccde6fd8f02fab287d9663b58d6a7fb41f8cc6ae"
)


def test_provenance_keeps_every_contract_hash_and_the_top_level_only_evidence():
    shapes = _provenance_shapes()

    observed = {
        label: provenance(config, config["models"], "price")
        for label, config in shapes.items()
    }

    assert {
        label: result["contract_sha256"] for label, result in observed.items()
    } == CONTRACT_SHA256
    assert (
        observed["top-level prompt only"]["evidence_sha256"]
        == TOP_LEVEL_ONLY_EVIDENCE_SHA256
    )


def test_provenance_of_a_top_level_prompt_run_omits_the_configured_prompts():
    shape = "top-level prompt with configured prompts"
    config = _provenance_shapes()[shape]

    result = run_benchmark(config)

    assert result["provenance"]["prompts"] == [_prompt_entry("config-prompt", "solo")]
    assert result["provenance"]["contract_sha256"] == CONTRACT_SHA256[shape]
    assert (
        provenance(config, config["models"], "price")["evidence_sha256"]
        != TOP_LEVEL_WITH_PROMPTS_2_21_EVIDENCE_SHA256
    )


def test_provenance_of_a_profile_run_lists_each_case_it_sent():
    config = load_config(Path("tests/fixtures/two-prompts.json"))

    configured = run_benchmark({**config, "prompt": "solo", "profiles": ["p1"]})
    selected = run_benchmark(config, profile_selector="quick-migration-check,p2")

    assert configured["provenance"]["prompts"] == [_prompt_entry("p1", "say alpha")]
    assert [entry["name"] for entry in selected["provenance"]["prompts"]] == [
        "chat-capital",
        "chat-summary",
        "chat-rewrite",
        "p2",
    ]
    assert selected["provenance"]["prompts"][-1] == _prompt_entry("p2", "say beta")


def test_baseline_from_before_the_prompt_fix_stays_comparable():
    config = load_config(Path("tests/fixtures/two-prompts.json"))
    current = run_benchmark(select_custom_prompt(config, "p1"))
    baseline = copy.deepcopy(current)
    baseline["provenance"]["prompts"] = [
        *current["provenance"]["prompts"],
        *[
            {
                "name": prompt["name"],
                "sha256": hashlib.sha256(prompt["prompt"].encode()).hexdigest(),
                "chars": len(prompt["prompt"]),
            }
            for prompt in config["prompts"]
        ],
    ]
    baseline["provenance"]["evidence_sha256"] = "2.21.x-evidence"

    diff = compare_results(baseline, current)

    assert diff["comparability"] == "compatible"
    assert all("provenance" not in warning for warning in diff["warnings"])
