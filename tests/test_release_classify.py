import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts/release_classify.py"

PRICING = "llm_preflight/pricing.py"
RETIREMENTS = "llm_preflight/retirements.py"
CI_DOC = "docs/automation/ci.md"
REAL_FILES = (
    PRICING,
    RETIREMENTS,
    "llm_preflight/__init__.py",
    "pyproject.toml",
    "server.json",
    "plugins/llm-preflight/.codex-plugin/plugin.json",
)


def _load():
    spec = importlib.util.spec_from_file_location("release_classify", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rc = _load()


def _version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "(\d+\.\d+\.\d+)"$', text, re.MULTILINE)
    assert match
    return match.group(1)


BASE_VERSION = _version()
MAJOR, MINOR, PATCH = (int(part) for part in BASE_VERSION.split("."))
NEXT_VERSION = f"{MAJOR}.{MINOR}.{PATCH + 1}"
PREVIOUS_VERSION = f"{MAJOR}.{MINOR}.{max(PATCH - 1, 0)}"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _replace(text: str, old: str, new: str) -> str:
    assert old in text, f"anchor not found: {old!r}"
    return text.replace(old, new, 1)


def _bump(text: str, version: str) -> str:
    return text.replace(BASE_VERSION, version)


class Repo:
    """A temp git repo whose base commit holds the real data files."""

    def __init__(self, path: Path) -> None:
        self.path = path
        _git(path, "init", "-q")
        for relative in REAL_FILES:
            _write(path, relative, (ROOT / relative).read_text(encoding="utf-8"))
        _write(path, "CHANGELOG.md", "# Changelog\n\n## Unreleased\n")
        _write(
            path,
            CI_DOC,
            f"Run a pinned release:\npackage-version: {PREVIOUS_VERSION}\n",
        )
        _write(path, "docs/data/models.md", "rows\n")
        _write(path, "llm_preflight/client.py", "VALUE = 1\n")
        _write(path, "scripts/render_measured_models.py", "VALUE = 1\n")
        _write(path, "tests/conftest.py", "VALUE = 1\n")
        _write(path, ".github/workflows/tests.yml", "name: tests\n")
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", "base")
        _git(path, "tag", f"v{BASE_VERSION}")

    def read(self, relative: str) -> str:
        return (self.path / relative).read_text(encoding="utf-8")

    def edit(self, relative: str, change) -> None:
        _write(self.path, relative, change(self.read(relative)))

    def release_prep(self, version: str = NEXT_VERSION, dated: bool = True) -> None:
        """The version files and CHANGELOG a release-prep commit changes."""
        for relative in REAL_FILES[2:]:
            self.edit(relative, lambda text: _bump(text, version))
        heading = f"## {version} - 2026-11-14" if dated else f"## {version}"
        self.edit(
            "CHANGELOG.md",
            lambda t: t.replace("## Unreleased\n", f"## Unreleased\n\n{heading}\n"),
        )

    def head(self) -> str:
        _git(self.path, "add", "-A")
        _git(self.path, "commit", "-q", "--allow-empty", "-m", "head")
        return _git(self.path, "rev-parse", "HEAD")

    def classify(self) -> dict:
        return self.verdict(self.head())

    def verdict(self, head: str) -> dict:
        previous = Path.cwd()
        try:
            os.chdir(self.path)
            return rc.classify(f"v{BASE_VERSION}", head)
        finally:
            os.chdir(previous)


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


def _assert_no(verdict: dict, fragment: str) -> None:
    assert verdict["qualifies"] is False
    assert any(fragment in reason for reason in verdict["reasons"]), verdict["reasons"]


PRICING_HEADER = "PUBLIC_PRICING: dict[tuple[str, str], tuple[float, float, str]] = {\n"


def _add_price_row(row: str = '    ("test", "new-model"): (1.0, 2.0, "2026-01-01"),\n'):
    return lambda text: _replace(text, PRICING_HEADER, PRICING_HEADER + row)


# --- qualifies -----------------------------------------------------------------


def test_price_row_added_and_as_of_bumped_qualifies(repo):
    repo.edit(PRICING, _add_price_row())
    repo.edit(PRICING, lambda t: t.replace('"2026-11-04"', '"2026-12-01"'))
    repo.release_prep()
    verdict = repo.classify()
    assert verdict["reasons"] == []
    assert verdict["qualifies"] is True
    assert verdict["version"] == NEXT_VERSION


def test_retirement_row_and_reviewed_bump_qualifies(repo):
    repo.edit(
        RETIREMENTS,
        lambda t: _replace(
            t,
            "_ANTHROPIC: dict[str, dict[str, Any]] = {\n",
            '_ANTHROPIC: dict[str, dict[str, Any]] = {\n    "claude-new": _anthropic("active"),\n',
        ),
    )
    repo.edit(
        RETIREMENTS,
        lambda t: re.sub(r'_REVIEWED = "[^"]+"', '_REVIEWED = "2026-12-01"', t),
    )
    repo.release_prep()
    verdict = repo.classify()
    assert verdict["reasons"] == []


def test_model_tuple_in_comprehension_qualifies(repo):
    repo.edit(
        PRICING,
        lambda t: _replace(
            t, "for model in (\n", 'for model in (\n            "gpt-new",\n'
        ),
    )
    repo.edit(
        RETIREMENTS,
        lambda t: _replace(
            t,
            'for model in ("gemini-3.6-flash"',
            'for model in ("gemini-new", "gemini-3.6-flash"',
        ),
    )
    repo.release_prep()
    assert repo.classify()["reasons"] == []


def test_comment_only_edit_qualifies(repo):
    repo.edit(PRICING, lambda t: "# a new note\n" + t)
    repo.edit(RETIREMENTS, lambda t: t + "\n# trailing note\n")
    repo.release_prep()
    assert repo.classify()["reasons"] == []


def test_data_docs_tests_and_version_files_qualify(repo):
    _write(repo.path, "docs/data/models.md", "more rows\n")
    _write(repo.path, "docs/images/measured-models-a.svg", "<svg/>\n")
    _write(repo.path, "README.md", "readme\n")
    _write(repo.path, "tests/test_pricing.py", "def test_x(): pass\n")
    repo.release_prep()
    assert repo.classify()["reasons"] == []


def test_previous_pin_substitution_qualifies(repo):
    repo.edit(CI_DOC, lambda t: t.replace(PREVIOUS_VERSION, BASE_VERSION))
    repo.release_prep()
    assert repo.classify()["reasons"] == []


# --- does not qualify: logic ---------------------------------------------------

BODY = "def estimate_sample_cost(sample: dict[str, Any], model: dict[str, Any]) -> float | None:\n"
ROW_STATUS = "def _row_status(row: dict[str, Any] | None, today: date) -> str:\n"
FIRST_NAME = "for model in (\n"

LOGIC_EDITS = {
    "function body": (PRICING, lambda t: _replace(t, BODY, BODY + "    sample = {}\n")),
    "retirement function body": (
        RETIREMENTS,
        lambda t: _replace(t, ROW_STATUS, ROW_STATUS + "    today = today\n"),
    ),
    "multiplier": (
        PRICING,
        lambda t: re.sub(
            r"ANTHROPIC_US_INFERENCE_MULTIPLIER = [\d.]+",
            "ANTHROPIC_US_INFERENCE_MULTIPLIER = 9.9",
            t,
        ),
    ),
    "expiry days": (
        RETIREMENTS,
        lambda t: re.sub(r"EXPIRY_NOTICE_DAYS = \d+", "EXPIRY_NOTICE_DAYS = 99", t),
    ),
    "gemini redirects": (
        RETIREMENTS,
        lambda t: _replace(
            t,
            "GEMINI_MODEL_REDIRECTS = {\n",
            'GEMINI_MODEL_REDIRECTS = {\n    "a": "b",\n',
        ),
    ),
    "pricing sources": (
        PRICING,
        lambda t: t + '\nPUBLIC_PRICING_SOURCES[("a", "b")] = "c"\n',
    ),
    "row builder": (
        RETIREMENTS,
        lambda t: _replace(
            t,
            "    row: dict[str, Any] = {",
            "    as_of = as_of\n    row: dict[str, Any] = {",
        ),
    ),
    "table update call": (PRICING, lambda t: t + "\nPUBLIC_PRICING.update({})\n"),
    "table item assignment": (
        PRICING,
        lambda t: t + '\nPUBLIC_PRICING[("a", "b")] = (1.0, 2.0, "2026-01-01")\n',
    ),
    "second table assignment": (
        PRICING,
        lambda t: t + "\nPUBLIC_PRICING_CHANGES = {}\n",
    ),
    "round in table": (
        PRICING,
        _add_price_row('    ("t", "m"): (round(1.0), 2.0, "2026-01-01"),\n'),
    ),
    "max in table": (
        PRICING,
        _add_price_row('    ("t", "m"): (max(1.0, 2.0), 2.0, "2026-01-01"),\n'),
    ),
    "lambda in table": (
        PRICING,
        _add_price_row('    ("t", "m"): ((lambda: 1.0)(), 2.0, "2026-01-01"),\n'),
    ),
    "arithmetic in table": (
        PRICING,
        _add_price_row('    ("t", "m"): (1.0 * 2, 2.0, "2026-01-01"),\n'),
    ),
    "annotation": (
        PRICING,
        lambda t: _replace(
            t, PRICING_HEADER, "PUBLIC_PRICING: dict[tuple[str, str], Any] = {\n"
        ),
    ),
    "comprehension element": (
        PRICING,
        lambda t: _replace(t, "api/docs/models/{model}", "api/docs/other/{model}"),
    ),
    "comprehension source": (
        PRICING,
        lambda t: _replace(t, FIRST_NAME, "for model in sorted(\n"),
    ),
    "new import": (
        PRICING,
        lambda t: _replace(t, "import json\n", "import json\nimport os\n"),
    ),
}


def test_non_utf8_encoding_declaration_is_rejected(repo):
    # Under GBK the last byte of the euro sign swallows the backslash, so the
    # string closes early and the print runs at import time.
    smuggled = 'OPENAI_DEPRECATIONS_URL = "\u20ac\\"; print(\'SMUGGLED\') # "'
    repo.edit(
        RETIREMENTS,
        lambda t: (
            "# coding: gbk\n"
            + re.sub(
                r"^OPENAI_DEPRECATIONS_URL = .*$",
                lambda _: smuggled,
                t,
                count=1,
                flags=re.MULTILINE,
            )
        ),
    )
    repo.release_prep()
    with pytest.raises(rc.ClassifierError, match="declares encoding gbk"):
        repo.classify()


def test_utf8_bom_is_rejected(repo):
    repo.edit(PRICING, lambda t: "\ufeff" + t)
    repo.release_prep()
    with pytest.raises(rc.ClassifierError, match="utf-8-sig"):
        repo.classify()


def test_comprehension_copied_from_outside_the_table_does_not_qualify(repo):
    routing = (
        "    **{key: _MODEL_PRICING_PAGES.get(key, _PROVIDER_PRICING_PAGES[key[0]])"
        " for key in PUBLIC_PRICING},\n"
    )
    repo.edit(
        PRICING,
        lambda t: _replace(
            t, "PUBLIC_PRICING_CHANGES = {\n", "PUBLIC_PRICING_CHANGES = {\n" + routing
        ),
    )
    repo.release_prep()
    _assert_no(repo.classify(), "PUBLIC_PRICING_CHANGES")


def test_non_utf8_path_is_an_error(repo):
    (repo.path / os.fsdecode(b"bad-\xff.txt")).write_text("x\n", encoding="utf-8")
    repo.release_prep()
    with pytest.raises(rc.ClassifierError, match="not UTF-8"):
        repo.classify()


@pytest.mark.parametrize("name", sorted(LOGIC_EDITS))
def test_logic_edit_does_not_qualify(repo, name):
    path, change = LOGIC_EDITS[name]
    repo.edit(path, change)
    repo.release_prep()
    verdict = repo.classify()
    assert verdict["qualifies"] is False, name
    assert any(path in reason for reason in verdict["reasons"]), verdict["reasons"]


def test_head_syntax_error_is_an_error(repo):
    repo.edit(PRICING, lambda t: t + "\ndef (\n")
    repo.release_prep()
    with pytest.raises(rc.ClassifierError):
        repo.classify()


@pytest.mark.parametrize("action", ["delete", "rename"])
def test_deleted_or_renamed_data_file_does_not_qualify(repo, action):
    repo.release_prep()
    if action == "delete":
        _git(repo.path, "rm", "-q", PRICING)
    else:
        _git(repo.path, "mv", PRICING, "llm_preflight/pricing_old.py")
    _assert_no(repo.classify(), "pricing")


# --- does not qualify: paths and versions --------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "llm_preflight/client.py",
        ".github/workflows/tests.yml",
        "scripts/release_classify.py",
        "scripts/render_measured_models.py",
        "tests/conftest.py",
    ],
)
def test_other_paths_do_not_qualify(repo, path):
    _write(repo.path, path, "VALUE = 2\n")
    repo.release_prep()
    _assert_no(repo.classify(), path)


def test_pyproject_dependency_line_does_not_qualify(repo):
    repo.release_prep()
    repo.edit("pyproject.toml", lambda t: t + '\n[tool.extra]\nrequires = ["x"]\n')
    _assert_no(repo.classify(), "pyproject.toml")


def test_server_json_non_version_key_does_not_qualify(repo):
    repo.release_prep()
    repo.edit(
        "server.json",
        lambda t: t.replace('"title": "LLM Preflight"', '"title": "Other"'),
    )
    _assert_no(repo.classify(), "server.json")


def test_minor_bump_does_not_qualify(repo):
    repo.release_prep(f"{MAJOR}.{MINOR + 1}.0")
    _assert_no(repo.classify(), "not a patch bump")


def test_versions_that_disagree_do_not_qualify(repo):
    repo.release_prep()
    repo.edit("server.json", lambda t: t.replace(NEXT_VERSION, BASE_VERSION))
    _assert_no(repo.classify(), "disagree")


def test_undated_changelog_does_not_qualify(repo):
    repo.release_prep(dated=False)
    _assert_no(repo.classify(), "CHANGELOG.md")


def test_non_pin_edit_in_docs_does_not_qualify(repo):
    repo.edit(CI_DOC, lambda t: t + "A new sentence about nothing.\n")
    repo.release_prep()
    _assert_no(repo.classify(), CI_DOC)


def test_pin_to_another_version_does_not_qualify(repo):
    repo.edit(CI_DOC, lambda t: t.replace(PREVIOUS_VERSION, "9.9.9"))
    repo.release_prep()
    _assert_no(repo.classify(), "previous release")


def test_existing_tag_does_not_qualify(repo):
    _git(repo.path, "tag", f"v{NEXT_VERSION}")
    repo.release_prep()
    _assert_no(repo.classify(), "already exists")


def test_empty_diff_does_not_qualify(repo):
    verdict = repo.classify()
    assert verdict["qualifies"] is False
    assert "no changes" in verdict["reasons"][0]


def test_unicode_in_data_strings_qualifies(repo):
    repo.edit(
        PRICING, _add_price_row('    ("test", "módel-ß"): (1.0, 2.0, "2026-01-01"),\n')
    )
    repo.release_prep()
    assert repo.classify()["reasons"] == []


def test_base_must_be_a_version_tag(repo):
    with pytest.raises(rc.ClassifierError):
        rc.classify("main", "HEAD")


# --- CLI and git ---------------------------------------------------------------


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exit_codes_and_json_keys(repo):
    repo.edit(PRICING, _add_price_row())
    repo.release_prep()
    head = repo.head()
    ok = _run(repo.path, "--base", f"v{BASE_VERSION}", "--head", head)
    assert ok.returncode == 0
    assert set(json.loads(ok.stdout)) == {
        "qualifies",
        "base",
        "head",
        "version",
        "reasons",
    }

    _write(repo.path, "llm_preflight/client.py", "VALUE = 2\n")
    bad = _run(repo.path, "--base", f"v{BASE_VERSION}", "--head", repo.head())
    assert bad.returncode == 1
    assert json.loads(bad.stdout)["qualifies"] is False

    missing = _run(repo.path, "--base", f"v{BASE_VERSION}", "--head", "no-such-ref")
    assert missing.returncode == 2
    assert "error" in json.loads(missing.stdout)


def test_git_range_end_to_end(repo):
    repo.edit(PRICING, _add_price_row())
    repo.release_prep()
    first = repo.head()
    _write(repo.path, "llm_preflight/client.py", "VALUE = 2\n")
    second = repo.head()
    assert repo.verdict(first)["qualifies"] is True
    assert repo.verdict(second)["qualifies"] is False
    assert repo.verdict(second)["head"] == second


def test_path_allowlist_is_pinned():
    assert rc.DATA_TABLES == {
        PRICING: (
            "PUBLIC_PRICING",
            "_PROVIDER_PRICING_PAGES",
            "_MODEL_PRICING_PAGES",
            "PUBLIC_PRICING_CHANGES",
            "PUBLIC_PRICING_DETAILS",
        ),
        RETIREMENTS: (
            "_ANTHROPIC",
            "_OPENAI",
            "_GEMINI",
            "_REVIEWED",
            "ANTHROPIC_DEPRECATIONS_URL",
            "OPENAI_DEPRECATIONS_URL",
            "GEMINI_DEPRECATIONS_URL",
        ),
    }
    assert rc.BUILDERS == {
        PRICING: ("date",),
        RETIREMENTS: ("_row", "_anthropic", "_openai"),
    }
    assert rc.VERSION_FILES == (
        "pyproject.toml",
        "llm_preflight/__init__.py",
        "server.json",
        "plugins/llm-preflight/.codex-plugin/plugin.json",
    )
    assert rc.DATA_DOC_PATTERNS == (
        r"docs/data/.*",
        r"docs/images/measured-models-[^/]*\.svg",
        r"docs/guides/observed-model-comparison\.md",
        r"docs/guides/current-snapshots\.md",
        r"docs/development/visual-assets\.md",
        r"docs/DOCMAP\.md",
        r"docs/index\.md",
        r"README\.md",
        r"tests/test_pricing\.py",
        r"tests/test_retirements\.py",
        r"tests/test_model_updates\.py",
        r"tests/test_documentation\.py",
        r"tests/test_package\.py",
    )
    assert rc.PIN_PATTERNS == (
        r"action\.yml",
        r"examples/.*",
        r"docs/.*\.md",
        r"tests/test_distribution\.py",
    )
