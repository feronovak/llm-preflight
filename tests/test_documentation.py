import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_current_snapshots_doc_lists_every_official_pricing_id():
    from llm_preflight.pricing import PUBLIC_PRICING

    page = (ROOT / "docs/guides/current-snapshots.md").read_text()

    assert "**Last reviewed:** 2026-10-15 · **As of:** unreleased source" in page
    assert "Package version: **2.21.2**" in page
    assert "not a ranking" in page
    assert "Gemini 4" in page
    assert "no live Gemini 4 result has been measured" not in page
    assert "16/16" in page and "observed-model-comparison.md" in page
    for model, rates in (
        ("qwen3.8-max", "2.00 | 6.00"),
        ("qwen3.8-flash", "0.15 | 0.47"),
    ):
        assert f"| `qwen` | `{model}` | {rates} | 2026-10-15 |" in page
    assert "Model Studio" in page and "account console" in page
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
    study = (ROOT / "docs/guides/observed-model-comparison.md").read_text()
    fresh = json.loads(
        (ROOT / "docs/data/model-comparison-2026-10-14.json").read_text()
    )
    historical = study.split("## Comparison results", 1)[1].split("\n## ", 1)[0]
    historical_rows = re.findall(
        r"^\| ([^|]+) \| `([^`]+)` \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$",
        historical,
        re.MULTILINE,
    )
    assert len(historical_rows) == 27
    names = {
        "gpt-6-astra": "GPT-6 Astra",
        "gpt-6.1-sol": "GPT-6.1 Sol",
        "gpt-6-luna": "GPT-6 Luna",
        "claude-opus-5-5": "Claude Opus 5.5",
        "claude-sonnet-5-5": "Claude Sonnet 5.5",
        "claude-haiku-5-5": "Claude Haiku 5.5",
        "gemini-4-argon": "Gemini 4 Argon",
        "gemini-3.8-flash": "Gemini 3.8 Flash",
        "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite",
        "z-ai/glm-5.3": "GLM 5.3",
        "z-ai/glm-5.3-flash": "GLM 5.3 Flash",
        "deepseek/deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
        "qwen/qwen3.8-max-0902": "Qwen 3.8 Max 0902",
        "qwen/qwen3.8-flash": "Qwen 3.8 Flash",
    }
    expected = {}
    for row in fresh["rows"]:
        expected[names[row["model"]]] = (
            f"{row['valid']}/16" if row["api_successful"] else "Request rejected",
            f"{row['mean_latency_seconds']:.3f}s"
            if row["mean_latency_seconds"] is not None
            else "—",
            f"${row['estimated_cost_usd']:.6f}"
            if row["estimated_cost_usd"] is not None
            else "—",
            row["observed_on"],
            row["route"],
        )
    for historical_model in ("gpt-6-astra", "gemini-3.1-flash-lite"):
        provider, model, date, valid, latency, cost = next(
            row for row in historical_rows if row[1] == historical_model
        )
        expected[names[model]] = (f"{valid}/16", latency, cost, date, provider)
    sections = []
    for page in (readme, docs_index):
        section = page.split("## Tested models\n", 1)[1].split("\n## ", 1)[0]
        sections.append(section)
        table = [line for line in section.splitlines() if line.startswith("|")]
        assert table[0] == (
            "| Model | Checks passed | Mean latency | Est. cost / 16 | Last tested | Connection |"
        )
        rows = [
            tuple(cell.strip() for cell in line.split("|")[1:-1]) for line in table[2:]
        ]
        assert len(rows) == len(expected) == 14
        assert {row[0] for row in rows} == set(expected)
        for name, *values in rows:
            assert tuple(values) == expected[name], name
        for provider in ("OpenAI", "Anthropic", "Gemini"):
            assert sum(row[-1] == provider for row in rows) >= 3, provider
        for row in rows:
            if row[0].startswith(("GLM", "DeepSeek", "Qwen")):
                assert row[-1].startswith("OpenRouter /"), row[0]
        qwen_max = next(row for row in rows if row[0] == "Qwen 3.8 Max 0902")
        assert qwen_max[1:4] == ("Request rejected", "—", "—")
        prose = [
            line
            for line in section.splitlines()
            if line.strip() and not line.startswith("|")
        ]
        assert len(prose) == 1
        assert (
            "[Test details]" in prose[0] and "observed-model-comparison.md" in prose[0]
        )
        assert len(section.splitlines()) <= 21
        assert "Current passing shortlist" not in page
        assert "Earlier evidence stays visible" not in page
    assert sections[0].split("\n\n[", 1)[0] == sections[1].split("\n\n[", 1)[0]
    for detail in (
        "password-reset",
        "5/6",
        "14/16",
        "cache-write",
        "32,768",
        "512",
        "reasoning.enabled: false",
        "passing response text was discarded",
    ):
        assert detail in study
    assert "| `claude-haiku-5-5` | 16/16 | 53/53 | 5/6 | $0.0014602 |" in study
    assert "| `claude-sonnet-5-5` | 16/16 | 53/53 | 6/6 | $0.0221540 |" in study


def test_current_comparison_aggregates_keep_the_approved_case_contract():
    data = json.loads((ROOT / "docs/data/model-comparison-2026-10-14.json").read_text())
    study = (ROOT / "docs/guides/observed-model-comparison.md").read_text()
    current_method = study.split("## 2026-10-14 bounded comparison", 1)[1].split(
        "## Historical method", 1
    )[0]
    assert "cache-hit rates" in current_method
    assert "or cache discounts" not in current_method
    for row in data["rows"]:
        if row["cached_input_tokens"]:
            assert str(row["cached_input_tokens"]) in current_method
    original = json.loads((ROOT / "examples/anthropic-5.5-comparison.json").read_text())
    case_hash = hashlib.sha256(
        json.dumps(original["prompts"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert data["method"]["case_set_sha256"] == case_hash
    assert data["method"]["case_source"] == "examples/anthropic-5.5-comparison.json"
    assert data["method"]["suite_repetitions"] == 2
    assert data["method"]["warmups"] == 0
    assert data["method"]["concurrency"] == 1
    assert len(data["rows"]) == 12
    assert sum(row["requests"] for row in data["rows"]) == 192
    assert sum(row["configured_cap_usd"] for row in data["rows"]) <= 5.73
    for row in data["rows"]:
        assert row["requests"] == 16
        assert row["retry_count"] == 0
        assert row["api_successful"] + row["api_failures"] == row["requests"]
        assert row["valid"] + row["contract_failures"] == row["api_successful"]
        if row["decision"] == "pass":
            assert row["valid"] == 16 and row["cost_coverage"]["known_requests"] == 16
        assert re.fullmatch(r"[0-9a-f]{64}", row["result_sha256"])
        request = row["request"]
        assert request["retry"]["max_attempts"] == 1
        assert request["max_output_tokens"] == (
            32768 if row["model"] == "gemini-4-argon" else 512
        )
        if row["provider"] == "openrouter":
            route = request["provider_options"]["openrouter"]["provider"]
            assert route["allow_fallbacks"] is False
            assert route["only"] == (
                ["alibaba/us-east-1"]
                if row["model"].startswith("qwen/")
                else ["relace"]
            )
    for key in (
        "requests",
        "api_successful",
        "valid",
        "api_failures",
        "contract_failures",
        "retry_count",
    ):
        assert data["totals"][key] == sum(row[key] for row in data["rows"])
    if all(row["estimated_cost_usd"] is not None for row in data["rows"]):
        assert math.isclose(
            data["totals"]["estimated_cost_usd"],
            sum(row["estimated_cost_usd"] for row in data["rows"]),
        )
    else:
        assert data["totals"]["estimated_cost_usd"] is None
    assert math.isclose(
        data["totals"]["known_cost_subtotal_usd"],
        sum(row["known_cost_subtotal_usd"] or 0 for row in data["rows"]),
    )
    for row in data["rows"]:
        if row["api_successful"] == 0:
            assert row["mean_latency_seconds"] is None
            assert row["estimated_cost_usd"] is None
    serialized = json.dumps(data)
    for private_marker in (
        "/home/",
        "scratchpad/",
        '"response":',
        '"user_id":',
        '"api_key":',
    ):
        assert private_marker not in serialized


def test_comparison_reconstruction_preserves_an_existing_config(tmp_path):
    guide = (ROOT / "docs/guides/observed-model-comparison.md").read_text()
    snippet = re.search(r"python3 - <<'PYCODE'\n(.*?)\nPYCODE", guide, re.DOTALL)
    assert snippet is not None
    for relative in (
        "docs/data/model-comparison-2026-10-14.json",
        "examples/anthropic-5.5-comparison.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    generated = subprocess.run(
        [sys.executable, "-c", snippet.group(1)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr
    config = tmp_path / "comparison.json"
    assert json.loads(config.read_text())["models"] == [
        {"provider": "gemini", "model": "gemini-4-argon"}
    ]
    config.write_text('{"name":"existing application contract"}\n')
    repeated = subprocess.run(
        [sys.executable, "-c", snippet.group(1)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert repeated.returncode != 0
    assert "FileExistsError" in repeated.stderr
    assert json.loads(config.read_text()) == {"name": "existing application contract"}


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
    assert "**Last reviewed:** 2026-10-13 · **As of:** v2.21.0" in feature_map
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


def test_mcp_guide_says_validate_config_does_not_evaluate_fixtures():
    guide = " ".join((ROOT / "docs/automation/mcp.md").read_text().split())
    row = guide.split("| `validate_config` |")[1].split("| `dry_run_plan` |")[0]

    assert "does not evaluate `validation_fixtures`" in row
    assert "CLI `--contract-check`" in row
    assert "`run_preflight` refuses a config whose fixtures fail" in row


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
        "Release notes for every version are in the [changelog]"
        "(https://github.com/feronovak/llm-preflight/blob/main/CHANGELOG.md)." in readme
    )
    assert "## Common jobs" in readme
    assert "catalog prepare benchmarks/watch.json" in readme
    assert "## Safety boundary" in readme
    assert "llm-preflight==2.21.2" in workflow
    assert "starter workflow pins the latest published package, 2.21.2" in ci
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
    live_section = readme.split("## First live run", 1)[1].split("\n## ", 1)[0]
    assert "llm-preflight init live.json --template provider" in live_section
    assert "cp benchmark.example.json" not in live_section
    assert live_section.index("--pricing-check") < live_section.index("--dry-run")
    assert "six requests per model" in readme
    assert "Version 2." not in readme


def test_readme_provider_starter_has_runnable_local_contract_fixtures(tmp_path):
    readme = (ROOT / "README.md").read_text()
    section = readme.split("## First live run", 1)[1].split("\n## ", 1)[0]
    fixture_block = re.search(r"```json\n(.*?)\n```", section, re.DOTALL)
    assert fixture_block is not None, (
        "Starter contract-check needs explicit local fixtures"
    )
    config = tmp_path / "live.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_preflight",
            "init",
            str(config),
            "--template",
            "provider",
            "--provider",
            "openai",
            "--model",
            "gpt-6.1-sol",
            "--api-key-env",
            "OPENAI_API_KEY",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    data = json.loads(config.read_text())
    data.update(json.loads(fixture_block.group(1)))
    config.write_text(json.dumps(data))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_preflight",
            str(config),
            "--contract-check",
            "--no-env-file",
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert {f["expect"] for f in data["validation_fixtures"]} == {"pass", "fail"}


def test_marketplace_action_writes_no_spend_and_paid_github_summaries():
    action = (ROOT / "action.yml").read_text()

    assert 'default: "2.21.2"' in action
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
        "**Last reviewed:** 2026-10-14 · **As of:** v2.21.2"
        in (ROOT / "docs/automation/ci.md").read_text()
    )

    for page in (ROOT / "docs/guides/model-catalog.md",):
        assert "**Last reviewed:** 2026-10-09 · **As of:** v2.19.2" in page.read_text()

    for page in (ROOT / "docs/reference/results.md",):
        assert "**Last reviewed:** 2026-10-09 · **As of:** v2.19.2" in page.read_text()

    for page in (ROOT / "docs/automation/change-plans.md",):
        assert "**Last reviewed:** 2026-09-04 · **As of:** v2.12.0" in page.read_text()

    coding_agents = (ROOT / "docs/automation/coding-agents.md").read_text()
    assert "**Last reviewed:** 2026-10-13 · **As of:** v2.21.0" in coding_agents
    for step in coding_agents.split("## ")[1:]:
        if "Run `--doctor`, `--pricing-check`, and `--dry-run`" in step:
            assert "`retirements` decision" in step

    assert (
        "**Last reviewed:** 2026-10-13 · **As of:** v2.21.0"
        in (ROOT / "docs/reference/cli.md").read_text()
    )

    for page in (ROOT / "docs/automation/mcp.md",):
        assert "**Last reviewed:** 2026-10-14 · **As of:** v2.21.2" in page.read_text()

    for page in (ROOT / "docs/reference/configuration.md",):
        assert "**Last reviewed:** 2026-10-09 · **As of:** v2.19.2" in page.read_text()

    assert (
        "**Last reviewed:** 2026-10-13 · **As of:** v2.21.0"
        in (ROOT / "docs/guides/pricing-and-safety.md").read_text()
    )

    assert (
        "**Last reviewed:** 2026-10-15 · **As of:** v2.21.2"
        in (ROOT / "docs/index.md").read_text()
    )
    assert (
        "**Last reviewed:** 2026-10-15 · **As of:** v2.21.2"
        in (ROOT / "README.md").read_text()
    )
    assert (
        "**Last reviewed:** 2026-10-13 · **As of:** v2.21.0"
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

    assert "**Last reviewed:** 2026-10-14 · **As of:** v2.21.2" in action_guide
    assert 'package-version: "2.21.2"' in action_guide
    assert "source defaults to `2.21.2`" in action_guide
    assert "`v2.21.2` release tag retains the `2.21.1`" in action_guide
    assert "latest published package (`2.21.2`)" in action_guide
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
    assert "**Last reviewed:** 2026-10-14 · **As of:** v2.21.1" in decisions
    for decision in (
        "Local-first execution",
        "Standard-library runtime",
        "Three-state decisions",
        "Human approval for spend and promotion",
        "Typed-decision models stay out of text preflight",
        "Independent, probe-based build ratings",
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

    assert "**Last reviewed:** 2026-10-16 · **As of:** unreleased source" in guide
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
    assert "**Last reviewed:** 2026-10-13 · **As of:** v2.21.0" in feature_map
    assert "retirement snapshot" in feature_map
    assert "`retirement`" in agent_validation
    validation_text = " ".join(agent_validation.split())
    assert "Report the dry-run `retirements` decision" in validation_text
    assert "`fail` means a selected model is retired" in validation_text
    assert (
        "`inconclusive` means one is retiring or its snapshot row is stale"
        in validation_text
    )
    assert "## 2.20.1" in changelog
    assert "retirement" in changelog.split("## 2.19.1")[0]


def test_stale_cliff_wording_spares_retired_models_and_names_the_date():
    guide = " ".join((ROOT / "docs/guides/retirements.md").read_text().split())
    changelog = " ".join((ROOT / "CHANGELOG.md").read_text().split())

    assert "returns 3 for every non-retired model in the snapshot" in guide
    assert "retired stays 1" in guide
    assert "stale from the 31st day after the review date stamped above" in guide
    assert "returns 3 for every non-retired model in the snapshot" in changelog
    assert "2026-11-09" in changelog


def test_readme_links_the_retirement_guide_by_absolute_url():
    readme = (ROOT / "README.md").read_text()

    assert (
        "(https://github.com/feronovak/llm-preflight/blob/main/docs/guides/retirements.md)"
        in readme
    )
    assert "(docs/guides/retirements.md)" not in readme


def test_readme_links_only_absolute_urls_or_anchors_for_the_pypi_page():
    readme = (ROOT / "README.md").read_text()
    targets = re.findall(r"\]\(([^)\s]+)", readme)
    targets += re.findall(r"^\[[^\]]+\]:\s*(\S+)", readme, re.MULTILINE)
    targets += re.findall(r"(?:href|src)=[\"']([^\"']+)", readme)

    assert len(targets) > 40
    relative = [
        target for target in targets if not target.startswith(("https://", "#"))
    ]
    assert relative == []


def test_build_rating_requires_an_independent_rater_and_named_probes():
    rubric = (ROOT / "docs/development/build-rating.md").read_text()

    assert "Current rubric: `build-rating-3`" in rubric
    assert "Rubric: build-rating-3" in rubric
    assert "**Independent rater.**" in rubric
    assert "**Name the probe.**" in rubric
    assert "make release-freshness" in rubric
    assert "#independent-probe-based-build-ratings" in rubric


def test_build_rating_defines_expiry_gate_five_and_the_verdict_split():
    rubric = " ".join((ROOT / "docs/development/build-rating.md").read_text().split())

    assert (
        "on the day after each distinct expiry date of the bundled snapshots "
        "(a snapshot row is stale once its age exceeds the 30-day window, i.e. "
        "from the 31st day after its `as_of` date, and the release gate and docs "
        "use that date;" in rubric
    )
    assert (
        "For a build that is not the intended release tag, mark this gate "
        "`not_due` and publication readiness `not_assessed`; for the intended "
        "tag, assess it before tagging and again after publication." in rubric
    )
    assert "For an unpublished build, mark this gate" not in rubric
    assert (
        "Gates 1–4 decide the build verdict and gate 5 decides publication "
        "readiness; a failed gate makes its verdict **blocked** regardless of "
        "total, and an unverified required gate makes it **unverified**, not "
        "ready." in rubric
    )


def test_changelog_names_the_receipts_a_changed_plan_shape_invalidates():
    changelog = " ".join((ROOT / "CHANGELOG.md").read_text().split())
    section = changelog.split("## 2.20.1")[1].split("## 2.20.0")[0]

    assert "now verify as `mismatch` (exit 1)" in section
    assert "re-approve" in section
    assert "`profiles` key" in section
    assert "give it no `next_command`" in section
    assert (
        "keeps hashing the same plan" not in (ROOT / "llm_preflight/cli.py").read_text()
    )


def test_agent_validation_report_list_includes_the_retirement_decision():
    guide = (ROOT / "docs/automation/agent-validation.md").read_text()
    allowed = " ".join(
        guide.split("An agent may:")[1].split("An agent must not:")[0].split()
    )

    assert "dry-run `retirements` decision" in allowed


def test_build_rating_revision_is_recorded_with_its_reason():
    rubric = " ".join((ROOT / "docs/development/build-rating.md").read_text().split())
    decisions = " ".join((ROOT / "docs/DECISIONS.md").read_text().split())

    assert "build-rating-3" in decisions
    assert "expiry boundaries" in decisions
    assert "publication readiness" in decisions
    assert "build-rating-2" in rubric
    assert "weights and checkpoint set are unchanged" in rubric
