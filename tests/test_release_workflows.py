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
    assert "environment: auto-release" in release


def test_head_must_be_on_main_before_anything_else_in_classify():
    classify = _job(AUTO, "classify")
    guard = 'git merge-base --is-ancestor "${HEAD_SHA}" origin/main'
    assert guard in classify
    assert "fetch-depth: 0" in classify
    # The guard is the first step after the checkout.
    assert classify.index(guard) < classify.index("Require a version change")
    assert classify.index("actions/checkout") < classify.index(guard)
    assert "if:" not in classify[classify.index(guard) - 120 : classify.index(guard)]


def test_app_token_only_in_release_job_and_only_for_the_tag():
    classify = _job(AUTO, "classify")
    release = _job(AUTO, "release")
    assert "environment:" not in classify
    assert "secrets." not in classify
    assert AUTO.count("secrets.") == 2
    assert AUTO.count("actions/create-github-app-token@") == 1
    assert re.search(r"create-github-app-token@[0-9a-f]{40} # v", release)
    assert "permission-contents: write" in release
    # Only the tag step receives the App token; every other step keeps the
    # workflow token.
    assert AUTO.count("steps.app-token.outputs.token") == 1
    tag_step = release[release.index("Create the tag at the release-prep commit") :]
    tag_step = tag_step[: tag_step.index("      - name: Write the dispatch helper")]
    assert "GH_TOKEN: ${{ steps.app-token.outputs.token }}" in tag_step
    assert "GH_TOKEN: ${{ github.token }}" in release.split("    steps:")[0]


def test_watch_polls_at_a_slow_interval():
    assert "gh run watch" in AUTO
    assert "--interval 30 --exit-status" in AUTO


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
    # Manual releases are titled with the bare version; the tag keeps the v.
    assert '--verify-tag --title "${VERSION}"' in release
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


def _guard_step() -> str:
    build = _job(RELEASE, "build")
    start = build.index("      - name: Require a tagged commit on main")
    end = build.index("      - uses: actions/setup-python")
    return build[start:end]


def test_dispatch_requires_tag_commit_on_main_before_any_build():
    build = _job(RELEASE, "build")
    guard = _guard_step()
    assert "if: github.event_name == 'workflow_dispatch'" in guard
    assert 'git merge-base --is-ancestor "${GITHUB_SHA}" origin/main' in guard
    assert "fetch-depth: 0" in build.split("Require a tagged commit")[0]
    # Everything that builds or publishes comes after the guard.
    assert build.index("Require a tagged commit") < build.index(
        "make release-freshness"
    )
    assert build.index("Require a tagged commit") < build.index("python -m build")
    assert "needs: build" in _job(RELEASE, "pypi-publish")


def test_dispatch_requires_an_existing_github_release():
    guard = _guard_step()
    assert 'gh release view "${GITHUB_REF_NAME}"' in guard
    # The token is scoped to this step and never stored by gh.
    assert "        env:\n          GH_TOKEN: ${{ github.token }}\n" in guard
    assert "gh auth login" not in RELEASE
    # Read-only: the guard adds no permission beyond the workflow's contents: read.
    assert "permissions:" not in _job(RELEASE, "build")
    assert re.search(r"^permissions:\n  contents: read$", RELEASE, re.MULTILINE)


def test_published_release_path_is_not_gated_by_the_dispatch_guards():
    build = _job(RELEASE, "build")
    assert "github.event_name == 'release' ||" in build
    # The only step that mentions the guards is conditional on a dispatch.
    assert build.count("merge-base") == 1
    assert build.count("gh release view") == 1
    assert build.count("if: github.event_name == 'workflow_dispatch'") == 1
    assert 'test "${GITHUB_REF_NAME}" = "v$(python -c' in build


def test_no_other_workflow_grants_write():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == "auto-release.yml":
            continue
        text = path.read_text(encoding="utf-8")
        assert "actions: write" not in text, path.name
        assert "contents: write" not in text, path.name
