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
        ({"type": "numeric", "expected": 42, "tolerance": 0.01}, "42.005", 1.0),
        ({"type": "numeric", "expected": 42, "tolerance": 0.01}, "41", 0.0),
    ],
)
def test_deterministic_evaluators(evaluator, response, expected_score):
    result = evaluate_response(response, evaluator)
    assert result["score"] == expected_score


def test_invalid_json_is_a_scored_failure():
    result = evaluate_response("not json", {"type": "json_subset", "expected": {}})
    assert result == {"score": 0.0, "valid": False, "error": "invalid JSON"}
