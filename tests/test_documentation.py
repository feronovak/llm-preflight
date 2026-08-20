import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_docs_home_and_mcp_guide_are_first_class_entry_points():
    readme = (ROOT / "README.md").read_text()
    mcp_guide = (ROOT / "docs/automation/mcp.md").read_text()

    assert "## MCP for coding agents" in readme
    assert "## Connect common coding agents" in mcp_guide
    assert "### Codex" in mcp_guide
    assert "### Claude Code" in mcp_guide
    assert "### Cursor" in mcp_guide
    assert "docs/index.md" in readme
    assert (ROOT / "docs/index.md").is_file()
    assert (ROOT / "docs/automation/mcp.md").is_file()


def test_mcp_release_notes_and_security_boundary_are_current():
    changelog = (ROOT / "CHANGELOG.md").read_text()
    mcp_guide = (ROOT / "docs/automation/mcp.md").read_text()
    feature_map = (ROOT / "docs/FEATURE_MAP.md").read_text()

    for change in (
        "model aliases and provider presets",
        "`ping`",
        "Do not load `.env.production`",
        "mock or unconfirmed runs",
        "`confirm_paid_run`",
    ):
        assert change in changelog
    assert "server requires `confirm_paid_run: true`" in mcp_guide
    assert "agent-supplied boolean" in mcp_guide
    assert "not proof of user approval" in mcp_guide
    assert "**Last reviewed:** 2026-08-20 · **As of:** v2.7.3" in feature_map
    assert "current-price coverage gate" in feature_map
    assert "Schema-versioned agent decision contract" in feature_map
    assert "Opt-in, versioned agent-instruction block" in feature_map
    assert "GPT-5.6 Luna" in changelog
    assert "GPT-5.6 Terra" in changelog
    pricing_guide = (ROOT / "docs/guides/pricing-and-safety.md").read_text()
    assert "## Snapshot verification" in pricing_guide
    assert "source_url" in pricing_guide


def test_coding_agents_documents_the_inconclusive_exit_code():
    coding_agents = (ROOT / "docs/automation/coding-agents.md").read_text()

    assert "`3` for inconclusive evidence" in coding_agents


def test_local_markdown_links_resolve_after_docs_reorganization():
    for page in (ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))):
        for target in re.findall(r"\]\(([^)]+)\)", page.read_text()):
            target = target.split("#", 1)[0]
            if not target or "://" in target:
                continue
            assert (page.parent / target).is_file(), f"{page}: {target}"
