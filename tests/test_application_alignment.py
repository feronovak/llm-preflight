import json
import subprocess
import sys
from pathlib import Path

import pytest

from llm_preflight.contracts import check_contract
from llm_preflight.features import estimate_budget
from llm_preflight.runner import run_benchmark, validate_config_validations

EXAMPLE = Path("examples/application_alignment")


def test_application_export_matches_reviewed_request_schema_and_case_fixtures():
    from examples.application_alignment import app, export_preflight

    config = export_preflight.build_config()
    assert config == json.loads((EXAMPLE / "benchmark.generated.json").read_text())
    expected = json.loads((EXAMPLE / "request-and-schema.expected.json").read_text())
    request = app.build_request(export_preflight.TICKET)
    assert request == expected["request"]
    assert app.response_schema() == expected["application_schema"]
    assert config["prompt"] == request["prompt"]
    assert config["request"] == request["request"]
    validate_config_validations(config)
    assert check_contract(config)["ok"]
    accepted = config["validation_fixtures"][0]["response"]
    assert app.parse_response(accepted)[app.QUEUE_FIELD] == "billing"
    for fixture in config["validation_fixtures"][2:]:
        with pytest.raises(ValueError):
            app.parse_response(fixture["response"])
    # Wrong queue is structurally valid to the app, but wrong for this ticket.
    assert (
        app.parse_response(config["validation_fixtures"][1]["response"])[
            app.QUEUE_FIELD
        ]
        == "technical"
    )
    completed = subprocess.run(
        [sys.executable, "-m", "examples.application_alignment.export_preflight"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(completed.stdout) == config


def test_regeneration_tracks_shared_app_changes_without_claiming_parser_execution(
    monkeypatch,
):
    from examples.application_alignment import app, export_preflight

    old = export_preflight.build_config()
    monkeypatch.setattr(app, "QUEUE_FIELD", "route")
    changed = export_preflight.build_config()
    assert changed != old
    assert "route" in changed["validation"]["json_schema"]["required"]
    assert "route" in changed["request"]["system_prompt"]
    assert check_contract(changed)["ok"]
    assert (
        app.parse_response(changed["validation_fixtures"][0]["response"])["route"]
        == "billing"
    )
    # A stale standalone contract can pass while the changed consumer rejects it.
    assert check_contract(old)["ok"]
    with pytest.raises(ValueError):
        app.parse_response(old["validation_fixtures"][0]["response"])


def test_application_export_is_bounded_and_keeps_mock_evidence_inconclusive():
    from examples.application_alignment.export_preflight import build_config

    config = build_config()
    plan = estimate_budget(config)
    assert plan["requests"] == plan["possible_requests"] == 1
    assert plan["maximum_estimated_cost_usd"] == 0
    result = run_benchmark(config)
    assert result["models"][0]["summary"]["valid_output_rate"] == 1
    assert result["decision"]["state"] == "inconclusive"
    assert result["pricing_coverage"]["summary"]["billable"] == 0
