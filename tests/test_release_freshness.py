import importlib.util
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts/release_freshness.py"


def _script():
    spec = importlib.util.spec_from_file_location("release_freshness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_freshness_passes_on_the_snapshot_review_day(capsys):
    assert _script().main(["--today", "2026-10-13"]) == 0

    output = capsys.readouterr().out
    assert "FAIL" not in output
    assert "Release freshness on 2026-10-13: pass" in output


def test_release_freshness_names_each_stale_example_and_its_reason(capsys):
    assert _script().main(["--today", "2026-10-29"]) == 1

    output = capsys.readouterr().out
    failed = [
        line.split()[2]
        for line in output.splitlines()
        if line.startswith("FAIL pricing-check")
    ]
    assert failed == [
        "examples/approved-smoke.json",
        "examples/cross-provider-run.json",
        "examples/frontier-candidates.json",
        "examples/flagship-comparison.json",
    ]
    assert "official pricing snapshot is stale by 31 days" in output
    assert "ok pricing-check examples/anthropic-5.5-checks.json" in output
    assert "Release freshness on 2026-10-29: fail" in output


def test_release_freshness_reports_stale_retirement_rows_in_the_examples(capsys):
    script = _script()
    script.EXAMPLES = ()

    assert script.main(["--today", "2026-11-13"]) == 1

    output = capsys.readouterr().out
    assert "FAIL audit-source examples: inconclusive" in output
    assert "stale" in output.split("FAIL audit-source examples")[1]


def test_release_freshness_script_exits_non_zero_on_a_stale_day():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--today", "2026-10-29"],
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
    monkeypatch.setattr(script, "today_utc", lambda: date(2026, 10, 29))

    assert script.main([]) == 1
    assert "Release freshness on 2026-10-29: fail" in capsys.readouterr().out
