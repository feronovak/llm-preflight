import json
from pathlib import Path

from llm_preflight import __version__

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
    assert 'package-version: "2.12.0"' in workflow
    assert "run-paid" not in workflow


def test_marketplace_action_installs_the_latest_published_package():
    action = (ROOT / "action.yml").read_text()

    assert 'default: "2.12.0"' in action


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


def test_mcp_registry_manifest_and_plugin_keep_discovery_local_and_safe():
    manifest = json.loads((ROOT / "server.json").read_text())
    plugin = json.loads(
        (ROOT / "plugins/llm-preflight/.codex-plugin/plugin.json").read_text()
    )
    skill = (ROOT / "plugins/llm-preflight/skills/llm-preflight/SKILL.md").read_text()
    readme = (ROOT / "README.md").read_text()

    assert manifest["name"] == "io.github.feronovak/llm-preflight"
    assert manifest["version"] == __version__
    assert manifest["packages"] == [
        {
            "registryType": "pypi",
            "identifier": "llm-preflight",
            "version": __version__,
            "transport": {"type": "stdio"},
            "packageArguments": [
                {
                    "type": "named",
                    "name": "--workspace",
                    "description": "Absolute path to the repository that the server may read.",
                    "isRequired": True,
                    "format": "filepath",
                }
            ],
        }
    ]
    assert "<!-- mcp-name: io.github.feronovak/llm-preflight -->" in readme
    assert plugin["name"] == "llm-preflight"
    assert plugin["version"] == __version__
    assert plugin["skills"] == "./skills/"
    assert "dry_run_plan" in skill
    assert "confirm_paid_run: true" in skill
    assert "must not infer approval" in skill


def test_testpypi_clean_install_exercises_the_mcp_no_spend_handshake():
    workflow = (ROOT / ".github/workflows/testpypi.yml").read_text()

    assert "llm-preflight-mcp --workspace" in workflow
    assert '"method":"initialize"' in workflow
    assert '"method":"resources/read"' in workflow
    assert "safe-workflow" in workflow
    assert "confirm_paid_run" not in workflow
