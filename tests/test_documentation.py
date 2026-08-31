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
    assert "**Last reviewed:** 2026-08-31 · **As of:** v2.10.0" in feature_map
    assert "current-price coverage gate" in feature_map
    assert "Schema-versioned agent decision contract" in feature_map
    assert "Opt-in, versioned agent-instruction block" in feature_map
    assert "Catalog-to-smoke eligibility" in feature_map
    assert "no-spend tool hints and workflow resource" in feature_map
    assert "GPT-5.6 Luna" in changelog
    assert "GPT-5.6 Terra" in changelog
    pricing_guide = (ROOT / "docs/guides/pricing-and-safety.md").read_text()
    assert "## Snapshot verification" in pricing_guide
    assert "source_url" in pricing_guide
    assert "## Release price review" in pricing_guide


def test_coding_agents_documents_the_inconclusive_exit_code():
    coding_agents = (ROOT / "docs/automation/coding-agents.md").read_text()

    assert "`3` for inconclusive evidence" in coding_agents


def test_docs_match_the_2_10_0_workflow_and_current_workflow_pin():
    readme = (ROOT / "README.md").read_text()
    ci = (ROOT / "docs/automation/ci.md").read_text()
    workflow = (ROOT / "examples/github-actions/preflight.yml").read_text()
    docmap = (ROOT / "docs/DOCMAP.md").read_text()

    assert "## What is new in 2.10.0" in readme
    assert "Make MCP discovery safer" in readme
    assert "For earlier releases, see the [changelog](CHANGELOG.md)." in readme
    assert "## Common jobs" in readme
    assert "catalog prepare benchmarks/watch.json" in readme
    assert "## Safety boundary" in readme
    assert "llm-preflight==2.7.3" in workflow
    assert "Pin the starter workflow to the current release" in ci
    assert "| stamped | 2026-08-30 | v2.7.5 |" in docmap


def test_readme_leads_with_a_safe_first_run_and_workflow_choices():
    readme = (ROOT / "README.md").read_text()

    assert "## Try it in 60 seconds" in readme
    assert "## Choose your path" in readme
    assert "## Safety boundary" in readme
    assert "## Common jobs" in readme
    assert "## What is new in 2.10.0" in readme
    assert "## Delivered in 2.8.0" not in readme
    assert "## Delivered in 2.7.5" not in readme
    assert (
        readme.index("## Try it in 60 seconds")
        < readme.index("## Choose your path")
        < readme.index("## Safety boundary")
    )
    assert readme.index("## What is new in 2.10.0") < readme.index("## Purpose")


def test_cli_and_pricing_docs_cover_every_builtin_pack_and_pricing_gate():
    cli_reference = (ROOT / "docs/reference/cli.md").read_text()
    pricing_guide = (ROOT / "docs/guides/pricing-and-safety.md").read_text()

    for profile in (
        "quick-migration-check",
        "exact-routing-check",
        "structured-output-check",
        "numeric-instruction-check",
        "concurrency-health-check",
        "strict-json-extraction",
        "support-classification",
        "code-patch-summary",
        "source-grounded-quiz",
        "refusal-boundary-check",
    ):
        assert profile in cli_reference
        assert profile in pricing_guide
    assert "`--help`" in cli_reference
    assert "`--version`" in cli_reference
    assert "does not by itself block a benchmark" in cli_reference


def test_agent_honesty_docs_distinguish_terminal_decisions_and_pricing_gates():
    readme = (ROOT / "README.md").read_text()
    coding_agents = (ROOT / "docs/automation/coding-agents.md").read_text()
    agent_validation = (ROOT / "docs/automation/agent-validation.md").read_text()
    decision_reference = (ROOT / "docs/reference/decision.md").read_text()
    agents = (ROOT / "AGENTS.md").read_text()

    assert readme.index("python3 -m pip install llm-preflight") < readme.index(
        "llm-preflight init"
    )
    assert "pricing advisory" in readme
    assert "fail-closed coverage gate" in readme
    assert "llmci" not in readme
    assert "llm-preflight benchmark.json --pricing-check" in coding_agents
    assert "llm-preflight benchmark.json --pricing-check" in agent_validation
    assert "terminal summary is not the decision object" in decision_reference
    assert "- llm_preflight/decision.py" in agents


def test_visitor_docs_stamp_json_evidence_and_release_scope_are_current():
    retained_stamps = (
        ROOT / "docs/getting-started/safe-demo.md",
        ROOT / "docs/reference/decision.md",
        ROOT / "docs/automation/ci.md",
    )
    for page in retained_stamps:
        assert "**Last reviewed:** 2026-08-30 · **As of:** v2.7.5" in page.read_text()

    for page in (
        ROOT / "docs/automation/coding-agents.md",
        ROOT / "docs/guides/model-catalog.md",
        ROOT / "docs/reference/cli.md",
        ROOT / "docs/reference/results.md",
    ):
        assert "**Last reviewed:** 2026-08-31 · **As of:** v2.8.0" in page.read_text()

    for page in (
        ROOT / "README.md",
        ROOT / "docs/index.md",
        ROOT / "docs/FEATURE_MAP.md",
        ROOT / "docs/PROJECT_MAP.md",
        ROOT / "docs/automation/mcp.md",
    ):
        assert "**Last reviewed:** 2026-08-31 · **As of:** v2.10.0" in page.read_text()

    for page in (ROOT / "docs/guides/pricing-and-safety.md",):
        assert "**Last reviewed:** 2026-08-30 · **As of:** v2.7.5" in page.read_text()

    safe_demo = (ROOT / "docs/getting-started/safe-demo.md").read_text()
    ci = (ROOT / "docs/automation/ci.md").read_text()
    north_star = (ROOT / "docs/NORTH_STAR.md").read_text()

    assert '"state": "inconclusive"' in safe_demo
    assert "saved JSON artifact" in safe_demo
    assert "## Release documentation checklist" in ci
    assert "examples/github-actions/preflight.yml" in ci
    assert "tests/test_package.py" in ci
    assert "not a built-in tool-schema validator" in north_star


def test_positioning_and_decisions_are_public_and_current():
    readme = (ROOT / "README.md").read_text()
    positioning = (ROOT / "docs/product/positioning.md").read_text()
    north_star = (ROOT / "docs/NORTH_STAR.md").read_text()
    decisions = (ROOT / "docs/DECISIONS.md").read_text()
    metadata = (ROOT / "pyproject.toml").read_text()

    assert "## Choose your path" in readme
    assert "Review a new model" in readme
    assert "local contract preflight for LLM integration\nchanges" in readme
    assert "[North star](../NORTH_STAR.md)" in positioning
    assert "**Last reviewed:** 2026-08-30 · **As of:** v2.7.5" in north_star
    assert "## Mission" in north_star
    assert "## Niche" in north_star
    assert "**Last reviewed:** 2026-08-30 · **As of:** v2.7.5" in decisions
    for decision in (
        "Local-first execution",
        "Standard-library runtime",
        "Three-state decisions",
        "Human approval for spend and promotion",
    ):
        assert decision in decisions
    assert (
        'description = "Local, cross-provider preflight checks for LLM integration changes"'
        in metadata
    )


def test_project_map_indexes_distribution_assets():
    project_map = (ROOT / "docs/PROJECT_MAP.md").read_text()

    assert "CI workflows and safe issue forms" in project_map
    assert "action.yml" in project_map


def test_local_markdown_links_resolve_after_docs_reorganization():
    for page in (ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))):
        for target in re.findall(r"\]\(([^)]+)\)", page.read_text()):
            target = target.split("#", 1)[0]
            if not target or "://" in target:
                continue
            assert (page.parent / target).is_file(), f"{page}: {target}"
