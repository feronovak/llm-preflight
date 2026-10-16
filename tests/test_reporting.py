import json
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

import pytest

from llm_preflight.reporting import (
    render_card_svg,
    render_job_summary,
    render_report_html,
)


@pytest.mark.parametrize(
    ("fixture", "state"),
    [
        ("schema-baseline", "pass"),
        ("schema-break", "fail"),
        ("cheaper-candidate-fails", "fail"),
        ("latency-cost-change", "pass"),
    ],
)
def test_synthetic_gallery_declares_coverage_for_its_intended_decision(fixture, state):
    result = json.loads((Path("examples/reports") / f"{fixture}.json").read_text())
    summary = render_job_summary(result)
    assert f"**Decision:** {state}" in summary
    assert "Legacy artifact" not in summary
    assert "Estimated cost: n/a" not in summary


def sample_result():
    return {
        "schema_version": 1,
        "run_id": "private-run-identifier",
        "timestamp": "2026-09-24T10:00:00+00:00",
        "benchmark": "private-project-name",
        "environment": {"hostname": "alice-workstation", "python": "3.13.1"},
        "source_config_path": "/home/alice/private/config.json",
        "prompt_name": "customer-support-prompt",
        "prompt_sha256": "a" * 64,
        "source_config": {"prompt": "private prompt contents"},
        "total_estimated_cost_usd": 0.002,
        "cost_confidence": "complete",
        "cost_coverage": {
            "known_requests": 4,
            "missing_usage_requests": 0,
            "missing_price_requests": 0,
            "unobserved_retry_requests": 0,
        },
        "usage_coverage": {"input_tokens": 4, "output_tokens": 4},
        "total_input_tokens": 100,
        "total_output_tokens": 20,
        "models": [
            {
                "name": "internal-deployment-name",
                "provider": "mock",
                "model": '<img src=x onerror="alert(1)">',
                "summary": {
                    "requests": 4,
                    "successful": 3,
                    "failed": 1,
                    "success_rate": 0.75,
                    "valid_output_rate": 0.5,
                    "contract_only_failures": 0,
                    "latency_seconds": {"p50": 0.3, "p95": 0.8},
                    "estimated_cost_usd": 0.002,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "failure_reasons": {"private response text": 1},
                },
                "samples": [{"prompt": "private prompt", "response": "private reply"}],
            }
        ],
        "pricing_coverage": {
            "models": [
                {
                    "provider": "mock",
                    "model": '<img src=x onerror="alert(1)">',
                    "status": "<script>alert(1)</script>",
                    "source": "official snapshot",
                    "as_of": "2026-09-24",
                    "source_url": "https://example.test/private?token=do-not-export",
                }
            ]
        },
        "baseline_diff": {
            "ok": False,
            "comparability": "compatible",
            "warnings": ["private baseline path"],
            "models": [{"regressions": ["cost", "latency_p95"]}],
        },
        "decision": {"state": "pass", "reason": "untrusted decision text"},
    }


def test_html_report_summarizes_v1_result_without_private_metadata_or_active_markup():
    html = render_report_html(sample_result())

    assert "Decision: fail" in html
    assert "Comparability: compatible" in html
    assert "Baseline comparison: regression" in html
    assert "Contract validity" in html
    assert "Requests: 4" in html
    assert "contract-only failures: 0" in html
    assert "100" in html and "20" in html
    assert "0.002" in html
    assert "official provider snapshot" in html
    assert "private-project-name" not in html
    assert "private-run-identifier" not in html
    assert "alice-workstation" not in html
    assert "untrusted decision text" not in html
    assert "private baseline path" not in html
    assert "internal-deployment-name" not in html
    assert "/home/alice" not in html
    assert "private prompt" not in html
    assert "private reply" not in html
    assert "private response text" not in html
    assert "do-not-export" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "https://" not in html
    assert "<script" not in html


def test_job_summary_is_compact_and_omits_prompts_and_local_paths():
    summary = render_job_summary(sample_result())

    assert "## LLM Preflight" in summary
    assert "**Decision:** fail" in summary
    assert "Contract-only failures: 0" in summary
    assert "**Comparability:** compatible" in summary
    assert "**Baseline comparison:** regression" in summary
    assert "cost" in summary
    assert "private-project-name" not in summary
    assert "private-run-identifier" not in summary
    assert "alice-workstation" not in summary
    assert "/home/alice" not in summary
    assert "private prompt" not in summary
    assert "private reply" not in summary
    assert "private response text" not in summary


def test_legacy_complete_zero_cost_is_not_verified_evidence():
    result = sample_result()
    result.pop("cost_coverage")
    result["models"][0]["summary"].update(
        requests=1,
        failed=0,
        successful=1,
        success_rate=1,
        valid_output_rate=1,
        estimated_cost_usd=0,
        input_tokens=0,
        output_tokens=0,
    )
    result["models"][0]["samples"] = [
        {"ok": True, "valid_output": True, "input_tokens": None, "output_tokens": None}
    ]
    result["cost_confidence"] = "complete"
    result["pricing_coverage"] = {"summary": {"billable": 1}, "models": []}
    html = render_report_html(result)
    summary = render_job_summary(result)
    assert "Decision: inconclusive" in html
    assert "estimated cost: n/a" in html
    assert "Legacy artifact: cost completeness is unverified" in html
    assert "Estimated cost: n/a" in summary
    assert "Legacy artifact: cost completeness is unverified" in summary
    assert (
        result["cost_confidence"] == "complete"
    )  # Rendering does not rewrite history.


def test_saved_result_renderer_rejects_unknown_major_schema():
    payload = sample_result()
    payload["schema_version"] = 2

    with pytest.raises(ValueError, match="schema version 1"):
        render_report_html(payload)


def test_contract_only_failure_count_is_unavailable_when_older_summary_omits_it():
    payload = sample_result()
    del payload["models"][0]["summary"]["contract_only_failures"]

    assert "contract-only failures: n/a" in render_report_html(payload)


def test_saved_result_renderer_rejects_malformed_result_shape():
    with pytest.raises(ValueError, match="models"):
        render_job_summary({"schema_version": 1, "models": "not-a-list"})

    payload = sample_result()
    payload["models"][0]["samples"] = "not-a-list"
    with pytest.raises(ValueError, match="samples"):
        render_report_html(payload)

    payload = sample_result()
    payload["models"][0]["summary"]["valid_output_rate"] = "unknown"
    with pytest.raises(ValueError, match="valid_output_rate"):
        render_report_html(payload)

    with pytest.raises(ValueError, match="non-empty"):
        render_report_html({"schema_version": 1, "models": []})


def test_report_command_writes_an_offline_html_file_without_provider_calls(
    monkeypatch, tmp_path
):
    import sys

    from llm_preflight import cli

    source = tmp_path / "result.json"
    source.write_text(json.dumps(sample_result()))
    destination = tmp_path / "report.html"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "llm-preflight",
            "report",
            str(source),
            "--format",
            "html",
            "--output",
            str(destination),
        ],
    )

    cli.main()

    assert destination.read_text().startswith("<!doctype html>")


def test_synthetic_gallery_fixtures_render_without_live_provider_calls():
    gallery = Path(__file__).parents[1] / "examples" / "reports"

    reports = [
        render_report_html(json.loads(path.read_text()))
        for path in gallery.glob("*.json")
    ]

    assert len(reports) == 4
    assert all("Limitations:" in report for report in reports)
    assert any("Decision: fail" in report for report in reports)
    assert any("Baseline comparison: regression" in report for report in reports)


CARD_TODAY = date(2026, 10, 17)
CARD_GOLDEN = Path(__file__).parent / "fixtures" / "cards"
FORBIDDEN_WORDS = (
    "certified",
    "certificate",
    "guaranteed",
    "compliant",
    "nutrition label",
)


def _card_model(provider, model, *, valid, p95, cost, requests=16):
    return {
        "name": f"private-{model}",
        "provider": provider,
        "model": model,
        "summary": {
            "requests": requests,
            "successful": requests,
            "failed": 0,
            "success_rate": 1.0,
            "valid_output_rate": valid / requests,
            "contract_only_failures": 0,
            "latency_seconds": {"p50": p95 / 2, "p95": p95},
            "estimated_cost_usd": cost,
            "input_tokens": 100 * requests,
            "output_tokens": 20 * requests,
        },
        "samples": [{"ok": True, "valid_output": i < valid} for i in range(requests)],
    }


def card_result(state):
    """A deterministic schema-v1 result whose recomputed decision is `state`."""
    models = {
        "pass": [
            _card_model(
                "anthropic", "claude-haiku-5-5", valid=16, p95=0.934, cost=0.000479
            ),
            _card_model("openai", "gpt-4.1-mini", valid=16, p95=1.412, cost=0.000612),
        ],
        "inconclusive": [
            _card_model("openai", "gpt-4.1-mini", valid=16, p95=1.412, cost=None),
        ],
        "fail": [
            _card_model(
                "gemini", "gemini-3.8-flash", valid=13, p95=2.255, cost=0.005666
            ),
            _card_model(
                "anthropic", "claude-sonnet-4-20250514", valid=16, p95=1.1, cost=0.0052
            ),
        ],
    }[state]
    if state == "pass":
        models[0]["observed_model"] = "claude-haiku-5-5-20261001"
    complete = state != "inconclusive"
    return {
        "schema_version": 1,
        "run_id": "private-run-identifier",
        "timestamp": "2026-10-14T09:30:00+00:00",
        "benchmark": "support-routing",
        "environment": {"hostname": "alice-workstation"},
        "source_config_path": "/home/alice/private/benchmark.json",
        "prompt_name": "customer-support-prompt",
        "source_config": {"prompt": "private prompt contents"},
        "models": models,
        "pricing_coverage": {
            "summary": {"billable": len(models)},
            "models": [
                {
                    "provider": model["provider"],
                    "model": model["model"],
                    "status": "priced",
                    "source": "official snapshot",
                    "as_of": "2026-10-16",
                }
                for model in models
            ],
        },
        "cost_confidence": "complete" if complete else "partial",
        "total_estimated_cost_usd": (
            sum(model["summary"]["estimated_cost_usd"] for model in models)
            if complete
            else None
        ),
        "cost_coverage": {
            "known_requests": 16 * len(models) if complete else 0,
            "missing_usage_requests": 0,
            "missing_price_requests": 0,
            "unobserved_retry_requests": 0,
        },
        "usage_coverage": {"input_tokens": 16, "output_tokens": 16},
        "provenance": {"schema_version": 1, "evidence_sha256": "3f9a1c" + "0" * 58},
    }


@pytest.mark.parametrize("state", ["pass", "inconclusive", "fail"])
def test_svg_card_matches_its_golden_file_for_each_verdict(state):
    rendered = render_card_svg(card_result(state), today=CARD_TODAY)

    assert rendered == (CARD_GOLDEN / f"{state}.svg").read_text(encoding="utf-8")


def test_svg_card_is_well_formed_self_contained_and_accessible():
    namespace = "{http://www.w3.org/2000/svg}"
    for state in ("pass", "inconclusive", "fail"):
        svg = render_card_svg(card_result(state), today=CARD_TODAY)
        root = ElementTree.fromstring(svg)

        assert root.tag == f"{namespace}svg"
        assert root.get("width") == "600"
        assert root.get("role") == "img"
        assert root.find(f"{namespace}title").text.startswith("LLM Preflight: ")
        assert "Does not certify" in root.find(f"{namespace}desc").text
        assert "<script" not in svg and "href" not in svg and "url(" not in svg
        assert "@import" not in svg and "@font-face" not in svg
        assert svg.count("http") == 1  # the SVG namespace, nothing fetched
        assert svg == render_card_svg(card_result(state), today=CARD_TODAY)


def test_svg_card_states_counts_and_limits_without_a_bare_percentage():
    passed = render_card_svg(card_result("pass"), today=CARD_TODAY)
    failed = render_card_svg(card_result("fail"), today=CARD_TODAY)
    unknown = render_card_svg(card_result("inconclusive"), today=CARD_TODAY)

    assert ">PASS<" in passed and ">FAIL<" in failed and ">INCONCLUSIVE<" in unknown
    assert "16 probes, all passed" in passed
    assert "13 of 16 passed" in failed
    assert "%" not in passed + failed + unknown
    for svg in (passed, failed, unknown):
        assert "Does not certify: accuracy · safety · production behaviour" in svg
        assert "Not attested: no preflight record was given" in svg
        assert not any(word in svg.lower() for word in FORBIDDEN_WORDS)
    assert "$0.0299 per 1,000 calls" in passed
    assert "cost unknown" in unknown and "per 1,000 calls" not in unknown
    assert "Why:" in unknown and "To pass:" in unknown
    assert "Cost confidence is partial" in unknown
    assert "Why:" in failed and "To pass:" not in failed and "Why:" not in passed


def test_svg_card_shows_the_observed_model_and_retirement_status():
    passed = render_card_svg(card_result("pass"), today=CARD_TODAY)
    failed = render_card_svg(card_result("fail"), today=CARD_TODAY)

    assert "claude-haiku-5-5 (anthropic)" in passed
    assert "claude-haiku-5-5-20261001" in passed
    assert passed.count(">Observed<") == 1
    assert "retiring on 2027-01-14" in passed
    assert "active in the bundled snapshot" in passed
    assert "retired on 2026-06-15" in failed
    assert ">Observed<" not in failed


def test_svg_card_escapes_text_and_keeps_non_ascii_names():
    result = card_result("pass")
    result["benchmark"] = '<b>&"Žltý čaj ✓"</b>\x00\u202e'

    svg = render_card_svg(result, today=CARD_TODAY)
    root = ElementTree.fromstring(svg)

    assert "&lt;b&gt;&amp;&quot;Žltý čaj ✓&quot;&lt;/b&gt;" in svg
    assert "<b>" not in svg
    assert "\x00" not in svg and "\u202e" not in svg
    assert '<b>&"Žltý čaj ✓"</b>' in "".join(root.itertext())


def test_svg_card_omits_private_metadata():
    svg = render_card_svg(card_result("pass"), today=CARD_TODAY)

    for private in (
        "private-run-identifier",
        "alice-workstation",
        "/home/alice",
        "customer-support-prompt",
        "private prompt contents",
        "private-claude-haiku-5-5",
    ):
        assert private not in svg
