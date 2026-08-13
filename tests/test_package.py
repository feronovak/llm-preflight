import json
import re
from pathlib import Path

from llm_preflight import __version__, cli
from llm_preflight.runner import run_benchmark


def test_package_version_is_stable_release():
    assert __version__ == "2.7.0"
    assert 'version = "2.7.0"' in Path("pyproject.toml").read_text()


def test_llm_preflight_is_the_only_console_command(monkeypatch):
    monkeypatch.setattr("sys.argv", ["llm-preflight"])
    assert cli._display_command() == "llm-preflight"

    pyproject = Path("pyproject.toml").read_text()
    assert 'name = "llm-preflight"' in pyproject
    assert 'llm-preflight = "llm_preflight.__main__:main"' in pyproject
    assert 'llm-preflight-mcp = "llm_preflight.mcp:main"' in pyproject
    assert "llm-bench" not in pyproject
    assert "llm_bench" not in pyproject


def test_preflight_has_a_public_python_module_entry_point():
    from llm_preflight.__main__ import main

    assert main is cli.main


def test_build_backend_is_pinned_for_reproducible_release_artifacts():
    pyproject = Path("pyproject.toml").read_text()

    assert 'requires = ["setuptools==83.0.0"]' in pyproject
    assert 'build-backend = "setuptools.build_meta"' in pyproject


def test_ci_and_release_workflows_install_committed_tool_locks():
    ci_workflow = Path(".github/workflows/tests.yml").read_text()
    release_workflow = Path(".github/workflows/release.yml").read_text()

    assert "python -m pip install --requirement requirements/ci.lock" in ci_workflow
    assert "python -m pip install --no-deps -e ." in ci_workflow
    assert (
        "python -m pip install --requirement requirements/release.lock"
        in release_workflow
    )


def test_setup_py_has_only_the_single_console_entry_point():
    setup = Path("setup.py").read_text()

    assert 'name="llm-preflight"' in setup
    assert 'version="2.4.3"' in setup
    assert '"llm-preflight=llm_preflight.__main__:main"' in setup
    assert '"llm-preflight-mcp=llm_preflight.mcp:main"' in setup
    assert "llm-bench" not in setup
    assert "llm_bench" not in setup


def test_example_does_not_present_unknown_model_pricing_as_free():
    example = Path("benchmark.example.json").read_text()

    assert '"input_cost_per_million": 0' not in example
    assert '"output_cost_per_million": 0' not in example


def test_custom_contract_examples_are_parseable_and_documented():
    examples = (
        "examples/custom-contracts/ticket-extraction.json",
        "examples/custom-contracts/intent-routing.json",
        "examples/custom-contracts/content-rule.json",
    )

    for example in examples:
        config = json.loads(Path(example).read_text())
        assert config["prompts"]
        assert config["models"][0]["provider"] == "mock"
        assert (
            run_benchmark(config)["models"][0]["profiles"][0]["summary"]["failed"] == 0
        )

    tutorial = Path("docs/guides/output-contracts.md").read_text()
    for example in examples:
        assert example in tutorial


def test_public_docs_make_the_catalog_lifecycle_primary():
    cli_reference = Path("docs/reference/cli.md").read_text()
    tutorial = Path("docs/guides/model-catalog.md").read_text()

    for command in (
        "catalog init",
        "catalog refresh",
        "catalog prepare",
        "catalog test",
        "models approve",
        "models remove",
        "--approve-to",
    ):
        assert command in cli_reference
        assert command in tutorial
    assert "compatibility aliases" in cli_reference
    assert "compatibility aliases" in tutorial
    assert "catalog prepare" in Path("README.md").read_text()
    assert "catalog prepare" in Path("docs/guides/model-change.md").read_text()
    assert "--approve-to" in Path("docs/guides/interactive-runs.md").read_text()
    assert "--migration-check" in Path("README.md").read_text()
    assert "--migration-check" in Path("docs/getting-started/safe-demo.md").read_text()
    assert "--migration-check" in Path("docs/reference/cli.md").read_text()
    assert Path("docs/operations/troubleshooting.md").exists()


def test_public_docs_give_beginner_and_scripted_users_clear_starting_paths():
    readme = Path("README.md").read_text()
    getting_started = Path("docs/getting-started/safe-demo.md").read_text()

    assert "## Choose your path" in readme
    for destination in (
        "docs/getting-started/safe-demo.md",
        "docs/guides/output-contracts.md",
        "docs/guides/model-catalog.md",
        "docs/automation/ci.md",
    ):
        assert destination in readme
    assert "## Choose your next path" in getting_started
    assert "custom contract test" in getting_started
    assert "CI and JSON output" in getting_started


def test_public_markdown_links_resolve_locally():
    markdown_files = (Path("README.md"), *Path("docs").rglob("*.md"))
    link_pattern = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")

    for document in markdown_files:
        for target in link_pattern.findall(document.read_text()):
            path = target.split("#", 1)[0]
            if not path or "://" in path or path.startswith("mailto:"):
                continue
            assert (document.parent / path).resolve().is_file(), (
                f"{document}: missing local documentation target {target}"
            )


def test_release_targets_only_current_version_artifacts():
    makefile = Path("Makefile").read_text()

    assert (
        'VERSION := $(shell python3 -c "from llm_preflight import __version__; print(__version__)")'
        in makefile
    )
    assert "DIST_FILES := dist/llm_preflight-$(VERSION)*" in makefile
    assert "python3 -m twine check $(DIST_FILES)" in makefile
    assert "python3 -m twine upload --repository testpypi $(DIST_FILES)" in makefile
    assert "llm_bench" not in makefile


def test_source_distribution_manifest_keeps_only_public_release_material():
    manifest = Path("MANIFEST.in").read_text()

    for included in (
        "include CHANGELOG.md",
        "include LICENSE",
        "include README.md",
        "include SECURITY.md",
        "recursive-include examples *.json",
    ):
        assert included in manifest

    for internal_path in (
        "AGENTS.md",
        "CONTRIBUTING.md",
        "LAUNCH.md",
        "Makefile",
        "RELEASING.md",
        "docs",
    ):
        assert f"include {internal_path}" not in manifest

    for excluded in ("exclude AGENTS.md", "exclude CONTRIBUTING.md", "prune docs"):
        assert excluded in manifest
    assert "legacy-pypi-shim" not in manifest


def test_first_run_starters_and_github_workflow_are_safe_and_documented():
    mock = json.loads(Path("examples/starter/mock-benchmark.json").read_text())
    assert mock["models"][0]["provider"] == "mock"
    assert mock["models"][0]["response"] == "ok"
    assert run_benchmark(mock)["models"][0]["summary"]["failed"] == 0

    pyproject = Path("pyproject.toml").read_text()
    version = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE).group(1)
    workflow = Path("examples/github-actions/preflight.yml").read_text()
    for required in (
        "pull_request:",
        "workflow_dispatch:",
        "contents: read",
        "actions/checkout@",
        "actions/setup-python@",
        "actions/upload-artifact@",
        "if: always()",
        "retention-days:",
        f"llm-preflight=={version}",
        "--doctor --json",
        "--pricing-check",
        "--smoke --dry-run --json",
        "--no-save",
        'test "$status" -eq 3',
    ):
        assert required in workflow
    assert "pull_request_target" not in workflow
    assert "contents: write" not in workflow
    assert "${{ secrets." not in workflow

    getting_started = Path("docs/getting-started/safe-demo.md").read_text()
    ci = Path("docs/automation/ci.md").read_text()
    readme = Path("README.md").read_text()
    assert "llm-preflight init" in getting_started
    assert "examples/github-actions/preflight.yml" in ci
    assert "## What is new in 2.5–2.6" in readme
    assert "**Match the deployed JSON consumer.**" in readme
    assert "**Require current pricing before paid work.**" in readme
    assert "**Give coding agents bounded access.**" not in readme


def test_pypi_trusted_publisher_isolated_to_release_workflow():
    workflow = Path(".github/workflows/release.yml").read_text()

    assert "types: [published]" in workflow
    assert "id-token: write" in workflow
    assert "actions/upload-artifact" in workflow
    assert "actions/download-artifact" in workflow
    assert "pypa/gh-action-pypi-publish@release/v1" in workflow
    assert "PYPI_API_TOKEN" not in workflow


def test_testpypi_workflow_uses_oidc_and_verifies_the_published_package():
    workflow = Path(".github/workflows/testpypi.yml").read_text()

    assert "workflow_dispatch:" in workflow
    assert "environment:" in workflow
    assert "name: testpypi" in workflow
    assert "id-token: write" in workflow
    assert "repository-url: https://test.pypi.org/legacy/" in workflow
    assert "llm-preflight==${VERSION}" in workflow
    assert (
        'llm-preflight --quick "Reply with ok." --models mock:local --no-save'
        in workflow
    )
    assert "TWINE_PASSWORD" not in workflow
    assert "PYPI_API_TOKEN" not in workflow


def test_no_legacy_package_surfaces_remain():
    for path in (
        Path("legacy-pypi-shim"),
        Path("llm_bench"),
        Path(".github/workflows/publish-legacy-shim.yml"),
        Path("docs/migrating-to-llm-preflight.md"),
    ):
        assert not path.exists()
