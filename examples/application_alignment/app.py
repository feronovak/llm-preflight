"""A small application-owned routing contract; no provider execution."""

import json
import math

QUEUE_FIELD = "queue"
PRIORITY_FIELD = "priority"
CONFIDENCE_FIELD = "confidence"
QUEUES = ("billing", "technical", "account")
PRIORITIES = ("high", "normal")


def response_schema():
    return {
        "type": "object",
        "required": [QUEUE_FIELD, PRIORITY_FIELD, CONFIDENCE_FIELD],
        "additionalProperties": False,
        "properties": {
            QUEUE_FIELD: {"type": "string", "enum": list(QUEUES)},
            PRIORITY_FIELD: {"type": "string", "enum": list(PRIORITIES)},
            CONFIDENCE_FIELD: {"type": "number", "minimum": 0, "maximum": 1},
        },
    }


def build_request(ticket):
    fields = ", ".join(response_schema()["required"])
    return {
        "prompt": f"Route this support ticket: {ticket}",
        "request": {
            "system_prompt": (
                f"Return only JSON with {fields}. "
                f"Allowed queues: {', '.join(QUEUES)}. "
                f"Allowed priorities: {', '.join(PRIORITIES)}."
            ),
            "temperature": 0,
            "max_output_tokens": 100,
            "retry": {"max_attempts": 1},
        },
    }


def parse_response(response):
    """The app's own parser; Preflight does not call this function."""
    value = json.loads(response)
    if not isinstance(value, dict) or set(value) != set(response_schema()["required"]):
        raise ValueError("route fields do not match the consumer")
    if value[QUEUE_FIELD] not in QUEUES or value[PRIORITY_FIELD] not in PRIORITIES:
        raise ValueError("route labels are invalid")
    confidence = value[CONFIDENCE_FIELD]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or (isinstance(confidence, float) and not math.isfinite(confidence))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("route confidence must be finite and between zero and one")
    return value
