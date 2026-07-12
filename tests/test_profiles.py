import pytest

from llm_bench.profiles import evaluate_response, select_profiles


def test_all_selects_every_supported_profile_except_coding():
    profiles = select_profiles("all")
    assert [profile["name"] for profile in profiles] == [
        "chat-fast",
        "classification",
        "structured-extraction",
        "reasoning",
        "load",
    ]


def test_profile_list_can_select_a_mixed_subset():
    profiles = select_profiles("chat-fast,reasoning")
    assert [profile["name"] for profile in profiles] == [
        "chat-fast",
        "reasoning",
    ]


def test_structured_extraction_defines_labels_and_has_room_for_reasoning():
    profile = select_profiles("structured-extraction")[0]
    ticket = next(case for case in profile["cases"] if case["id"] == "extract-ticket")
    assert "high, medium, or low" in ticket["prompt"]
    assert profile["request"]["max_output_tokens"] >= 512


def test_reasoning_prompts_request_numeric_only_answers():
    profile = select_profiles("reasoning")[0]

    for case in profile["cases"]:
        assert "Return only the numeric answer" in case["prompt"]
        assert "Do not include units" in case["prompt"]
        assert "explanation" in case["prompt"]


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
