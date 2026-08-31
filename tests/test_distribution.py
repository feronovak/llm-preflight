from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_marketplace_action_defaults_to_no_spend_preflight_checks():
    action = (ROOT / "action.yml").read_text()

    assert "runs:" in action
    assert "using: composite" in action
    assert "run-paid:" in action
    assert 'default: "false"' in action
    assert "--doctor --json" in action
    assert "--pricing-check" in action
    assert "--smoke --dry-run --json" in action
    assert "--smoke --json --no-save" in action


def test_action_is_exercised_with_a_mock_config_and_read_only_permissions():
    workflow = (ROOT / ".github/workflows/action-smoke.yml").read_text()

    assert "contents: read" in workflow
    assert "uses: ./" in workflow
    assert "examples/starter/mock-benchmark.json" in workflow
    assert 'package-version: "2.8.0"' in workflow
    assert "run-paid" not in workflow


def test_issue_forms_and_comparison_page_keep_reporting_safe_and_scoped():
    provider = (ROOT / ".github/ISSUE_TEMPLATE/provider-breakage.yml").read_text()
    pricing = (ROOT / ".github/ISSUE_TEMPLATE/pricing-drift.yml").read_text()
    comparison = (ROOT / "docs/product/when-to-use.md").read_text()

    for form in (provider, pricing):
        assert "Do not include API keys" in form
        assert "private prompts" in form
        assert "validation" in form
    assert "evaluation suite" in comparison
    assert "observability platform" in comparison
    assert "provider CLI" in comparison
    assert "not a universal ranking" in comparison
    assert "../NORTH_STAR.md" in comparison
    assert "../reference/decision.md" in comparison
