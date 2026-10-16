import json
import os
import re
import subprocess
import sys
import textwrap
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
    assert 'package-version: "2.21.2"' in workflow
    assert "run-paid" not in workflow


def test_marketplace_action_installs_the_latest_published_package():
    action = (ROOT / "action.yml").read_text()

    assert 'default: "2.21.2"' in action
    assert 'python -m pip install "llm-preflight==${version}"' in action
    assert "sleep 20" in action


def test_marketplace_action_passes_package_version_through_environment():
    action = (ROOT / "action.yml").read_text()
    install_step = action.split("name: Install LLM Preflight", 1)[1].split(
        "    - name:", 1
    )[0]

    assert "PACKAGE_VERSION: ${{ inputs.package-version }}" in install_step
    script = install_step.split("run: |", 1)[1]
    assert "${{ inputs.package-version }}" not in script
    assert 'version="$PACKAGE_VERSION"' in script


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


def test_testpypi_install_wait_tolerates_propagation_and_stops_at_its_bound(tmp_path):
    workflow = (ROOT / ".github/workflows/testpypi.yml").read_text()
    install = workflow.split(
        "name: Wait for TestPyPI and install the published package", 1
    )[1]
    script = textwrap.dedent(
        install.split("run: |\n", 1)[1].split("      - name:", 1)[0]
    )
    bin_dir = tmp_path / ".testpypi-venv/bin"
    bin_dir.mkdir(parents=True)
    pip = bin_dir / "pip"
    pip.write_text(
        "#!/bin/bash\n"
        'count=0; test ! -f "$COUNTER" || read -r count < "$COUNTER"\n'
        'count=$((count + 1)); echo "$count" > "$COUNTER"\n'
        'test "$count" -eq "$SUCCEED_ON"\n'
    )
    pip.chmod(0o755)
    sleep = bin_dir / "sleep"
    sleep.write_text('#!/bin/bash\necho "$1" >> "$SLEEPS"\n')
    sleep.chmod(0o755)
    for success_on, attempts, expected in ((1, 1, 0), (36, 36, 0), (0, 40, 1)):
        counter = tmp_path / f"count-{success_on}"
        sleeps = tmp_path / f"sleeps-{success_on}"
        result = subprocess.run(
            ["bash", "-e", "-c", script],
            cwd=tmp_path,
            capture_output=True,
            env={
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "COUNTER": str(counter),
                "SLEEPS": str(sleeps),
                "SUCCEED_ON": str(success_on),
                "VERSION": "2.21.2",
            },
            timeout=5,
            check=False,
        )
        assert result.returncode == expected, result.stderr
        assert int(counter.read_text()) == attempts
        waits = sleeps.read_text().splitlines() if sleeps.exists() else []
        assert waits == ["15"] * (attempts - 1)


def _action_step(action, name):
    """The YAML of one composite step, from its name to the next step."""
    return action.split(f"- name: {name}\n", 1)[1].split("\n    - ", 1)[0] + "\n"


def _action_script(action, name):
    return textwrap.dedent(_action_step(action, name).split("run: |\n", 1)[1])


def test_action_proof_of_preflight_inputs_are_off_by_default():
    action = (ROOT / "action.yml").read_text()
    inputs = action.split("inputs:\n", 1)[1].split("\nruns:", 1)[0]

    for name in ("attest", "sign"):
        block = re.search(rf"^  {name}:\n((?:    .*\n)+)", inputs, re.MULTILINE)
        assert block is not None, name
        assert '    required: false\n    default: "false"\n' in block.group(1)
    check = _action_step(action, "Check proof-of-preflight inputs")
    assert "if: ${{ inputs.attest == 'true' || inputs.sign == 'true' }}" in check
    assert action.index("Check proof-of-preflight inputs") < action.index(
        "Install LLM Preflight"
    )
    upload = _action_step(action, "Upload the preflight record")
    link = _action_step(action, "Link the preflight record in the job summary")
    sign = _action_step(action, "Sign the preflight record")
    assert "if: ${{ !cancelled() && steps.paid.outputs.record != '' }}" in upload
    assert "steps.record.outputs.artifact-url != ''" in link
    assert "inputs.sign == 'true' && steps.paid.outputs.predicate != ''" in sign
    paid = _action_step(action, "Run explicitly authorized paid smoke")
    assert "id: paid" in paid
    for script_name in (
        "Check proof-of-preflight inputs",
        "Run explicitly authorized paid smoke",
        "Link the preflight record in the job summary",
    ):
        script = _action_script(action, script_name)
        assert "${{" not in script, script_name


def test_action_pins_the_upload_and_signing_actions_and_the_predicate_type():
    action = (ROOT / "action.yml").read_text()
    upload = _action_step(action, "Upload the preflight record")
    sign = _action_step(action, "Sign the preflight record")

    assert (
        "uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4"
        in upload
    )
    assert "name: llm-preflight-record" in upload
    assert "path: ${{ steps.paid.outputs.record-dir }}" in upload
    assert "uses: actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4" in sign
    assert "subject-path: ${{ steps.paid.outputs.record }}" in sign
    assert "predicate-type: https://in-toto.io/attestation/test-result/v0.1" in sign
    assert "predicate-path: ${{ steps.paid.outputs.predicate }}" in sign
    sign_input = action.split("  sign:\n", 1)[1].split("\n  run", 1)[0]
    assert "id-token: write" in sign_input and "attestations: write" in sign_input


def _run_action_script(tmp_path, script, **variables):
    """Run an action script against the mock starter, with llm-preflight from source."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    command = bin_dir / "llm-preflight"
    command.write_text(
        f'#!/bin/bash\nPYTHONPATH="{ROOT}" exec "{sys.executable}" -m llm_preflight "$@"\n'
    )
    command.chmod(0o755)
    python = bin_dir / "python"
    if not python.exists():
        python.symlink_to(sys.executable)
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    config = workspace / "benchmark.json"
    config.write_text((ROOT / "examples/starter/mock-benchmark.json").read_text())
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir(exist_ok=True)
    files = {name: tmp_path / name for name in ("summary.md", "output.txt")}
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GITHUB_", "RUNNER_"))
    }
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=workspace,
        capture_output=True,
        text=True,
        env={
            **environment,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "CONFIG": "benchmark.json",
            "ENV_FILE": "",
            "GITHUB_ACTION_PATH": str(ROOT),
            "GITHUB_STEP_SUMMARY": str(files["summary.md"]),
            "GITHUB_OUTPUT": str(files["output.txt"]),
            "RUNNER_TEMP": str(runner_temp),
            **variables,
        },
        timeout=60,
        check=False,
    )
    outputs = dict(
        line.split("=", 1)
        for line in (
            files["output.txt"].read_text().splitlines()
            if files["output.txt"].exists()
            else []
        )
    )
    return result, outputs, runner_temp


def test_action_paid_smoke_with_attest_off_writes_no_record(tmp_path):
    action = (ROOT / "action.yml").read_text()
    script = _action_script(action, "Run explicitly authorized paid smoke")

    result, outputs, runner_temp = _run_action_script(
        tmp_path, script, ATTEST="false", SIGN="false"
    )

    assert result.returncode == 3, result.stderr  # the mock run is inconclusive
    assert outputs == {}
    assert list(runner_temp.iterdir()) == []
    assert "## LLM Preflight" in (tmp_path / "summary.md").read_text()


def test_action_paid_smoke_with_attest_writes_the_record_card_and_predicate(tmp_path):
    action = (ROOT / "action.yml").read_text()
    script = _action_script(action, "Run explicitly authorized paid smoke")

    result, outputs, runner_temp = _run_action_script(
        tmp_path, script, ATTEST="true", SIGN="true"
    )

    assert result.returncode == 3, result.stderr  # the run's exit code is kept
    record_dir = runner_temp / "llm-preflight-record"
    assert outputs["record-dir"] == str(record_dir)
    assert sorted(path.name for path in record_dir.iterdir()) == [
        "llm-preflight-card.svg",
        "llm-preflight-result.preflight.json",
    ]
    record = json.loads(Path(outputs["record"]).read_text())
    assert record["predicate"]["result"] == "WARNED"
    assert [subject["name"] for subject in record["subject"]] == [
        "benchmark.json",
        "llm-preflight-result.json",
    ]
    assert json.loads(Path(outputs["predicate"]).read_text()) == record["predicate"]
    assert not Path(outputs["predicate"]).is_relative_to(record_dir)
    card = (record_dir / "llm-preflight-card.svg").read_text()
    assert ">INCONCLUSIVE<" in card
    assert "llm-preflight verify llm-preflight-result.preflight.json" in card


def test_action_attest_without_signing_writes_no_predicate(tmp_path):
    action = (ROOT / "action.yml").read_text()
    script = _action_script(action, "Run explicitly authorized paid smoke")

    _, outputs, _ = _run_action_script(tmp_path, script, ATTEST="true", SIGN="false")

    assert set(outputs) == {"record", "record-dir"}


def test_action_refuses_sign_without_attest_and_attest_without_a_paid_run(tmp_path):
    action = (ROOT / "action.yml").read_text()
    script = _action_script(action, "Check proof-of-preflight inputs")

    def check(**variables):
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, **variables},
            timeout=5,
            check=False,
        )
        return result.returncode, result.stderr

    assert check(RUN_PAID="true", ATTEST="true") == (0, "")
    code, err = check(RUN_PAID="false", ATTEST="true")
    assert code == 1 and 'run-paid: "true"' in err
    code, err = check(RUN_PAID="true", ATTEST="false")
    assert code == 1 and 'attest: "true"' in err
