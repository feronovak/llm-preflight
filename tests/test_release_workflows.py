import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
WORKFLOWS = ROOT / ".github/workflows"
AUTO = (WORKFLOWS / "auto-release.yml").read_text(encoding="utf-8")
RELEASE = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")


def _job(text: str, name: str) -> str:
    """The text of one top-level job of a workflow."""
    jobs = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([\w-]+):\n", jobs, flags=re.MULTILINE)
    blocks = dict(zip(parts[1::2], parts[2::2]))
    return blocks[name]


def _permissions(block: str) -> dict[str, str]:
    match = re.search(r"^    permissions:\n((?:      .+\n)+)", block, re.MULTILINE)
    assert match, "job has no permissions block"
    return dict(re.findall(r"^      ([\w-]+): (\S+)$", match.group(1), re.MULTILINE))


def test_auto_release_runs_only_after_tests_success_on_main():
    on = AUTO.split("\npermissions:", 1)[0]
    assert "workflow_run:" in on
    assert "workflows: [tests]" in on
    assert "types: [completed]" in on
    assert "branches: [main]" in on
    for other in ("pull_request", "push:", "workflow_dispatch", "schedule"):
        assert other not in on.split("on:", 1)[1]
    classify = _job(AUTO, "classify")
    assert "github.event.workflow_run.conclusion == 'success'" in classify
    assert "github.event.workflow_run.event == 'push'" in classify
    assert "concurrency:" in AUTO and "cancel-in-progress: false" in AUTO


def test_auto_release_acts_only_on_a_version_change_with_green_checks():
    classify = _job(AUTO, "classify")
    assert '"${HEAD_SHA}^:pyproject.toml"' in classify
    assert "prep=false" in classify
    for check in ("test (3.10)", "test (3.13)", "security", "mock-action", "check"):
        assert f'"{check}"' in classify
    assert "steps.prep.outputs.prep == 'true'" in classify


def test_auto_release_minimum_permissions():
    assert re.search(r"^permissions: \{\}$", AUTO, re.MULTILINE)
    assert "id-token" not in AUTO
    assert _permissions(_job(AUTO, "classify")) == {
        "contents": "read",
        "checks": "read",
    }
    assert _permissions(_job(AUTO, "release")) == {
        "contents": "write",
        "actions": "write",
    }
    assert AUTO.count("persist-credentials: false") == AUTO.count("actions/checkout")


def test_release_job_gated_on_qualifies_and_switch():
    release = _job(AUTO, "release")
    assert "needs: classify" in release
    assert "needs.classify.outputs.qualifies == 'true'" in release
    assert "vars.AUTO_RELEASE == 'on'" in release
    assert "environment:" not in release


def test_classifier_runs_from_base_tag():
    classify = _job(AUTO, "classify")
    assert 'git show "${base}:scripts/release_classify.py"' in classify
    assert 'python3 -I "${RUNNER_TEMP}/release_classify.py"' in classify
    assert "python3 scripts/release_classify.py" not in AUTO
    assert (
        "git describe --tags --abbrev=0 --match 'v[0-9]*' \"${HEAD_SHA}^\"" in classify
    )
    # A base tag without the classifier is not an error: the maintainer tags.
    assert "has no classifier" in classify


def test_tag_at_head_sha_then_testpypi_then_release_then_dispatch():
    release = _job(AUTO, "release")
    steps = [
        release.index('-f "sha=${HEAD_SHA}"'),
        release.index('dispatch_and_watch.sh" testpypi.yml'),
        release.index("gh release create"),
        release.index('dispatch_and_watch.sh" release.yml'),
    ]
    assert steps == sorted(steps)
    assert "--verify-tag" in release
    assert (
        'gh workflow run "${workflow}" --repo "${REPO}" --ref "v${VERSION}"' in release
    )
    assert "gh run watch" in release and "--exit-status" in release
    # An existing tag must point at the head commit, else the job fails.
    assert 'if [ "${existing}" != "${HEAD_SHA}" ]' in release.replace("elif", "if")


def test_release_dispatch_only_for_v_tags_and_checks_version():
    on = RELEASE.split("\npermissions:", 1)[0]
    assert "types: [published]" in on
    assert "workflow_dispatch:" in on
    build = _job(RELEASE, "build")
    assert (
        "github.event_name == 'release' || startsWith(github.ref, 'refs/tags/v')"
        in build
    )
    assert 'test "${GITHUB_REF_NAME}" = "v$(python -c' in build
    assert re.search(r"^permissions:\n  contents: read$", RELEASE, re.MULTILINE)
    assert "contents: write" not in RELEASE and "actions: write" not in RELEASE


def test_no_other_workflow_grants_write():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == "auto-release.yml":
            continue
        text = path.read_text(encoding="utf-8")
        assert "actions: write" not in text, path.name
        assert "contents: write" not in text, path.name
