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
    assert _listed(provenance["prompts"]) == [
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
    assert _listed(result["provenance"]["prompts"]) == [
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


def _listed(prompts):
    """Which prompts provenance lists; the request fingerprints are tested apart."""
    return [
        {key: value for key, value in entry.items() if key != "request_sha256"}
        for entry in prompts
    ]


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
# Pinned in 2.22.0, when each listed prompt gained the fingerprint of the
# request sent with it and each route the settings that shape its requests.
# 2.21.2 recorded f4c54b5c… for the same run.
TOP_LEVEL_ONLY_EVIDENCE_SHA256 = (
    "3ff22ff485766df47c61f9ec555aca9614d53ebd8180e37ae99e736dd9f97422"
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

    assert _listed(result["provenance"]["prompts"]) == [
        _prompt_entry("config-prompt", "solo")
    ]
    assert result["provenance"]["contract_sha256"] == CONTRACT_SHA256[shape]
    assert (
        provenance(config, config["models"], "price")["evidence_sha256"]
        != TOP_LEVEL_WITH_PROMPTS_2_21_EVIDENCE_SHA256
    )


def test_provenance_of_a_profile_run_lists_each_case_it_sent():
    config = load_config(Path("tests/fixtures/two-prompts.json"))

    configured = run_benchmark({**config, "prompt": "solo", "profiles": ["p1"]})
    selected = run_benchmark(config, profile_selector="quick-migration-check,p2")

    assert _listed(configured["provenance"]["prompts"]) == [
        _prompt_entry("p1", "say alpha")
    ]
    assert [entry["name"] for entry in selected["provenance"]["prompts"]] == [
        "chat-capital",
        "chat-summary",
        "chat-rewrite",
        "p2",
    ]
    assert _listed(selected["provenance"]["prompts"])[-1] == _prompt_entry(
        "p2", "say beta"
    )


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


REQUEST_BASE = {
    "prompt": "Reply with ok.",
    "validation": {"exact": "ok"},
    "request": {"temperature": 0, "max_output_tokens": 64, "system_prompt": "Terse."},
    "models": [{"provider": "mock", "model": "local", "response": "ok"}],
}


def _request_fingerprint(config, profiles=()):
    (entry,) = provenance(config, config["models"], "price", profiles)["prompts"]
    return entry


@pytest.mark.parametrize(
    "change",
    [
        {"system_prompt": "Ignore the validator."},
        {"temperature": 1.5},
        {"max_output_tokens": 5},
        {"reasoning_effort": "high"},
        {"provider_options": {"top_p": 0.1}},
    ],
    ids=["system_prompt", "temperature", "max_output_tokens", "reasoning", "options"],
)
def test_each_prompt_fingerprint_hashes_the_request_options_sent_with_it(change):
    before = provenance(REQUEST_BASE, REQUEST_BASE["models"], "price")
    edited = {**REQUEST_BASE, "request": {**REQUEST_BASE["request"], **change}}
    after = provenance(edited, edited["models"], "price")

    assert len(before["prompts"][0]["request_sha256"]) == 64
    assert (
        after["prompts"][0]["request_sha256"]
        != (before["prompts"][0]["request_sha256"])
    )
    assert after["prompts"][0]["sha256"] == before["prompts"][0]["sha256"]
    # The contract fingerprint, which baselines compare, never moves.
    assert after["contract_sha256"] == before["contract_sha256"]


def test_a_request_fingerprint_hashes_what_is_sent_never_a_secret_or_runtime_key():
    implicit = {k: v for k, v in REQUEST_BASE.items() if k != "request"}
    default = {**implicit, "request": {"temperature": 0, "max_output_tokens": 256}}
    keyed = {
        **REQUEST_BASE,
        "request": {
            **REQUEST_BASE["request"],
            "provider_options": {"api_key": "sk-synthetic-one"},
            "_image_base_dir": "/somewhere",
        },
    }
    rekeyed = copy.deepcopy(keyed)
    rekeyed["request"]["provider_options"]["api_key"] = "sk-synthetic-two"
    rekeyed["request"]["_image_base_dir"] = "/elsewhere"

    # A config without a request sends the runner's default request.
    assert _request_fingerprint(implicit) == _request_fingerprint(default)
    assert _request_fingerprint(implicit) != _request_fingerprint(REQUEST_BASE)
    assert _request_fingerprint(keyed) == _request_fingerprint(rekeyed)
    assert "sk-synthetic" not in str(provenance(keyed, keyed["models"], "price"))


def test_profile_prompt_fingerprints_merge_profile_request_presets_and_system_prompt():
    from llm_preflight.runner import select_test_profiles

    config = {
        **REQUEST_BASE,
        "prompts": [
            {
                "name": "json",
                "prompt": "Return JSON.",
                "validation": {"json_object": True},
                "request": {"max_output_tokens": 32},
                "system_prompt": "S1",
                "presets": ["json"],
            }
        ],
    }

    def fingerprint(edit):
        edited = copy.deepcopy(config)
        edit(edited)
        profiles = select_test_profiles(edited, "json")
        return _request_fingerprint(edited, profiles)["request_sha256"]

    unchanged = fingerprint(lambda c: None)
    for edit in (
        lambda c: c["prompts"][0].update(system_prompt="S2"),
        lambda c: c["prompts"][0].update(presets=["no-reasoning"]),
        lambda c: c["prompts"][0]["request"].update(max_output_tokens=8),
        lambda c: c["request"].update(temperature=1),
    ):
        assert fingerprint(edit) != unchanged


def _png_bytes(marker):
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big") * 2
        + b"\x08\x02\x00\x00\x00"
        + marker
    )


def test_image_inputs_are_fingerprinted_by_content_never_by_path(tmp_path):
    import json

    def fingerprint(name, marker):
        directory = tmp_path / name
        directory.mkdir()
        (directory / f"{name}.png").write_bytes(_png_bytes(marker))
        config = {
            **REQUEST_BASE,
            "request": {
                "input_images": [{"path": f"{name}.png", "mime_type": "image/png"}]
            },
        }
        path = directory / "benchmark.json"
        path.write_text(json.dumps(config))
        loaded = load_config(path)
        return _request_fingerprint(loaded)["request_sha256"]

    assert fingerprint("first", b"a") == fingerprint("moved", b"a")
    assert fingerprint("other", b"b") != fingerprint("again", b"a")


ROUTE = {"provider": "openai", "model": "gpt-4.1-mini"}


def _fingerprints(edit, config=REQUEST_BASE):
    edited = copy.deepcopy(config)
    edit(edited)
    return provenance(edited, edited["models"], "price")


@pytest.mark.parametrize(
    ("field", "texts", "fingerprint"),
    [
        (
            lambda c, text: c["request"].update(system_prompt=f"Reply in {text}."),
            ("sk-SK", "sk-IGNORE-ALL-RULES"),
            lambda p: p["prompts"][0]["request_sha256"],
        ),
        (
            lambda c, text: c["validation"].update(exact=text),
            ("sk-SK", "sk-XX"),
            lambda p: p["contract_sha256"],
        ),
        (
            lambda c, text: c["models"][0].update(base_url=f"https://{text}.example"),
            ("sk-proxy.good", "sk-proxy.evil"),
            lambda p: p["routes_sha256"],
        ),
    ],
    ids=["request", "contract", "routes"],
)
def test_fingerprints_tell_apart_texts_that_differ_only_in_a_secret_like_word(
    field, texts, fingerprint
):
    first, second = (
        fingerprint(_fingerprints(lambda c, text=text: field(c, text)))
        for text in texts
    )

    assert first != second


def test_routes_fingerprint_counts_behaviour_header_values_never_a_credential():
    def routes(**headers):
        config = {
            **REQUEST_BASE,
            "models": [
                {
                    **ROUTE,
                    "headers": {
                        "anthropic-beta": "tools-1",
                        "Authorization": "Bearer sk-synthetic-one",
                        "x-api-key": "synthetic-one",
                        "api-key": "synthetic-one",
                        **headers,
                    },
                }
            ],
        }
        return provenance(config, config["models"], "price")

    unchanged = routes()["routes_sha256"]

    assert (
        routes(
            Authorization="Bearer sk-synthetic-two",
            **{"x-api-key": "synthetic-two", "api-key": "synthetic-two"},
        )["routes_sha256"]
        == unchanged
    )
    assert routes(**{"anthropic-beta": "tools-2"})["routes_sha256"] != unchanged
    assert "synthetic-one" not in str(routes())


@pytest.mark.parametrize(
    ("route", "change"),
    [
        (ROUTE, {"capabilities": {"temperature": False}}),
        (ROUTE, {"supports_temperature": False}),
        (ROUTE, {"adapter": "openai_responses"}),
        (REQUEST_BASE["models"][0], {"response": "not ok"}),
    ],
    ids=["capabilities.temperature", "supports_temperature", "adapter", "mock"],
)
def test_routes_fingerprint_changes_with_each_route_setting_that_changes_a_request(
    route, change
):
    before = _fingerprints(lambda c: c.update(models=[route]))
    after = _fingerprints(lambda c: c.update(models=[{**route, **change}]))

    assert after["routes_sha256"] != before["routes_sha256"]


def test_routes_fingerprint_hashes_temperature_support_as_sent_not_as_spelled():
    spellings = [
        ROUTE,
        {**ROUTE, "supports_temperature": True},
        {**ROUTE, "capabilities": {"temperature": True}},
    ]

    assert (
        len(
            {
                _fingerprints(lambda c, r=r: c.update(models=[r]))["routes_sha256"]
                for r in spellings
            }
        )
        == 1
    )
