import importlib.util
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from llm_preflight import cli, pricing

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts/release_freshness.py"


def _script():
    spec = importlib.util.spec_from_file_location("release_freshness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_freshness_passes_on_the_snapshot_review_day(capsys):
    assert _script().main(["--today", "2026-10-16"]) == 0

    output = capsys.readouterr().out
    assert "FAIL" not in output
    assert "Release freshness on 2026-10-16: pass" in output


def test_release_freshness_names_each_stale_example_and_its_reason(capsys):
    assert _script().main(["--today", "2026-10-31"]) == 1

    output = capsys.readouterr().out
    failed = [
        line.split()[2]
        for line in output.splitlines()
        if line.startswith("FAIL pricing-check")
    ]
    assert failed == ["examples/glm-5.3-openrouter-comparison.json"]
    assert "OpenRouter Relace endpoint pricing pricing is stale by 31 days" in output
    assert "ok pricing-check examples/approved-smoke.json" in output
    assert "Release freshness on 2026-10-31: fail" in output


def test_official_snapshots_stay_fresh_through_november_15(capsys):
    script = _script()
    script.main(["--today", "2026-11-15"])
    assert "official pricing snapshot is stale" not in capsys.readouterr().out

    assert script.main(["--today", "2026-11-16"]) == 1
    output = capsys.readouterr().out
    assert "official pricing snapshot is stale by 31 days" in output
    assert "official pricing snapshot is stale by 32 days" not in output


def test_release_freshness_reports_stale_retirement_rows_in_the_examples(capsys):
    script = _script()
    script.EXAMPLES = ()

    assert script.main(["--today", "2026-11-16"]) == 1

    output = capsys.readouterr().out
    assert "FAIL audit-source examples: inconclusive" in output
    assert "stale" in output.split("FAIL audit-source examples")[1]


def test_release_freshness_script_exits_non_zero_on_a_stale_day():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--today", "2026-11-16"],
        cwd=ROOT.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stderr
    assert "FAIL pricing-check examples/approved-smoke.json" in result.stdout


def test_make_release_freshness_and_the_release_workflow_run_the_script():
    makefile = (ROOT / "Makefile").read_text()
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    recipe = makefile.split("release-freshness:\n", 1)[1].split("\n\n", 1)[0]

    assert recipe.strip() == "python3 scripts/release_freshness.py"
    assert workflow.index("make release-freshness") < workflow.index("python -m build")
    for example in _script().EXAMPLES:
        assert (ROOT / "examples" / f"{example}.json").is_file()


def test_release_freshness_without_today_uses_the_real_utc_date(monkeypatch, capsys):
    script = _script()
    monkeypatch.setattr(script, "today_utc", lambda: date(2026, 11, 16))

    assert script.main([]) == 1
    assert "Release freshness on 2026-11-16: fail" in capsys.readouterr().out


def _cli_json(monkeypatch, capsys, arguments):
    monkeypatch.setattr(sys, "argv", ["llm-preflight", *arguments])
    try:
        cli.main()
    except SystemExit as exc:
        status = exc.code
    else:
        status = 0
    return status, json.loads(capsys.readouterr().out)


def _pin_cli_day(monkeypatch, today):
    class PinnedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(today.year, today.month, today.day, tzinfo=tz)

    monkeypatch.setattr(pricing, "datetime", PinnedDatetime)
    monkeypatch.setattr(cli, "today_utc", lambda: today)


@pytest.mark.parametrize(
    "today",
    [
        date.fromisoformat(value)
        for value in (
            "2026-10-13",
            "2026-10-14",
            "2026-10-16",
            "2026-10-28",
            "2026-10-29",
            "2026-10-30",
            "2026-10-31",
            "2026-11-12",
            "2026-11-13",
            "2026-11-14",
            "2026-11-15",
            "2026-11-16",
            "2026-12-01",
            "2027-01-01",
        )
    ],
)
def test_release_freshness_agrees_with_cli_at_snapshot_boundaries(
    monkeypatch, capsys, today
):
    script = _script()
    _pin_cli_day(monkeypatch, today)
    for example in script.EXAMPLES:
        path = ROOT / "examples" / f"{example}.json"
        status, report = _cli_json(
            monkeypatch, capsys, [str(path), "--pricing-check", "--no-env-file"]
        )
        reasons = script.pricing_reasons(path, today)
        assert bool(reasons) == (status != 0), (today, example, reasons, report)
        if reasons:
            assert reasons == [
                f"{row['provider']}/{row['model']}: {row['message']}"
                for row in report["warnings"]
            ]

    status, report = _cli_json(
        monkeypatch,
        capsys,
        ["--audit-source", str(ROOT / "examples"), "--ci", "--json"],
    )
    decision, reasons = script.retirement_reasons(ROOT / "examples", today)
    assert decision == report["decision"]
    assert status == {"pass": 0, "none": 0, "fail": 1, "inconclusive": 3}[decision]
    assert reasons == [
        f"{row['path']}:{row['line']}: {row['model']} — "
        f"{row['retirement']['status']}: {row['retirement']['reason']}"
        for row in report["references"]
        if row["retirement"]["status"] in {"retired", "retiring", "stale"}
    ]


@pytest.mark.parametrize("strict", [False, True])
def test_release_freshness_matches_cli_for_optional_stale_override(
    monkeypatch, tmp_path, capsys, strict
):
    today = date(2026, 10, 14)
    _pin_cli_day(monkeypatch, today)
    path = tmp_path / "benchmark.json"
    path.write_text(
        json.dumps(
            {
                "prompt": "Reply with ok.",
                "require_current_pricing": strict,
                "models": [
                    {
                        "provider": "openai_compatible",
                        "model": "local",
                        "input_cost_per_million": 1,
                        "output_cost_per_million": 2,
                        "pricing_metadata": {
                            "as_of": "2026-01-01",
                            "source": "owner",
                        },
                    }
                ],
            }
        )
    )
    status, report = _cli_json(
        monkeypatch, capsys, [str(path), "--pricing-check", "--no-env-file"]
    )
    assert report["summary"]["stale"] == int(strict)
    assert report["models"][0]["as_of"] == "2026-01-01"
    assert status == int(strict)
    assert bool(_script().pricing_reasons(path, today)) == strict


@pytest.mark.parametrize(
    ("model", "expected_decision", "expected_status", "flagged"),
    [
        ("gpt-4-32k", "fail", 1, True),
        ("gpt-4o", "inconclusive", 3, True),
        ("claude-sonnet-5-5", "pass", 0, False),
        ("gpt-99-future", "none", 0, False),
    ],
)
def test_release_retirement_gate_matches_cli_for_each_decision(
    monkeypatch, tmp_path, capsys, model, expected_decision, expected_status, flagged
):
    today = date(2026, 10, 14)
    _pin_cli_day(monkeypatch, today)
    source = tmp_path / "app.py"
    source.write_text(f'model = "{model}"\n')
    status, report = _cli_json(
        monkeypatch, capsys, ["--audit-source", str(source), "--ci", "--json"]
    )
    decision, reasons = _script().retirement_reasons(source, today)
    assert decision == report["decision"] == expected_decision
    assert status == expected_status
    assert bool(reasons) == flagged
