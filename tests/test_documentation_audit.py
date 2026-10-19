"""Executable documentation checks for setup and copyable examples."""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_output_contract_json_examples_parse_without_manual_repair():
    text = (ROOT / "docs/guides/output-contracts.md").read_text()
    for block in re.findall(r"```json\n(.*?)\n```", text, re.DOTALL):
        assert isinstance(json.loads(block), dict)


@pytest.mark.parametrize(
    "page",
    ["docs/automation/change-plans.md", "docs/automation/coding-agents.md"],
)
def test_documented_receipt_can_be_written_and_verified_today(page, tmp_path):
    from llm_preflight.cli import _starter_config

    (tmp_path / "benchmark.json").write_text(json.dumps(_starter_config()))
    blocks = re.findall(r"```bash\n(.*?)\n```", (ROOT / page).read_text(), re.DOTALL)
    selected = [
        block
        for block in blocks
        if "--approval-receipt " in block or "--verify-approval-receipt " in block
    ]
    assert selected
    assert "--approval-receipt " in "\n".join(selected)
    assert "--verify-approval-receipt " in "\n".join(selected)
    env = {
        "PATH": str(Path(sys.executable).parent) + os.pathsep + "/usr/bin:/bin",
        "PYTHONPATH": str(ROOT),
    }
    for block in selected:
        command = block.replace(
            "llm-preflight ", shlex.quote(sys.executable) + " -m llm_preflight "
        )
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert list((tmp_path / ".llm-preflight/approvals").glob("*.json"))


def test_documented_workflows_pin_third_party_actions():
    for page in (ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))):
        if "product-thesis-" in str(page):
            continue
        for block in re.findall(r"```ya?ml\n(.*?)\n```", page.read_text(), re.DOTALL):
            for reference in re.findall(r"uses:\s*([\w.-]+/[\w./-]+@[^\s]+)", block):
                if reference.startswith("feronovak/"):
                    continue
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference), (page, reference)


def test_generic_live_model_example_does_not_invent_free_usage(tmp_path):
    page = (ROOT / "docs/reference/configuration.md").read_text()
    model = json.loads(re.search(r"```json\n(.*?)\n```", page, re.DOTALL).group(1))
    config = tmp_path / "generic.json"
    config.write_text(json.dumps({"prompt": "Reply with ok.", "models": [model]}))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_preflight",
            str(config),
            "--dry-run",
            "--json",
            "--no-env-file",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads(result.stdout)
    assert plan["estimated_cost_usd"] is None
    assert plan["maximum_estimated_cost_usd"] is None
    assert plan["pricing_coverage"]["models"][0]["status"] == "unknown"


def test_troubleshooting_help_commands_work():
    page = (ROOT / "docs/operations/troubleshooting.md").read_text()
    commands = re.findall(r"^llm-preflight (.*--help.*)$", page, re.MULTILINE)
    assert commands
    for command in commands:
        result = subprocess.run(
            [sys.executable, "-m", "llm_preflight", *shlex.split(command)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
