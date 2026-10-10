import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_current_snapshots_doc_lists_every_official_pricing_id():
    from llm_preflight.pricing import PUBLIC_PRICING

    page = (ROOT / "docs/guides/current-snapshots.md").read_text()

    assert "**As of:** v2.20.0" in page
    assert "Package version: **2.20.0**" in page
    assert "not a ranking" in page
    assert "Gemini 4" in page
    for provider, model_id in PUBLIC_PRICING:
        assert f"`{provider}`" in page
        assert f"`{model_id}`" in page


def test_docs_home_and_mcp_guide_are_first_class_entry_points():
    readme = (ROOT / "README.md").read_text()
    mcp_guide = (ROOT / "docs/automation/mcp.md").read_text()

    assert "## MCP for coding agents" in readme
    assert "## Connect common coding agents" in mcp_guide
    assert "### Codex" in mcp_guide
    assert "### Claude Code" in mcp_guide
    assert "### Cursor" in mcp_guide
    assert "## Registry discovery" in mcp_guide
    assert "## Clean-install verification" in mcp_guide
    assert "docs/index.md" in readme
    assert "docs/guides/current-snapshots.md" in readme
    assert (ROOT / "docs/index.md").is_file()
    assert (ROOT / "docs/automation/mcp.md").is_file()


def test_homepage_model_list_matches_comparison_evidence():
    readme = (ROOT / "README.md").read_text()
    docs_index = (ROOT / "docs/index.md").read_text()
    study_path = ROOT / "docs/guides/observed-model-comparison.md"
    study = study_path.read_text()

    assert "docs/guides/observed-model-comparison.md" in readme
    assert "guides/observed-model-comparison.md" in docs_index
    assert "2026-09-28" in study

    homepage_section = readme.split("## Model comparison", 1)[1]
    homepage_section = homepage_section.split("\n## ", 1)[0]
    study_section = study.split("## Comparison results", 1)[1]
    study_section = study_section.split("\n## ", 1)[0]
    homepage_ids = set(re.findall(r"`([\w./-]+)`", homepage_section))
    study_ids = set(re.findall(r"\| `([\w./-]+)` \|", study_section))

    assert len(study_ids) == 27
    assert "claude-haiku-5-5" in study_ids
    assert "gpt-6.1-sol" in study_ids
    assert "z-ai/glm-5.3" in study_ids
    assert homepage_ids == study_ids

    rows = re.findall(
        r"^\| [^|]+ \| `([^`]+)` \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$",
        study_section,
        re.MULTILINE,
    )
    assert len(rows) == len(study_ids)
    measured = 0
    for model, observed_on, valid, latency, cost in rows:
        if observed_on == "Not run":
            assert (valid, latency, cost) == ("—", "—", "—"), model
        else:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", observed_on), model
            assert 0 <= int(valid) <= 16
            assert re.fullmatch(r"\d+\.\d+s", latency), model
            assert re.fullmatch(r"\$\d+\.\d+", cost), model
            measured += 1
    assert f"{measured} measured" in readme
    assert f"{measured} measured" in study
    assert measured == 27
    for model in ("gpt-6.1-sol", "z-ai/glm-5.3"):
        row = next(row for row in rows if row[0] == model)
        assert row[1] == "2026-09-30"
    assert "OpenRouter / Relace" in study
    assert "native Z.ai route was not tested" in study
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5"):
        row = next(row for row in rows if row[0] == model)
        assert row[1:3] == ("2026-10-07", "16")
    for page in (readme, docs_index, study):
        assert "| `claude-haiku-5-5` | 16/16 | 53/53 | 5/6 | $0.0014602 |" in page
        assert "| `claude-sonnet-5-5` | 16/16 | 53/53 | 6/6 | $0.0221540 |" in page
        assert "password-reset" in page
    for page in (readme, docs_index):
        assert "2.20.0" in page
    assert "2.19.1" in study


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
    assert "**Last reviewed:** 2026-10-10 · **As of:** v2.20.0" in feature_map
    assert "current-price coverage gate" in feature_map
    assert "`--doctor` — validate config, keys, model resolution" in feature_map
    assert "Schema-versioned agent decision contract" in feature_map
    assert "Opt-in, versioned agent-instruction block" in feature_map
    assert "Catalog-to-smoke eligibility" in feature_map
    assert "Official pricing snapshots for named public model IDs" in feature_map
    assert "no-spend tool hints and workflow resource" in feature_map
    assert "registry manifest and repository plugin skill" in feature_map
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

    assert "## CLI, CI, and MCP" in readme
    assert "Works as a CLI, GitHub Action, and local MCP server" in readme
    assert (
        "Release notes for every version are in the [changelog](CHANGELOG.md)."
        in readme
    )
    assert "## Common jobs" in readme
    assert "catalog prepare benchmarks/watch.json" in readme
    assert "## Safety boundary" in readme
    assert "llm-preflight==2.19.2" in workflow
    assert "starter workflow pins the latest published package, 2.19.2" in ci
    assert "| stamped | 2026-08-30 | v2.7.5 |" in docmap


def test_readme_leads_with_a_safe_first_run_and_workflow_choices():
    readme = (ROOT / "README.md").read_text()

    assert "## Try it in 60 seconds" in readme
    assert "## Choose your path" in readme
    assert "**Configure a coding agent.**" in readme
    assert "llm-preflight-mcp --workspace" in readme
    assert "## Safety boundary" in readme
    assert "## Common jobs" in readme
    assert "The pre-merge check for LLM changes." in readme
    assert "## CLI, CI, and MCP" in readme
    assert "## Delivered in 2.8.0" not in readme
    assert "## Delivered in 2.7.5" not in readme
    assert (
        readme.index("## Try it in 60 seconds")
        < readme.index("## Choose your path")
        < readme.index("## Safety boundary")
    )
    assert (
        readme.index("## See a contract change fail")
        < readme.index("## Purpose")
        < readme.index("## Choose your path")
    )
    assert readme.index("## Safety boundary") < readme.index("## CLI, CI, and MCP")
    assert "Version **2." not in readme
    assert readme.count("## Purpose") == 1
    assert readme.index("## What live evidence looks like") < readme.index(
        "## First live run"
    )


def test_marketplace_action_writes_no_spend_and_paid_github_summaries():
    action = (ROOT / "action.yml").read_text()

    assert 'default: "2.19.2"' in action
    assert "GITHUB_STEP_SUMMARY" in action
    assert "No generation requests were made by the default checks." in action
    assert 'python -m llm_preflight report "$result_file" --format markdown' in action
    assert 'result_file="$(mktemp)"' in action
    assert "trap 'rm -f \"$result_file\"' EXIT" in action


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
    for page in (ROOT / "docs/reference/decision.md",):
        assert "**Last reviewed:** 2026-08-30 · **As of:** v2.7.5" in page.read_text()

    assert (
        "**Last reviewed:** 2026-10-10 · **As of:** v2.19.2"
        in (ROOT / "docs/automation/ci.md").read_text()
    )

    for page in (ROOT / "docs/guides/model-catalog.md",):
        assert "**Last reviewed:** 2026-10-09 · **As of:** v2.19.2" in page.read_text()

    for page in (ROOT / "docs/reference/results.md",):
        assert "**Last reviewed:** 2026-10-09 · **As of:** v2.19.2" in page.read_text()

    for page in (
        ROOT / "docs/automation/coding-agents.md",
        ROOT / "docs/automation/change-plans.md",
    ):
        assert "**Last reviewed:** 2026-09-04 · **As of:** v2.12.0" in page.read_text()

    assert (
        "**Last reviewed:** 2026-10-10 · **As of:** v2.20.0"
        in (ROOT / "docs/reference/cli.md").read_text()
    )

    for page in (ROOT / "docs/automation/mcp.md",):
        assert "**Last reviewed:** 2026-09-28 · **As of:** v2.18.0" in page.read_text()

    for page in (ROOT / "docs/reference/configuration.md",):
        assert "**Last reviewed:** 2026-10-09 · **As of:** v2.19.2" in page.read_text()

    assert (
        "**Last reviewed:** 2026-10-08 · **As of:** v2.19.1"
        in (ROOT / "docs/guides/pricing-and-safety.md").read_text()
    )

    assert (
        "**Last reviewed:** 2026-10-10 · **As of:** v2.20.0"
        in (ROOT / "docs/index.md").read_text()
    )
    assert (
        "**Last reviewed:** 2026-10-10 · **As of:** v2.20.0"
        in (ROOT / "README.md").read_text()
    )
    assert (
        "**Last reviewed:** 2026-10-10 · **As of:** v2.20.0"
        in (ROOT / "docs/FEATURE_MAP.md").read_text()
    )

    safe_demo = (ROOT / "docs/getting-started/safe-demo.md").read_text()
    assert "**Last reviewed:** 2026-09-09 · **As of:** v2.14.0" in safe_demo
    assert "llm-preflight init --template provider --interactive" in safe_demo
    assert safe_demo.count("**Last reviewed:**") == 1
    ci = (ROOT / "docs/automation/ci.md").read_text()
    north_star = (ROOT / "docs/NORTH_STAR.md").read_text()

    assert '"state": "inconclusive"' in safe_demo
    assert "saved JSON artifact" in safe_demo
    assert "## Release documentation checklist" in ci
    assert "examples/github-actions/preflight.yml" in ci
    assert "tests/test_package.py" in ci
    assert "statically validates a deliberately portable" in north_star


def test_marketplace_action_docs_describe_the_current_published_release():
    action_guide = (ROOT / "docs/automation/github-action.md").read_text()

    assert "**Last reviewed:** 2026-10-10 · **As of:** v2.19.2" in action_guide
    assert 'package-version: "2.19.2"' in action_guide
    assert "source defaults to `2.19.2`" in action_guide
    assert "`v2.19.2` release tag retains the `2.19.1`" in action_guide
    assert "latest published package (`2.19.2`)" in action_guide
    assert "under development" not in action_guide


def test_project_integration_example_supports_local_contract_and_plan():
    config = ROOT / "examples/project-integration/support-routing.json"
    guide = (ROOT / "docs/getting-started/project-integration.md").read_text()
    copied_config = re.search(r"```json\n(.*?)\n```", guide, re.DOTALL)
    assert copied_config is not None
    assert json.loads(copied_config.group(1)) == json.loads(config.read_text())
    for flag in ("--contract-check", "--dry-run"):
        result = subprocess.run(
            [sys.executable, "-m", "llm_preflight", str(config), flag, "--no-env-file"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr + result.stdout

    readme = (ROOT / "README.md").read_text()
    docs_index = (ROOT / "docs/index.md").read_text()
    assert "docs/getting-started/project-integration.md" in readme
    assert "getting-started/project-integration.md" in docs_index


def test_change_plans_guide_is_indexed_in_the_generated_document_map():
    docmap = (ROOT / "docs/DOCMAP.md").read_text()

    assert "docs/automation/change-plans.md" in docmap
    assert "docs/guides/current-snapshots.md" in docmap
    assert "docs/guides/reports.md" in docmap


def test_positioning_and_decisions_are_public_and_current():
    readme = (ROOT / "README.md").read_text()
    positioning = (ROOT / "docs/product/positioning.md").read_text()
    north_star = (ROOT / "docs/NORTH_STAR.md").read_text()
    when_to_use = (ROOT / "docs/product/when-to-use.md").read_text()
    decisions = (ROOT / "docs/DECISIONS.md").read_text()
    metadata = (ROOT / "pyproject.toml").read_text()

    assert "## Choose your path" in readme
    assert "Review a new model" in readme
    assert "The pre-merge check for LLM changes." in readme
    assert "local CLI and CI tool that checks an\napplication's LLM contract" in readme
    assert "[North star](../NORTH_STAR.md)" in positioning
    assert "**Last reviewed:** 2026-09-08 · **As of:** v2.12.0" in north_star
    assert "## Mission" in north_star
    assert "## Niche" in north_star
    assert (
        "Help engineers catch LLM integration regressions before shipping a change."
        in north_star
    )
    assert "**Last reviewed:** 2026-08-31 · **As of:** v2.10.0" in when_to_use
    assert "**Last reviewed:** 2026-08-30 · **As of:** v2.7.5" in decisions
    for decision in (
        "Local-first execution",
        "Standard-library runtime",
        "Three-state decisions",
        "Human approval for spend and promotion",
        "Typed-decision models stay out of text preflight",
    ):
        assert decision in decisions
    assert (
        'description = "The pre-merge check for LLM model, prompt, schema, and provider changes"'
        in metadata
    )


def test_project_map_indexes_distribution_assets():
    project_map = (ROOT / "docs/PROJECT_MAP.md").read_text()

    assert "**Last reviewed:** 2026-09-09 · **As of:** v2.14.0" in project_map
    assert "CI workflows and safe issue forms" in project_map
    assert "llm_preflight/images.py" in project_map
    assert "action.yml" in project_map
    assert "server.json" in project_map
    assert "plugins/llm-preflight/" in project_map


def test_local_markdown_links_resolve_after_docs_reorganization():
    for page in (ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))):
        for target in re.findall(r"\]\(([^)]+)\)", page.read_text()):
            target = target.split("#", 1)[0]
            if not target or "://" in target:
                continue
            assert (page.parent / target).is_file(), f"{page}: {target}"


def test_configuration_reference_documents_fixtures_at_both_levels():
    configuration = (ROOT / "docs/reference/configuration.md").read_text()
    contracts_guide = (ROOT / "docs/guides/output-contracts.md").read_text()
    cli_reference = (ROOT / "docs/reference/cli.md").read_text()

    assert "## Contract fixtures" in configuration
    assert "same level as the `validation`" in configuration
    assert "inside that prompt" in configuration
    assert "inside the prompt" in contracts_guide
    assert "top level or inside a custom prompt" in cli_reference


def test_custom_contract_examples_prove_their_fixtures_without_a_provider():
    for name in ("ticket-extraction", "intent-routing", "content-rule"):
        config = ROOT / f"examples/custom-contracts/{name}.json"
        prompt = json.loads(config.read_text())["prompts"][0]
        expectations = {fixture["expect"] for fixture in prompt["validation_fixtures"]}
        assert expectations == {"pass", "fail"}, name
        for flags in (["--contract-check"], ["--no-save"]):
            result = subprocess.run(
                [sys.executable, "-m", "llm_preflight", str(config), *flags],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            expected = 0 if flags == ["--contract-check"] else 3
            assert result.returncode == expected, (
                name,
                flags,
                result.stderr,
                result.stdout,
            )


def test_project_integration_guide_keeps_the_user_register():
    guide = (ROOT / "docs/getting-started/project-integration.md").read_text()

    for internal in ("pilot adoption", "team friction", "owner decision"):
        assert internal not in guide


def test_retirements_guide_documents_the_verdict_and_its_upkeep():
    guide = (ROOT / "docs/guides/retirements.md").read_text()
    readme = (ROOT / "README.md").read_text()
    docs_index = (ROOT / "docs/index.md").read_text()
    cli_reference = (ROOT / "docs/reference/cli.md").read_text()
    feature_map = (ROOT / "docs/FEATURE_MAP.md").read_text()
    agent_validation = (ROOT / "docs/automation/agent-validation.md").read_text()
    changelog = (ROOT / "CHANGELOG.md").read_text()

    assert "**Last reviewed:** 2026-10-10 · **As of:** v2.20.0" in guide
    for status in ("`retired`", "`retiring`", "`stale`", "`active`", "`unknown`"):
        assert status in guide
    assert "30 days" in guide
    assert "provider-stated" in guide
    assert "## Release retirement review" in guide
    assert "platform.claude.com/docs/en/about-claude/model-deprecations" in guide
    assert "developers.openai.com/api/docs/deprecations" in guide
    assert "guides/retirements.md" in docs_index
    assert "llm-preflight --audit-source ." in readme
    assert readme.index("--audit-source .") < readme.index("llm-preflight init")
    assert "docs/guides/retirements.md" in readme
    assert (
        "retirement" in cli_reference.split("`--audit-source PATH`")[1].split("\n")[0]
    )
    assert "3 retiring or stale" in cli_reference.split("| `--ci` |")[1].split("\n")[0]
    assert "retirement" in cli_reference.split("| `--doctor` |")[1].split("\n")[0]
    assert "retirement" in cli_reference.split("| `--dry-run` |")[1].split("\n")[0]
    assert "**Last reviewed:** 2026-10-10 · **As of:** v2.20.0" in feature_map
    assert "retirement snapshot" in feature_map
    assert "`retirement`" in agent_validation
    assert "## 2.20.0" in changelog or "## Unreleased" in changelog
    assert "retirement" in changelog.split("## 2.19.1")[0]
