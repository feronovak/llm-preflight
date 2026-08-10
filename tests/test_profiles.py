import pytest

from llm_preflight.profiles import evaluate_response, select_profiles
from llm_preflight.runner import validate_config_validations


def test_all_selects_every_supported_profile_except_coding():
    profiles = select_profiles("all")
    assert [profile["name"] for profile in profiles] == [
        "quick-migration-check",
        "exact-routing-check",
        "structured-output-check",
        "numeric-instruction-check",
        "concurrency-health-check",
        "strict-json-extraction",
        "support-classification",
        "code-patch-summary",
        "source-grounded-quiz",
        "refusal-boundary-check",
    ]


def test_profile_list_accepts_legacy_names_and_returns_clear_canonical_names():
    profiles = select_profiles("chat-fast,reasoning")
    assert [profile["name"] for profile in profiles] == [
        "quick-migration-check",
        "numeric-instruction-check",
    ]


def test_agent_smoke_selects_curated_functional_contracts_without_load():
    profiles = select_profiles("agent-smoke")

    assert [profile["name"] for profile in profiles] == [
        "strict-json-extraction",
        "support-classification",
        "code-patch-summary",
        "source-grounded-quiz",
        "refusal-boundary-check",
    ]


def test_quick_migration_check_is_described_by_user_value():
    profile = select_profiles("quick-migration-check")[0]

    assert "API compatibility" in profile["description"]
    assert "TTFT" in profile["description"]


def test_structured_extraction_defines_labels_and_has_room_for_reasoning():
    profile = select_profiles("structured-output-check")[0]
    ticket = next(case for case in profile["cases"] if case["id"] == "extract-ticket")
    assert "high, medium, or low" in ticket["prompt"]
    assert profile["request"]["max_output_tokens"] >= 512


def test_reasoning_prompts_request_numeric_only_answers():
    profile = select_profiles("numeric-instruction-check")[0]

    for case in profile["cases"]:
        assert "Return only the numeric answer" in case["prompt"]
        assert "Do not include units" in case["prompt"]
        assert "explanation" in case["prompt"]


def test_numeric_answer_evaluator_rejects_explanation_even_when_it_mentions_answer():
    result = evaluate_response(
        "The new price is 100.",
        {"type": "numeric_answer", "expected": 100, "tolerance": 0},
    )

    assert result["valid"] is False


def test_contains_evaluator_rejects_an_empty_expected_value():
    result = evaluate_response("anything", {"type": "contains", "contains": ""})

    assert result["valid"] is False


@pytest.mark.parametrize(
    ("evaluator", "response", "valid"),
    [
        ({"type": "json_object"}, '{"status":"ok"}', True),
        ({"type": "json_object"}, '["ok"]', False),
        ({"type": "json_array"}, '["one","two"]', True),
        ({"type": "json_array"}, '{"one":1}', False),
        ({"type": "no_markdown"}, "Plain text only.", True),
        ({"type": "no_markdown"}, "```json\n{}\n```", False),
        ({"type": "exact_count", "expected": 2}, '["one","two"]', True),
        ({"type": "exact_count", "expected": 2}, '["one"]', False),
        (
            {"type": "allowed_values", "values": ["billing", "technical"]},
            "Billing",
            True,
        ),
        (
            {"type": "allowed_values", "values": ["billing", "technical"]},
            "account",
            False,
        ),
        ({"type": "max_chars", "maximum": 5}, "short", True),
        ({"type": "max_chars", "maximum": 5}, "too long", False),
    ],
)
def test_common_contract_evaluators(evaluator, response, valid):
    assert evaluate_response(response, evaluator)["valid"] is valid


def test_composite_evaluator_requires_every_contract():
    evaluator = {
        "type": "all",
        "evaluators": [
            {"type": "json_object"},
            {"type": "no_markdown"},
            {"type": "max_chars", "maximum": 20},
        ],
    }

    assert evaluate_response('{"ok":true}', evaluator)["valid"] is True
    assert evaluate_response('```json\n{"ok":true}\n```', evaluator)["valid"] is False


@pytest.mark.parametrize(
    ("evaluator", "response", "expected_score"),
    [
        ({"type": "nonempty"}, "answer", 1.0),
        ({"type": "exact", "expected": "billing"}, " Billing \n", 1.0),
        (
            {"type": "json_subset", "expected": {"priority": "high"}},
            '{"priority":"high","summary":"Login broken"}',
            1.0,
        ),
        (
            {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "required": ["questions"],
                    "properties": {"questions": {"type": "array", "minItems": 1}},
                },
            },
            '{"questions":[{"id":"q1"}]}',
            1.0,
        ),
        ({"type": "numeric", "expected": 42, "tolerance": 0.01}, "42.005", 1.0),
        ({"type": "numeric", "expected": 42, "tolerance": 0.01}, "41", 0.0),
        ({"type": "contains", "contains": "questions"}, '{"questions":[]}', 1.0),
        (
            {"type": "regex", "regex": '"questions"\\s*:\\s*\\['},
            '{"questions":[]}',
            1.0,
        ),
    ],
)
def test_deterministic_evaluators(evaluator, response, expected_score):
    result = evaluate_response(response, evaluator)
    assert result["score"] == expected_score


def test_invalid_json_is_a_scored_failure():
    result = evaluate_response("not json", {"type": "json_subset", "expected": {}})
    assert result == {"score": 0.0, "valid": False, "error": "invalid JSON"}


@pytest.mark.parametrize("evaluator_type", ["json_subset", "json_schema"])
@pytest.mark.parametrize("fence", ["```json", "```"])
def test_json_evaluators_accept_one_complete_fenced_block_when_enabled(
    evaluator_type, fence
):
    evaluator = {
        "type": evaluator_type,
        "allow_fenced_json": True,
        **(
            {"expected": {"priority": "high"}}
            if evaluator_type == "json_subset"
            else {
                "schema": {
                    "type": "object",
                    "required": ["priority"],
                    "properties": {"priority": {"type": "string"}},
                }
            }
        ),
    }

    result = evaluate_response(f'{fence}\n{{"priority": "high"}}\n```', evaluator)

    assert result == {"score": 1.0, "valid": True, "error": None}


def test_fenced_json_option_accepts_one_block_surrounded_by_prose():
    result = evaluate_response(
        'Explanation:\n```json\n{"priority":"high"}\n```\nDone.',
        {
            "type": "json_schema",
            "allow_fenced_json": True,
            "schema": {"type": "object", "required": ["priority"]},
        },
    )

    assert result == {"score": 1.0, "valid": True, "error": None}


@pytest.mark.parametrize(
    "response",
    [
        'The answer is {"priority":"high"}.',
        '```json\n{"priority":"high"}\n```\n```json\n{"priority":"low"}\n```',
    ],
)
def test_fenced_json_option_does_not_guess_a_payload_from_unfenced_prose_or_multiple_blocks(
    response,
):
    result = evaluate_response(
        response,
        {
            "type": "json_schema",
            "allow_fenced_json": True,
            "schema": {"type": "object", "required": ["priority"]},
        },
    )

    assert result == {
        "score": 0.0,
        "valid": False,
        "error": "invalid JSON (expected raw JSON or exactly one fenced JSON block)",
    }


def test_prose_tolerant_parser_accepts_one_nested_json_value():
    result = evaluate_response(
        'Answer: {"a": {"b": 1}}.',
        {
            "type": "json_schema",
            "parsing_policy": "prose_tolerant",
            "schema": {"type": "object", "required": ["a"]},
        },
    )

    assert result["valid"] is True


def test_prose_tolerant_parser_rejects_two_separate_json_values():
    result = evaluate_response(
        'First: {"a": 1}; second: {"b": 2}',
        {"type": "json_object", "parsing_policy": "prose_tolerant"},
    )

    assert result == {
        "score": 0.0,
        "valid": False,
        "error": "invalid JSON (expected exactly one JSON value in prose)",
    }


def test_first_match_json_policies_model_first_fence_and_value():
    fenced = '```json\n{"a": 1}\n```\n```json\n{"a": 2}\n```'
    prose = 'First: {"a": 1}; second: {"a": 2}'

    assert (
        evaluate_response(
            fenced,
            {
                "type": "json_subset",
                "expected": {"a": 1},
                "parsing_policy": "first_fenced_block",
            },
        )["valid"]
        is True
    )
    assert (
        evaluate_response(
            prose,
            {
                "type": "json_subset",
                "expected": {"a": 1},
                "parsing_policy": "first_json_value",
            },
        )["valid"]
        is True
    )


def test_json_set_requires_the_same_unique_unordered_values():
    evaluator = {"type": "json_set", "key": "exclude", "expected": [2, 3, 4]}

    assert evaluate_response('{"exclude":[4,2,3]}', evaluator)["valid"] is True
    assert evaluate_response('{"exclude":[2,2,2]}', evaluator)["valid"] is False


@pytest.mark.parametrize(
    "schema",
    [
        {"required": ["a"]},
        {"type": "Object"},
        {"type": "str"},
    ],
)
def test_json_schema_requires_an_explicit_supported_type(schema):
    with pytest.raises(ValueError, match="type"):
        validate_config_validations(
            {
                "prompt": "ok",
                "models": [{"provider": "mock", "model": "m"}],
                "validation": {"json_schema": schema},
            }
        )


def test_json_schema_rejects_booleans_as_integers_and_numbers():
    for expected_type in ("integer", "number"):
        assert (
            evaluate_response(
                "true", {"type": "json_schema", "schema": {"type": expected_type}}
            )["valid"]
            is False
        )


@pytest.mark.parametrize(
    "policy", ["raw_json", "single_fenced_block", "prose_tolerant"]
)
def test_deeply_nested_json_is_an_invalid_output_not_a_crash(policy):
    response = "[" * 2_000 + "0" + "]" * 2_000

    result = evaluate_response(
        response,
        {
            "type": "json_array",
            "parsing_policy": policy,
        },
    )

    assert result == {"score": 0.0, "valid": False, "error": "invalid JSON"}


def test_prose_prefixed_deep_json_aborts_the_prose_scan():
    response = "x " + "[" * 2_000 + "0" + "]" * 2_000

    result = evaluate_response(
        response,
        {"type": "json_array", "parsing_policy": "prose_tolerant"},
    )

    assert result == {"score": 0.0, "valid": False, "error": "invalid JSON"}


def test_json_schema_reports_structural_mismatch():
    result = evaluate_response(
        '{"questions":[]}',
        {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "required": ["questions"],
                "properties": {"questions": {"type": "array", "minItems": 1}},
            },
        },
    )
    assert result == {
        "score": 0.0,
        "valid": False,
        "error": "questions must contain at least 1 items",
    }


def test_select_profiles_rejects_unknown_profile_names():
    with pytest.raises(ValueError, match="unknown profiles: bogus"):
        select_profiles("bogus")


def test_numeric_evaluator_rejects_a_non_numeric_response():
    result = evaluate_response(
        "not a number", {"type": "numeric", "expected": 5, "tolerance": 0}
    )
    assert result == {"score": 0.0, "valid": False, "error": "not a numeric answer"}


def test_numeric_answer_evaluator_accepts_a_matching_response():
    result = evaluate_response(
        "42", {"type": "numeric_answer", "expected": 42, "tolerance": 0}
    )
    assert result == {"score": 1.0, "valid": True, "error": None}


def test_evaluate_response_rejects_an_unknown_evaluator_type():
    with pytest.raises(ValueError, match="unknown evaluator type 'bogus'"):
        evaluate_response("anything", {"type": "bogus"})


@pytest.mark.parametrize(
    ("schema", "response", "expected_error"),
    [
        ({"type": "object"}, '"just text"', "value must be an object"),
        (
            {"type": "object", "required": ["name"]},
            "{}",
            "name is required",
        ),
        ({"type": "array"}, '{"a":1}', "value must be an array"),
        (
            {"type": "object", "properties": {"name": {"type": "string"}}},
            '{"name":123}',
            "name must be a string",
        ),
        (
            {"type": "object", "properties": {"amount": {"type": "number"}}},
            '{"amount":"nope"}',
            "amount must be a number",
        ),
        (
            {"type": "object", "properties": {"count": {"type": "integer"}}},
            '{"count":1.5}',
            "count must be an integer",
        ),
        (
            {"type": "object", "properties": {"flag": {"type": "boolean"}}},
            '{"flag":"yes"}',
            "flag must be a boolean",
        ),
    ],
)
def test_json_schema_reports_type_mismatches(schema, response, expected_error):
    result = evaluate_response(response, {"type": "json_schema", "schema": schema})
    assert result["valid"] is False
    assert result["error"] == expected_error


def test_json_schema_reports_nested_array_paths_and_enum():
    schema = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["mc", "tf", "sa"]},
                        "options": {"type": "array", "maxItems": 4},
                    },
                },
            }
        },
    }

    result = evaluate_response(
        '{"questions":[{"type":"essay","options":["a","b","c","d","e"]}]}',
        {"type": "json_schema", "schema": schema},
    )

    assert result["valid"] is False
    assert result["error"] == "questions[0].type must be one of: mc, tf, sa"

    result = evaluate_response(
        '{"questions":[{"type":"mc","options":["a","b","c","d","e"]}]}',
        {"type": "json_schema", "schema": schema},
    )

    assert result["valid"] is False
    assert result["error"] == "questions[0].options must contain at most 4 items"
