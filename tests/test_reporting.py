import json
from pathlib import Path

import pytest

from llm_preflight.reporting import render_job_summary, render_report_html


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
