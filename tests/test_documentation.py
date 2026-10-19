import ast
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

    assert "**Last reviewed:** 2026-10-16 · **As of:** v2.22.0" in page
    assert "Package version: **2.22.0**" in page
    assert "not a ranking" in page
    assert "Gemini 4" in page
    assert "no live Gemini 4 result has been measured" not in page
    assert "16/16" in page and "observed-model-comparison.md" in page
    for model, rates in (
        ("qwen3.8-max", "2.00 | 6.00"),
        ("qwen3.8-flash", "0.15 | 0.47"),
    ):
        assert f"| `qwen` | `{model}` | {rates} | 2026-10-16 |" in page
    assert "Model Studio" in page and "account console" in page
    for (provider, model_id), (_, _, as_of) in PUBLIC_PRICING.items():
        rows = [
            line
            for line in page.splitlines()
            if line.startswith(f"| `{provider}` | `{model_id}` |")
        ]
        assert len(rows) == 1 and rows[0].endswith(f"| {as_of} |"), rows


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


def test_documented_model_list_matches_comparison_evidence():
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
    import xml.etree.ElementTree as ET

    assert "docs/images/measured-models.svg" in readme
    assert "docs/guides/observed-model-comparison.md" in readme
    assert "| Model | Checks passed |" not in readme
    assert "| Model | Checks passed |" not in docs_index
    assert "observed-model-comparison.md" in docs_index
    svg = ET.fromstring((ROOT / "docs/images/measured-models.svg").read_bytes())
    ns = {"svg": "http://www.w3.org/2000/svg"}
    rows = [
        tuple("".join(cell.itertext()) for cell in row.findall("svg:text", ns))
        for row in svg.findall("svg:g[@data-model]", ns)
    ]
    assert len(rows) == len(expected) == 14
    assert {row[0] for row in rows} == set(expected)
    for name, *values in rows:
        assert tuple(values) == expected[name], name
    assert svg.find("svg:title", ns) is not None
    description = svg.find("svg:desc", ns).text
    assert "API errors" in description
    assert "unknown" in description
    assert "not a ranking" in description
    assert not svg.findall(".//svg:script", ns)
    for provider in ("OpenAI", "Anthropic", "Gemini"):
        assert sum(row[-1] == provider for row in rows) >= 3, provider
    for row in rows:
        if row[0].startswith(("GLM", "DeepSeek", "Qwen")):
            assert row[-1].startswith("OpenRouter /"), row[0]
    qwen_max = next(row for row in rows if row[0] == "Qwen 3.8 Max 0902")
    assert qwen_max[1:4] == ("Request rejected", "—", "—")
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
    assert "llm-preflight==2.22.1" in workflow
    assert "starter workflow pins the latest published package, 2.22.1" in ci
    assert "| stamped | 2026-08-30 | v2.7.5 |" in docmap


def test_readme_leads_with_a_safe_first_run_and_workflow_choices():
    readme = (ROOT / "README.md").read_text()

    assert "## Try it in 60 seconds" in readme
    assert "## Choose your path" in readme
    assert "**Configure a coding agent.**" in readme
    assert "llm-preflight-mcp --workspace" in readme
    assert "## Safety boundary" in readme
    assert "## Common jobs" in readme
    assert "No preflight, no merge." in readme
    assert "A signed record" not in readme
    assert "The pre-merge check for LLM changes." not in readme
    assert "## CLI, CI, and MCP" in readme
    assert "## Delivered in 2.8.0" not in readme
    assert "## Delivered in 2.7.5" not in readme
    assert readme.index("## Try it in 60 seconds") < readme.index("## First live run")
    assert (
        readme.index("## Try it in 60 seconds")
        < readme.index("## Observed results on a support-routing contract")
        < readme.index("## First live run")
    )
    paths = readme.split("## Choose your path", 1)[1].split("\n## ", 1)[0]
    for destination in (
        "docs/getting-started/project-integration.md",
        "docs/guides/model-change.md",
        "docs/automation/ci.md",
        "docs/automation/mcp.md",
    ):
        assert destination in paths
    assert "Version **2." not in readme
    assert "Version 2." not in readme
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

    assert 'default: "2.22.1"' in action
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
        "**Last reviewed:** 2026-10-14 · **As of:** v2.22.1"
        in (ROOT / "docs/automation/ci.md").read_text()
    )

    for page in (ROOT / "docs/guides/model-catalog.md",):
        assert "**Last reviewed:** 2026-10-09 · **As of:** v2.19.2" in page.read_text()

    for page in (ROOT / "docs/reference/results.md",):
        assert "**Last reviewed:** 2026-10-18 · **As of:** v2.22.1" in page.read_text()

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
        assert "**Last reviewed:** 2026-10-18 · **As of:** v2.22.1" in page.read_text()

    assert (
        "**Last reviewed:** 2026-10-13 · **As of:** v2.21.0"
        in (ROOT / "docs/guides/pricing-and-safety.md").read_text()
    )

    assert (
        "**Last reviewed:** 2026-10-19 · **As of:** v2.22.1"
        in (ROOT / "docs/index.md").read_text()
    )
    assert (
        "**Last reviewed:** 2026-10-19 · **As of:** v2.22.1"
        in (ROOT / "README.md").read_text()
    )
    assert (
        "**Last reviewed:** 2026-10-13 · **As of:** v2.21.0"
        in (ROOT / "docs/FEATURE_MAP.md").read_text()
    )

    safe_demo = (ROOT / "docs/getting-started/safe-demo.md").read_text()
    assert "**Last reviewed:** 2026-10-19 · **As of:** v2.22.1" in safe_demo
    assert "llm-preflight init live.json --template provider --interactive" in safe_demo
    assert safe_demo.count("**Last reviewed:**") == 1
    ci = (ROOT / "docs/automation/ci.md").read_text()
    north_star = (ROOT / "docs/NORTH_STAR.md").read_text()

    assert '"state": "inconclusive"' in safe_demo
    assert "saved JSON artifact" in " ".join(safe_demo.split())
    assert "## Release documentation checklist" in ci
    assert "examples/github-actions/preflight.yml" in ci
    assert "tests/test_package.py" in ci
    assert "statically validates a deliberately portable" in north_star


def test_marketplace_action_docs_describe_the_current_published_release():
    action_guide = (ROOT / "docs/automation/github-action.md").read_text()

    assert "**Last reviewed:** 2026-10-14 · **As of:** v2.22.1" in action_guide
    assert 'package-version: "2.22.1"' in action_guide
    assert "source defaults to `2.22.1`" in action_guide
    assert "`v2.22.1` release tag retains the `2.22.0`" in action_guide
    assert "latest published package (`2.22.1`)" in action_guide
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
    assert "docs/guides/model-catalog.md" in readme
    assert "No preflight, no merge." in readme
    assert "A signed record" not in readme
    assert (
        "It doesn't certify production behaviour. It proves the check was done."
        in readme
    )
    assert (
        "Check LLM responses against the output rules your application depends on"
        in readme
    )
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
    assert (
        "A prompt preset fills only keys left unset, under both `--prompt` and "
        "`--tests`. A prompt `provider_options` object replaces that dict; "
        "top-level presets then fill only the defaults that object left unset."
    ) in configuration
    assert (
        "A built-in test runs the same every time: its own presets expand into "
        "its own request, which replaces those keys of the run request"
    ) in configuration
    assert "presets fill the default request" not in configuration
    schema = (ROOT / "docs/reference/configuration-schema.md").read_text()
    assert (
        "| `temperature` | `0` without `request` and `presets`; otherwise "
        "provider default |"
    ) in schema
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

    assert "**Last reviewed:** 2026-10-16 · **As of:** v2.22.0" in guide
    assert "`.gitignore`" in guide and "`--all`" in guide
    assert "| `--all` | off | With `--audit-source`" in cli_reference
    results_reference = (ROOT / "docs/reference/results.md").read_text()
    assert "`file_selection`" in results_reference.split("## Source audit JSON")[1]
    assert (
        "A built-in test's presets expand into its own request, which replaces "
        "those keys of the run request"
    ) in results_reference
    assert (
        "A custom prompt's `provider_options` object replaces that dict, and "
        "top-level presets fill only the defaults the prompt left unset"
    ) in results_reference
    assert (
        "Under `--tests`, `settings.request` and the dry-run request stay the "
        "parent request after top-level presets. A profile's own request and "
        "presets are not copied into those fields. The options sent with each "
        "prompt are the per-prompt `request_sha256`. Under `--prompt`, "
        "`settings.request` and the dry-run request are that merged send."
    ) in results_reference
    for status in ("`retired`", "`retiring`", "`stale`", "`active`", "`unknown`"):
        assert status in guide
    assert "30 days" in guide
    assert "provider-stated" in guide
    assert "## Release retirement review" in guide
    assert "platform.claude.com/docs/en/about-claude/model-deprecations" in guide
    assert "developers.openai.com/api/docs/deprecations" in guide
    assert "guides/retirements.md" in docs_index
    assert "llm-preflight --audit-source ." in readme
    assert readme.index("llm-preflight init") < readme.index("## Common jobs")
    assert "llm-preflight --audit-source ." in readme.split("## Common jobs", 1)[1]
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


PROOF_OF_PREFLIGHT_PAGES = (
    "docs/guides/proof-of-preflight.md",
    "docs/automation/ci.md",
    "docs/automation/github-action.md",
    "docs/guides/reports.md",
)
HONESTY_LINE = "It doesn't certify production behaviour. It proves the check was done."
FORBIDDEN_CLAIMS = re.compile(
    r"\bcertified\b|\bcertificates?\b|\bguarantee[ds]?\b|\bcompliant\b|nutrition label",
    re.IGNORECASE,
)


def _gate_reason_codes():
    """Every reason code the gate returns, each with its decision, read from
    attestation.py itself so a new code cannot miss the guide's table.

    A code is a candidate or blocking verdict, a literal `reason_code` in a
    report (whose literal `decision` names it), or a literal the gate assigns
    to `code`; only `fresh_pass` passes.
    """
    from llm_preflight import attestation

    codes = {
        code: "blocked"
        for code in [
            *(attestation._CANDIDATE_VERDICTS - {"pass"}),
            *attestation._BLOCKING_PRIORITY,
        ]
    }
    tree = ast.parse(Path(attestation.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            fields = {
                key.value: value.value
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
            }
            if isinstance(fields.get("reason_code"), str):
                codes[fields["reason_code"]] = fields.get("decision", "blocked")
        elif isinstance(node, ast.Assign):
            for target, value in _assignments(node):
                if isinstance(target, ast.Name) and target.id == "code":
                    branches = (
                        [value.body, value.orelse]
                        if isinstance(value, ast.IfExp)
                        else [value]
                    )
                    for branch in branches:
                        if isinstance(branch, ast.Constant):
                            codes.setdefault(branch.value, "blocked")
    codes["fresh_pass"] = "pass"
    return codes


def _assignments(node):
    """(target, value) pairs, unpacking `a, b = x, y`."""
    for target in node.targets:
        if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
            yield from zip(target.elts, node.value.elts, strict=True)
        else:
            yield target, node.value


def test_proof_of_preflight_guide_explains_the_record_commands_and_reason_codes():
    from llm_preflight.cli import _GATE_EXIT_CODES

    guide = (ROOT / "docs/guides/proof-of-preflight.md").read_text()
    table = guide.split("## Gate reason codes", 1)[1].split("\n## ", 1)[0]

    assert "**Last reviewed:** 2026-10-18 · **As of:** v2.22.1" in guide
    assert HONESTY_LINE in guide
    assert "pilot signs the preflight" in guide
    for command in (
        "llm-preflight attest results/run.json",
        "llm-preflight verify results/run.preflight.json",
        "llm-preflight gate benchmark.json --repository acme/app --records records",
    ):
        assert command in guide
    rows = re.findall(r"^\| `([a-z_]+)` \| ([a-z ]+) \| (\d) \|", table, re.MULTILINE)
    expected = _gate_reason_codes()
    decisions = {"pass": "pass", "blocked": "blocked", "undecided": "cannot decide"}
    assert {code for code, _, _ in rows} == set(expected)
    assert len(rows) == len(expected)
    for code, decision, exit_code in rows:
        assert decision == decisions[expected[code]], code
        assert int(exit_code) == _GATE_EXIT_CODES[expected[code]], code
    for heading in (
        "## What a record proves",
        "## Same selection, same repository",
        "## Private and public repositories",
        "## Freshness",
        "## When the gate blocks",
    ):
        assert heading in guide
    assert "30 days" in guide and "gh attestation verify" in guide
    for flag in ("--prompt", "--tests", "--profiles", "--env", "--migration-check"):
        assert f"`{flag}" in guide, flag
    assert "`--repository OWNER/NAME`" in guide and "`GITHUB_REPOSITORY`" in guide
    assert "GitHub Enterprise Cloud" in guide


def test_record_docs_separate_the_result_and_the_sealed_evidence_digests():
    results = " ".join((ROOT / "docs/reference/results.md").read_text().split())
    guide = " ".join((ROOT / "docs/guides/proof-of-preflight.md").read_text().split())
    reports = " ".join((ROOT / "docs/guides/reports.md").read_text().split())
    configuration_row = results.split("| `predicate.configuration` |", 1)[1]
    configuration_row = configuration_row.split("| `", 1)[0]

    assert "whose `sha256` digests are the result's `provenance`" not in results
    assert (
        "`llm-preflight/contract`, `llm-preflight/routes` and "
        "`llm-preflight/pricing` digests are the result's `provenance` fingerprints"
    ) in configuration_row
    assert (
        "`selection_sha256`, `decision_state`, `blocking_warnings` and "
        "`cost_confidence`"
    ) in configuration_row
    assert "the full `provenance`" not in results
    assert "`selectionSha256`" in results
    assert "| `selection_sha256` |" in results
    assert "does not make the gate pass" not in guide
    assert "without recomputing the checksum fails integrity" in guide
    assert "does not cover `checkedAt`" in guide
    assert "Only a signature checked with `gh attestation verify`" in guide
    assert "labelled `result evidence`" in reports


def test_mcp_gate_schema_names_every_gate_reason_code():
    from llm_preflight import mcp

    tools = mcp._response(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, ROOT
    )["result"]["tools"]
    gate = next(tool for tool in tools if tool["name"] == "gate")
    schema = gate["outputSchema"]["oneOf"][1]["properties"]
    codes = _gate_reason_codes()

    assert set(schema["reason_code"]["enum"]) == set(codes)
    verdicts = schema["records"]["items"]["properties"]["verdict"]["enum"]
    assert set(verdicts) == {
        *(
            code
            for code, decision in codes.items()
            if decision == "blocked" and code != "no_record"
        ),
        "pass",
        "record_error",
    }


def test_proof_of_preflight_pages_avoid_the_forbidden_claims():
    for page in PROOF_OF_PREFLIGHT_PAGES:
        claim = FORBIDDEN_CLAIMS.search((ROOT / page).read_text())
        assert claim is None, (page, claim)


def test_proof_of_preflight_guide_is_linked_from_every_entry_point():
    readme = (ROOT / "README.md").read_text()
    index = (ROOT / "docs/index.md").read_text()
    feature_map = (ROOT / "docs/FEATURE_MAP.md").read_text()
    docmap = (ROOT / "docs/DOCMAP.md").read_text()
    gate = readme.split("## CLI, CI, and MCP", 1)[1].split("\n## ", 1)[0]
    assert "docs/guides/proof-of-preflight.md" in gate
    assert "gh attestation verify" in gate
    assert "Protect the producer and gate workflows" in gate
    assert "merge policy" in gate
    assert "synthetic" in readme.split("## Try it in 60 seconds", 1)[0].lower()
    assert "(guides/proof-of-preflight.md)" in index
    assert "`attestation.py`" in feature_map and "`report --format svg`" in feature_map
    action_row = feature_map.split("GitHub Marketplace Action", 1)[1].split("\n")[0]
    assert "`attest`" in action_row and "`sign`" in action_row
    assert "docs/guides/proof-of-preflight.md" in docmap


def test_gate_and_record_workflows_pin_every_action_and_the_package():
    ci = (ROOT / "docs/automation/ci.md").read_text()
    action_guide = (ROOT / "docs/automation/github-action.md").read_text()
    gate = ci.split("## Proof-of-preflight gate", 1)[1].split("\n## ", 1)[0]
    record = action_guide.split("## Proof of preflight", 1)[1].split("\n## ", 1)[0]

    for workflow in (gate, record):
        for reference in re.findall(r"uses: (\S+)", workflow):
            assert re.fullmatch(
                r"feronovak/llm-preflight@v2\.22\.1|[\w.-]+/[\w./-]+@[0-9a-f]{40}",
                reference,
            ), reference
    assert "on:\n  pull_request:" in gate
    assert 'python -m pip install "llm-preflight==2.22.1"' in gate
    assert "not an available package or tag yet" not in gate
    assert "not an available package or tag yet" not in record
    gate_fence = gate.split("```yaml", 1)[1].split("```", 1)[0]
    record_fence = record.split("```yaml", 1)[1].split("```", 1)[0]
    assert "2.21.2" not in gate_fence
    assert "2.21.2" not in record_fence
    assert "`v2.22.1` release tag retains the `2.22.0` default" in record
    assert "llm-preflight gate benchmark.json --smoke --records records" in gate
    assert "gh attestation verify" in gate
    assert "--predicate-type https://in-toto.io/attestation/test-result/v0.1" in gate
    assert 'attest: "true"' in record and 'sign: "true"' in record
    assert 'package-version: "2.22.1"' in record
    assert "id-token: write" in record and "attestations: write" in record
    assert HONESTY_LINE in record


def test_documented_gate_takes_records_from_main_only():
    """A branch anyone can push must never produce a record the gate accepts:
    the gate reads only runs of the record workflow on `main`, and a pull
    request is recorded by a maintainer dispatching that workflow from `main`
    against the pull request's head commit."""
    ci = (ROOT / "docs/automation/ci.md").read_text()
    action_guide = (ROOT / "docs/automation/github-action.md").read_text()
    gate = ci.split("## Proof-of-preflight gate", 1)[1].split("\n## ", 1)[0]
    record = action_guide.split("## Proof of preflight", 1)[1].split("\n## ", 1)[0]

    assert "head_ref" not in gate and "HEAD_REF" not in gate
    assert "for event in push workflow_dispatch; do" in gate
    assert '--branch main --event "$event"' in gate
    assert "--source-ref refs/heads/main" in gate
    assert (
        '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/'
        'llm-preflight-record.yml"'
    ) in gate
    assert "  workflow_dispatch:\n    inputs:\n      commit:" in record
    assert "ref: ${{ inputs.commit || github.sha }}" in record
    assert "persist-credentials: false" in record
    # The risk of a dispatched run is stated where a maintainer starts it.
    assert "base_url" in record and "api_key_env" in record


def test_report_gallery_gate_demo_blocks_without_ci_evidence(monkeypatch):
    """Execute the advertised offline gate demo, including its nonzero exit."""
    gallery = (ROOT / "examples/reports/README.md").read_text()
    section = gallery.split("## Try the merge gate without a provider", 1)[1]
    command = re.search(r"```bash\n(.*?)\n```", section, re.DOTALL).group(1)
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/app")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    result = subprocess.run(
        ["bash", "-c", command], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 1, result.stderr + result.stdout
    decision = json.loads(result.stdout)
    assert decision["decision"] == "blocked"
    assert decision["reason_code"] == "no_record"
    assert decision["records"] == []


def test_default_template_interactive_and_cli_communication_examples(tmp_path):
    import shlex

    guide = (ROOT / "docs/guides/interactive-runs.md").read_text()
    walkthrough = guide.split("## Default template walkthrough", 1)[1].split(
        "\n## ", 1
    )[0]
    communication = guide.split("## CLI JSON communication", 1)[1].split("\n## ", 1)[0]
    config_path = tmp_path / "benchmark.json"

    def execute(command, *, answers=None):
        arguments = shlex.split(command)
        assert arguments.pop(0) == "llm-preflight"
        if arguments == ["init"]:
            arguments.append(str(config_path))
        else:
            assert arguments[0] == "benchmark.json"
            arguments[0] = str(config_path)
        return subprocess.run(
            [sys.executable, "-m", "llm_preflight", *arguments],
            cwd=ROOT,
            input=answers,
            capture_output=True,
            text=True,
            check=False,
        )

    commands = (
        re.search(r"```bash\n(.*?)\n```", walkthrough, re.DOTALL).group(1).splitlines()
    )
    initialized = execute(commands[0])
    assert initialized.returncode == 0, initialized.stderr
    config = json.loads(config_path.read_text())
    assert config["prompt"] == "Reply with ok."
    assert config["validation"] == {"exact": "ok"}
    assert {model["provider"] for model in config["models"]} == {"mock"}
    interactive = execute(commands[1], answers="all\n\n\n4\nr\ny\n")
    assert interactive.returncode == 3, interactive.stdout + interactive.stderr
    assert "Tests: config prompt" in interactive.stdout
    assert "Run local mock benchmark?" in interactive.stdout
    assert "API OK / TEST OK" in interactive.stdout
    assert "Decision: inconclusive (exit 3)" in interactive.stdout

    commands = (
        re.search(r"```bash\n(.*?)\n```", communication, re.DOTALL)
        .group(1)
        .splitlines()
    )
    excerpts = [
        json.loads(block)
        for block in re.findall(r"```json\n(.*?)\n```", communication, re.DOTALL)
    ]
    assert len(commands) == len(excerpts) == 2

    def assert_excerpt(actual, expected):
        for key, value in expected.items():
            if isinstance(value, dict):
                assert_excerpt(actual[key], value)
            else:
                assert actual[key] == value

    for command, excerpt, status in zip(commands, excerpts, (0, 3), strict=True):
        result = execute(command)
        assert result.returncode == status, result.stdout + result.stderr
        assert_excerpt(json.loads(result.stdout), excerpt)


def test_readme_embeds_both_current_terminal_recordings():
    readme = (ROOT / "README.md").read_text()
    introduction = readme.split("## Observed results on a support-routing contract", 1)[
        0
    ]
    embedded = re.findall(
        r"!\[[^\]]*\]\(https://raw\.githubusercontent\.com/feronovak/"
        r"llm-preflight/main/docs/images/([^)]+)\)",
        introduction,
    )
    assert embedded == ["contract-check-session.gif", "default-template-session.gif"]
    for name in embedded:
        assert (ROOT / "docs/images" / name).read_bytes().startswith(b"GIF89a")
    assert "contract-break.svg" not in introduction
    gallery = (ROOT / "examples/reports/README.md").read_text()
    assert "../../docs/images/contract-break.svg" in gallery


def test_readme_first_run_is_the_isolated_mock_contract_demo(tmp_path):
    readme = (ROOT / "README.md").read_text()
    quickstart = readme.split("## Try it in 60 seconds", 1)[1].split("\n### ", 1)[0]
    block = re.search(r"```bash\n(.*?)\n```", quickstart, re.DOTALL)
    assert block is not None
    commands = [
        line
        for line in block.group(1).splitlines()
        if line.startswith("llm-preflight ")
    ]
    assert commands == [
        "llm-preflight init",
        "llm-preflight benchmark.json --no-save --no-env-file",
    ]
    # The no-key walkthrough must not read an existing project's env file.
    (tmp_path / ".env.production").write_text("not a valid environment assignment\n")
    for command, expected in zip(commands, (0, 3)):
        result = subprocess.run(
            [sys.executable, "-m", "llm_preflight", *command.split()[1:]],
            cwd=tmp_path,
            env={"PATH": str(Path(sys.executable).parent), "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == expected, result.stdout + result.stderr
    assert re.search(r"local-mock\s*│\s*PASS\s*│\s*-", result.stdout)
    assert "Decision: inconclusive (exit 3)" in result.stdout
    assert "Mock-only runs do not provide live-provider evidence." in result.stdout
    config = json.loads((tmp_path / "benchmark.json").read_text())
    assert config["validation"] == {"exact": "ok"}
    assert config["models"][0]["response"] == "ok"
    assert not list((tmp_path / "results").glob("*.json"))
    assert not list((tmp_path / "results").glob("*.md"))


def test_measured_model_image_is_reproducible(tmp_path):
    output = tmp_path / "models.svg"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/render_measured_models.py"),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        output.read_bytes() == (ROOT / "docs/images/measured-models.svg").read_bytes()
    )
    output.write_text("outdated image")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/render_measured_models.py"),
            "--output",
            str(output),
            "--check",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert output.read_text() == "outdated image"


def test_docs_home_routes_to_runnable_first_tasks():
    home = (ROOT / "docs/index.md").read_text()
    start = home.split("## Start here", 1)[1].split("\n## ", 1)[0]
    targets = re.findall(r"\]\(([^)]+)\)", start)
    assert set(targets) == {
        "getting-started/safe-demo.md",
        "getting-started/project-integration.md",
        "guides/model-change.md",
        "automation/ci.md",
        "automation/mcp.md",
    }
    for target in targets:
        assert (ROOT / "docs" / target).is_file()


def test_measured_image_accepts_new_native_and_routed_evidence(tmp_path):
    import xml.etree.ElementTree as ET

    source = json.loads(
        (ROOT / "docs/data/model-comparison-2026-10-14.json").read_text()
    )
    row = source["rows"][0].copy()
    row.update(
        model="deepseek-flash",
        display_name="DeepSeek Flash",
        route="DeepSeek (native)",
        observed_on="2026-10-20",
        valid=10,
        api_successful=12,
        api_failures=4,
        contract_failures=2,
        estimated_cost_usd=None,
    )
    routed = {**row, "route": "OpenRouter / Relace"}
    source.update(display_title="Native & routed <checks>", rows=[row, routed])
    data = tmp_path / "new-comparison.json"
    data.write_text(json.dumps(source))
    output = tmp_path / "new-models.svg"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/render_measured_models.py"),
            "--data",
            str(data),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    image = ET.fromstring(output.read_bytes())
    ns = {"svg": "http://www.w3.org/2000/svg"}
    rows = image.findall("svg:g[@data-model]", ns)
    assert len(rows) == 2
    cells = [[cell.text for cell in row.findall("svg:text", ns)] for row in rows]
    assert {row[-1] for row in cells} == {"DeepSeek (native)", "OpenRouter / Relace"}
    assert all(
        row[0] == "DeepSeek Flash" and row[1] == "10/16" and row[3] == "—"
        for row in cells
    )
    assert all(row[4] == "2026-10-20" for row in cells)
    assert image.find("svg:title", ns).text == "Native & routed <checks>"


def test_measured_image_refuses_a_misleading_common_cost_denominator(tmp_path):
    source = json.loads(
        (ROOT / "docs/data/model-comparison-2026-10-14.json").read_text()
    )
    source["rows"][0]["requests"] = 8
    data = tmp_path / "mixed-request-counts.json"
    data.write_text(json.dumps(source))
    output = tmp_path / "models.svg"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/render_measured_models.py"),
            "--data",
            str(data),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "same positive request count" in result.stderr
    assert not output.exists()


def test_mcp_first_plan_example_matches_the_server(tmp_path):
    from llm_preflight import mcp
    from llm_preflight.cli import _starter_config

    page = (ROOT / "docs/automation/mcp.md").read_text()
    section = page.split("## Try a local planning request", 1)[1].split("\n## ", 1)[0]
    request, excerpt = [
        json.loads(block)
        for block in re.findall(r"```json\n(.*?)\n```", section, re.DOTALL)
    ]
    (tmp_path / "benchmark.json").write_text(json.dumps(_starter_config()))
    response = mcp._response(request, tmp_path)["result"]["structuredContent"]
    assert {key: response[key] for key in excerpt} == excerpt
    assert response["ok"] is True


def test_visual_specification_covers_images_and_machine_style():
    import xml.etree.ElementTree as ET

    spec = (ROOT / "docs/development/visual-assets.md").read_text()
    for folder in ("docs/images", "tests/fixtures/cards", "examples/vision"):
        for path in (ROOT / folder).iterdir():
            if path.suffix in {".svg", ".gif", ".png", ".mp4"}:
                assert path.stem in spec, path
    style = json.loads((ROOT / "docs/images/style.json").read_text())
    image = ET.parse(ROOT / "docs/images/measured-models.svg").getroot()
    assert image.get("width") == str(style["measured_models"]["width"])
    assert image.get("font-family") == style["fonts"]["sans"]
    assert "scripts/render_measured_models.py" in spec
    assert "native" in spec and "OpenRouter" in spec


def test_measured_image_rejects_invalid_cost_evidence(tmp_path):
    source = json.loads(
        (ROOT / "docs/data/model-comparison-2026-10-14.json").read_text()
    )
    data = tmp_path / "invalid-cost.json"
    output = tmp_path / "models.svg"
    for invalid in (-0.01, float("nan"), float("inf")):
        source["rows"][0]["estimated_cost_usd"] = invalid
        data.write_text(json.dumps(source))
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/render_measured_models.py"),
                "--data",
                str(data),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        assert "finite nonnegative" in result.stderr
        assert not output.exists()
