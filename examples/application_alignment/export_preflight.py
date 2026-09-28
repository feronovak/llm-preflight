"""Export a reviewable mock configuration from application-owned definitions."""

import json

from . import app

TICKET = "I was charged twice for the same subscription."


def build_config():
    request = app.build_request(TICKET)
    schema = app.response_schema()
    # These expectations belong to this ticket, rather than every valid route.
    schema["properties"][app.QUEUE_FIELD]["enum"] = ["billing"]
    schema["properties"][app.PRIORITY_FIELD]["enum"] = ["high"]
    accepted = {
        app.QUEUE_FIELD: "billing",
        app.PRIORITY_FIELD: "high",
        app.CONFIDENCE_FIELD: 0.95,
    }
    responses = [
        ("accepted", accepted, "pass"),
        (
            "wrong queue for this ticket",
            {**accepted, app.QUEUE_FIELD: "technical"},
            "fail",
        ),
        ("undeclared field", {**accepted, "internal_note": "forbidden"}, "fail"),
        ("confidence outside range", {**accepted, app.CONFIDENCE_FIELD: 2}, "fail"),
    ]
    fixtures = [
        {
            "name": name,
            "response": json.dumps(value, sort_keys=True, separators=(",", ":")),
            "expect": expected,
        }
        for name, value, expected in responses
    ]
    return {
        "name": "application-owned-routing-contract",
        **request,
        "models": [
            {
                "name": "local-mock",
                "provider": "mock",
                "model": "application-alignment-demo",
                "response": fixtures[0]["response"],
                "input_cost_per_million": 0,
                "output_cost_per_million": 0,
            }
        ],
        "validation": {"json_schema": schema},
        "validation_fixtures": fixtures,
        "repetitions": 1,
        "warmups": 0,
        "concurrency": 1,
        "max_requests": 1,
        "max_estimated_cost_usd": 0,
        "save_responses": False,
    }


if __name__ == "__main__":
    print(json.dumps(build_config(), indent=2))
