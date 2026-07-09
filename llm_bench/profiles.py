from __future__ import annotations

import json
from typing import Any


BUILTIN_PROFILES: list[dict[str, Any]] = [
    {
        "name": "chat-fast",
        "description": "Short interactive answers; emphasizes TTFT and latency.",
        "cases": [
            {
                "id": "chat-capital",
                "prompt": "Answer in one short sentence: What is the capital of France?",
                "evaluator": {"type": "nonempty"},
            },
            {
                "id": "chat-summary",
                "prompt": "Summarize in one sentence: A customer changed their email address and can no longer log in.",
                "evaluator": {"type": "nonempty"},
            },
            {
                "id": "chat-rewrite",
                "prompt": "Rewrite politely in one sentence: Send the report today.",
                "evaluator": {"type": "nonempty"},
            },
        ],
    },
    {
        "name": "classification",
        "description": "Exact-label classification accuracy.",
        "system_prompt": "Return only the requested lowercase label.",
        "cases": [
            {
                "id": "class-billing",
                "prompt": "Classify as billing, technical, or account: I was charged twice.",
                "evaluator": {"type": "exact", "expected": "billing"},
            },
            {
                "id": "class-technical",
                "prompt": "Classify as billing, technical, or account: The mobile app crashes on startup.",
                "evaluator": {"type": "exact", "expected": "technical"},
            },
            {
                "id": "class-account",
                "prompt": "Classify as billing, technical, or account: I need to change my login email.",
                "evaluator": {"type": "exact", "expected": "account"},
            },
        ],
    },
    {
        "name": "structured-extraction",
        "description": "JSON validity and exact required-field extraction.",
        "system_prompt": "Return only valid JSON with no Markdown formatting.",
        "request": {"max_output_tokens": 512},
        "cases": [
            {
                "id": "extract-ticket",
                "prompt": (
                    "Extract product and priority as high, medium, or low; map "
                    '"Urgent" to high: "Urgent: payments are failing in Checkout."'
                ),
                "evaluator": {
                    "type": "json_subset",
                    "expected": {"priority": "high", "product": "Checkout"},
                },
            },
            {
                "id": "extract-person",
                "prompt": 'Extract name and city: "Marta Novak lives in Bratislava."',
                "evaluator": {
                    "type": "json_subset",
                    "expected": {"name": "Marta Novak", "city": "Bratislava"},
                },
            },
            {
                "id": "extract-order",
                "prompt": 'Extract order_id and quantity: "Order A-104 contains 7 units."',
                "evaluator": {
                    "type": "json_subset",
                    "expected": {"order_id": "A-104", "quantity": 7},
                },
            },
        ],
    },
    {
        "name": "reasoning",
        "description": "Deterministic arithmetic and logic correctness.",
        "system_prompt": "Return only the final numeric answer.",
        "cases": [
            {
                "id": "reason-percent",
                "prompt": "A price of 80 increases by 25%. What is the new price?",
                "evaluator": {"type": "numeric", "expected": 100, "tolerance": 0},
            },
            {
                "id": "reason-rate",
                "prompt": "A car travels 150 km in 3 hours. What is its average speed in km/h?",
                "evaluator": {"type": "numeric", "expected": 50, "tolerance": 0},
            },
            {
                "id": "reason-sequence",
                "prompt": "What is the next number: 2, 6, 12, 20, 30?",
                "evaluator": {"type": "numeric", "expected": 42, "tolerance": 0},
            },
        ],
    },
    {
        "name": "load",
        "description": "Latency and reliability under increasing concurrency.",
        "concurrency_levels": [1, 5, 10],
        "cases": [
            {
                "id": "load-short",
                "prompt": "Reply with exactly: benchmark",
                "evaluator": {"type": "exact", "expected": "benchmark"},
            }
        ],
    },
]


def select_profiles(selector: str) -> list[dict[str, Any]]:
    requested = [item.strip() for item in selector.split(",") if item.strip()]
    names = [profile["name"] for profile in BUILTIN_PROFILES]
    if requested == ["all"]:
        return BUILTIN_PROFILES
    unknown = sorted(set(requested) - set(names))
    if unknown:
        raise ValueError(
            f"unknown profiles: {', '.join(unknown)}; choose all or {', '.join(names)}"
        )
    return [profile for profile in BUILTIN_PROFILES if profile["name"] in requested]


def evaluate_response(response: str, evaluator: dict[str, Any]) -> dict[str, Any]:
    evaluator_type = evaluator["type"]
    if evaluator_type == "nonempty":
        valid = bool(response.strip())
        return {
            "score": 1.0 if valid else 0.0,
            "valid": valid,
            "error": None if valid else "empty response",
        }
    if evaluator_type == "exact":
        valid = (
            response.strip().casefold() == str(evaluator["expected"]).strip().casefold()
        )
        return {
            "score": 1.0 if valid else 0.0,
            "valid": valid,
            "error": None if valid else "exact match failed",
        }
    if evaluator_type == "json_subset":
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            return {"score": 0.0, "valid": False, "error": "invalid JSON"}
        expected = evaluator["expected"]
        valid = isinstance(parsed, dict) and all(
            parsed.get(key) == value for key, value in expected.items()
        )
        return {
            "score": 1.0 if valid else 0.0,
            "valid": valid,
            "error": None if valid else "required JSON fields did not match",
        }
    if evaluator_type == "numeric":
        try:
            actual = float(response.strip().replace(",", ""))
        except ValueError:
            return {"score": 0.0, "valid": False, "error": "not a numeric answer"}
        valid = abs(actual - float(evaluator["expected"])) <= float(
            evaluator.get("tolerance", 0)
        )
        return {
            "score": 1.0 if valid else 0.0,
            "valid": valid,
            "error": None if valid else "numeric answer outside tolerance",
        }
    raise ValueError(f"unknown evaluator type {evaluator_type!r}")
