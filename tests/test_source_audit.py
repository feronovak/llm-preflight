import json
import os
import shutil
import subprocess
import time
from datetime import date
from pathlib import Path

import pytest

from llm_preflight import retirements
from llm_preflight.source_audit import audit_source, audit_source_text

TODAY = date(2026, 10, 9)


def _without_retirement(references):
    return [{k: v for k, v in item.items() if k != "retirement"} for item in references]


def test_source_audit_reports_literal_model_ids_without_network(tmp_path):
    (tmp_path / "app.py").write_text(
        'fast = "gpt-5.4-mini"\nlegacy = "claude-3-opus"\n'
    )

    report = audit_source(tmp_path, today=TODAY)

    assert report["network_accessed"] is False
    assert _without_retirement(report["references"]) == [
        {
            "path": "app.py",
            "line": 1,
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "status": "pricing_known",
            "confidence": "official_snapshot",
        },
        {
            "path": "app.py",
            "line": 2,
            "provider": "anthropic",
            "model": "claude-3-opus",
            "status": "pricing_unknown",
            "confidence": "unknown",
        },
    ]
    assert report["references"][0]["retirement"]["status"] == "unknown"
    assert report["ok"] is True
    assert report["confidence"] == "limited_static_pricing_and_retirement"
    assert report["retirement_snapshot"]["providers"] == [
        "anthropic",
        "gemini",
        "openai",
    ]
    assert any("not a verdict" in note for note in report["notes"])


def test_source_audit_detects_provider_prefixed_and_unquoted_yaml_model_ids(tmp_path):
    (tmp_path / "models.yaml").write_text(
        "model: gpt-5.5\nmodel: anthropic/claude-sonnet-5\nmodel: x-ai/grok-4.3\n"
        "model: deepseek-flash\nmodel: qwen3.8-max\nmodel: jev-latest\n"
    )

    report = audit_source(tmp_path)

    assert [(item["line"], item["model"]) for item in report["references"]] == [
        (1, "gpt-5.5"),
        (2, "anthropic/claude-sonnet-5"),
        (3, "x-ai/grok-4.3"),
        (4, "deepseek-flash"),
        (5, "qwen3.8-max"),
        (6, "jev-latest"),
    ]


def test_source_audit_ignores_bare_model_prefix_fragments(tmp_path):
    (tmp_path / "app.py").write_text('prefix = "gpt-"\nother = "claude-"\n')

    assert audit_source(tmp_path)["references"] == []


def test_source_audit_recognizes_glm_5_3_and_routed_id(tmp_path):
    (tmp_path / "app.py").write_text('native = "glm-5.3"\nrouted = "z-ai/glm-5.3"\n')
    report = audit_source(tmp_path)
    assert [r["model"] for r in report["references"]] == ["glm-5.3", "z-ai/glm-5.3"]
    assert all(r["provider"] == "zai" for r in report["references"])
    assert report["references"][0]["status"] == "pricing_known"


def test_source_audit_ignores_paths_and_commented_yaml(tmp_path):
    (tmp_path / "app.py").write_text('path = "docs/gpt-4-notes.md"\n')
    (tmp_path / "models.yaml").write_text("# model: gpt-4o-mini\n")

    assert audit_source(tmp_path)["references"] == []


URL = "https://example.test/deprecations"
TABLE = {
    ("openai", "gpt-gone"): {
        "status": "deprecated",
        "retirement_date": "2026-10-01",
        "replacement": "gpt-new",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("openai", "gpt-going"): {
        "status": "deprecated",
        "retirement_date": "2027-04-01",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("openai", "gpt-new"): {
        "status": "active",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("anthropic", "claude-fine"): {
        "status": "active",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
}


def test_source_audit_attaches_retirement_verdicts_and_a_decision(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    (tmp_path / "app.py").write_text(
        'a = "gpt-gone"\nb = "gpt-going"\nc = "claude-fine"\nd = "gpt-mystery"\n'
    )
    (tmp_path / "other.py").write_text('e = "gpt-gone"\n')

    report = audit_source(tmp_path, today=TODAY)

    by_model = {item["model"]: item["retirement"] for item in report["references"]}
    assert by_model["gpt-gone"]["status"] == "retired"
    assert by_model["gpt-going"]["status"] == "retiring"
    assert by_model["claude-fine"]["status"] == "active"
    assert by_model["gpt-mystery"]["status"] == "unknown"
    assert report["decision"] == "fail"
    assert [(f["path"], f["model"]) for f in report["findings"]] == [
        ("app.py", "gpt-gone"),
        ("app.py", "gpt-going"),
        ("app.py", "claude-fine"),
        ("app.py", "gpt-mystery"),
        ("other.py", "gpt-gone"),
    ]
    assert report["next_commands"] == [
        'llm-preflight --quick "<your prompt>" --models openai:gpt-gone,openai:gpt-new --dry-run'
    ]


def test_source_audit_findings_exclude_priced_models_with_unknown_retirement(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    (tmp_path / "app.py").write_text('fast = "gpt-5.4-mini"\n')

    report = audit_source(tmp_path, today=TODAY)

    assert report["references"][0]["status"] == "pricing_known"
    assert report["findings"] == []
    assert report["decision"] == "none"


def test_source_audit_lists_a_priced_model_with_a_stale_row_as_a_finding(
    tmp_path, monkeypatch
):
    stale_table = {
        ("openai", "gpt-5.4-mini"): {
            "status": "active",
            "as_of": "2026-01-01",
            "source_url": URL,
        }
    }
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", stale_table)
    (tmp_path / "app.py").write_text('fast = "gpt-5.4-mini"\n')

    report = audit_source(tmp_path, today=TODAY)

    assert report["references"][0]["status"] == "pricing_known"
    assert report["references"][0]["retirement"]["status"] == "stale"
    assert [(f["path"], f["model"]) for f in report["findings"]] == [
        ("app.py", "gpt-5.4-mini")
    ]
    assert report["decision"] == "inconclusive"


def test_source_audit_is_inconclusive_when_only_retiring_ids_are_found(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    (tmp_path / "app.py").write_text('b = "gpt-going"\n')

    assert audit_source(tmp_path, today=TODAY)["decision"] == "inconclusive"


def test_source_audit_text_carries_the_same_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)

    report = audit_source_text(tmp_path / "app.py", 'a = "gpt-gone"\n', today=TODAY)

    assert report["references"][0]["retirement"]["status"] == "retired"
    assert report["decision"] == "fail"
    assert report["next_commands"]
    assert report["confidence"] == "limited_static_pricing_and_retirement"


def test_source_audit_defaults_today_to_the_current_date(tmp_path):
    (tmp_path / "app.py").write_text('a = "gpt-5.4-mini"\n')
    assert audit_source(tmp_path)["decision"] in {
        "none",
        "pass",
        "inconclusive",
        "fail",
    }


def test_source_audit_notes_name_every_provider_in_the_retirement_snapshot():
    note = next(
        note
        for note in audit_source_text(Path("app.py"), "")["notes"]
        if note.startswith("Retirement verdicts")
    )

    for provider in retirements.RETIREMENT_PROVIDERS:
        assert provider in note.casefold()


requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)


def _git(workspace, *args):
    subprocess.run(
        ["git", *args], cwd=workspace, check=True, text=True, capture_output=True
    )


def _repository(workspace):
    workspace.mkdir()
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.email", "test@example.invalid")
    _git(workspace, "config", "user.name", "Test User")
    return workspace


@requires_git
def test_source_audit_in_a_git_work_tree_skips_ignored_files(tmp_path, monkeypatch):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    repo = _repository(tmp_path / "repo")
    (repo / ".gitignore").write_text("scratch/\n")
    (repo / "app.py").write_text('a = "gpt-going"\n')
    _git(repo, "add", ".gitignore", "app.py")
    _git(repo, "commit", "-q", "-m", "initial")
    (repo / "new.py").write_text('b = "gpt-going"\n')
    (repo / "scratch").mkdir()
    (repo / "scratch" / "old.py").write_text('c = "gpt-gone"\n')

    report = audit_source(repo, today=TODAY)

    assert report["file_selection"] == "git"
    assert report["files_scanned"] == 2
    assert [(item["path"], item["model"]) for item in report["references"]] == [
        ("app.py", "gpt-going"),
        ("new.py", "gpt-going"),
    ]
    assert report["decision"] == "inconclusive"


@requires_git
def test_source_audit_decision_on_unignored_files_matches_the_filesystem_walk(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    repo = _repository(tmp_path / "repo")
    (repo / ".gitignore").write_text("*.local.json\n")
    (repo / "app.py").write_text('a = "gpt-gone"\nb = "gpt-mystery"\n')
    (repo / "pkg").mkdir()
    (repo / "pkg" / "models.yaml").write_text("model: gpt-going\n")
    (repo / "results").mkdir()
    (repo / "results" / "run.json").write_text('{"model": "gpt-new"}\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    (repo / "draft.local.json").write_text('{"model": "gpt-new"}\n')

    from_git = audit_source(repo, today=TODAY)
    (repo / "draft.local.json").unlink()
    monkeypatch.setattr(shutil, "which", lambda name: None)
    from_walk = audit_source(repo, today=TODAY)

    assert from_git["file_selection"] == "git"
    assert from_walk["file_selection"] == "filesystem"
    for key in ("references", "findings", "decision", "next_commands"):
        assert from_git[key] == from_walk[key]


@requires_git
def test_source_audit_audits_a_subdirectory_of_a_git_work_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    repo = _repository(tmp_path / "repo")
    (repo / ".gitignore").write_text("build/\n")
    (repo / "pkg" / "build").mkdir(parents=True)
    (repo / "pkg" / "app.py").write_text('a = "gpt-going"\n')
    (repo / "pkg" / "build" / "app.py").write_text('a = "gpt-gone"\n')
    (repo / "top.py").write_text('a = "gpt-gone"\n')

    report = audit_source(repo / "pkg", today=TODAY)

    assert report["file_selection"] == "git"
    assert [item["path"] for item in report["references"]] == ["app.py"]


@requires_git
def test_source_audit_includes_tracked_submodule_files(tmp_path, monkeypatch):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    library = _repository(tmp_path / "library")
    (library / "client.py").write_text('a = "gpt-gone"\n')
    _git(library, "add", "client.py")
    _git(library, "commit", "-q", "-m", "initial")
    repo = _repository(tmp_path / "repo")
    _git(
        repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(library),
        "vendor/library",
    )

    report = audit_source(repo, today=TODAY)

    assert report["file_selection"] == "git"
    assert [item["path"] for item in report["references"]] == [
        "vendor/library/client.py"
    ]
    assert report["decision"] == "fail"


@requires_git
def test_source_audit_never_reads_a_symlink_that_leaves_the_audited_path(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    outside = tmp_path / "outside.py"
    outside.write_text('a = "gpt-gone"\n')
    repo = _repository(tmp_path / "repo")
    (repo / "app.py").write_text('a = "gpt-going"\n')
    (repo / "linked.py").symlink_to(outside)
    (repo / "alias.py").symlink_to(repo / "app.py")
    _git(repo, "add", ".")

    from_git = audit_source(repo, today=TODAY)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    from_walk = audit_source(repo, today=TODAY)

    assert from_git["file_selection"] == "git"
    for report in (from_git, from_walk):
        assert [item["path"] for item in report["references"]] == [
            "alias.py",
            "app.py",
        ]
        assert report["decision"] == "inconclusive"


@requires_git
def test_source_audit_walks_a_directory_that_is_not_a_git_work_tree(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    (tmp_path / ".gitignore").write_text("generated.py\n")
    (tmp_path / "generated.py").write_text('a = "gpt-5.4-mini"\n')
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text('a = "gpt-5.4-mini"\n')

    report = audit_source(tmp_path)

    assert report["file_selection"] == "filesystem"
    assert report["file_selection_reason"].startswith(
        "git could not list files: not a git repository"
    )
    assert [item["path"] for item in report["references"]] == ["generated.py"]


def test_source_audit_walks_the_directory_when_git_is_unavailable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    (tmp_path / "app.py").write_text('a = "gpt-5.4-mini"\n')
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "run.json").write_text('{"model": "gpt-5.4-mini"}\n')

    report = audit_source(tmp_path)

    assert report["file_selection"] == "filesystem"
    assert report["file_selection_reason"] == "git is not installed"
    assert [item["path"] for item in report["references"]] == ["app.py"]


def test_source_audit_of_a_single_file_reports_the_file_selection(tmp_path):
    source = tmp_path / "app.py"
    source.write_text('a = "gpt-5.4-mini"\n')

    report = audit_source(source)

    assert report["file_selection"] == "file"
    assert report["file_selection_reason"] is None
    assert report["files_scanned"] == 1


@requires_git
def test_source_audit_never_runs_a_command_the_audited_repository_configures(
    tmp_path, tripwire
):
    library = _repository(tmp_path / "library")
    (library / "client.py").write_text('a = "gpt-5.4-mini"\n')
    _git(library, "add", "client.py")
    _git(library, "commit", "-q", "-m", "initial")
    repo = _repository(tmp_path / "repo")
    _git(
        repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(library),
        "vendor/library",
    )
    _git(repo, "config", "core.fsmonitor", tripwire("fsmonitor"))
    _git(
        repo / "vendor" / "library",
        "config",
        "core.fsmonitor",
        tripwire("submodule-fsmonitor"),
    )

    report = audit_source(repo)

    assert report["file_selection"] == "git"
    assert [item["path"] for item in report["references"]] == [
        "vendor/library/client.py"
    ]
    assert sorted(path.name for path in tmp_path.glob("*.ran")) == []


@requires_git
def test_source_audit_lists_the_audited_repository_whatever_git_environment_is_set(
    tmp_path, monkeypatch
):
    other = _repository(tmp_path / "other")
    (other / "other.py").write_text('a = "gpt-5.4-mini"\n')
    _git(other, "add", "other.py")
    _git(other, "commit", "-q", "-m", "initial")
    repo = _repository(tmp_path / "repo")
    (repo / "app.py").write_text('a = "gpt-5.4-mini"\n')
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))

    report = audit_source(repo)

    assert report["file_selection"] == "git"
    assert [item["path"] for item in report["references"]] == ["app.py"]


@requires_git
def test_source_audit_skips_directories_only_below_the_audited_path(
    tmp_path, monkeypatch
):
    (tmp_path / "results" / "venv").mkdir(parents=True)
    repo = _repository(tmp_path / "results" / "venv" / "project")
    (repo / "app.py").write_text('a = "gpt-5.4-mini"\n')
    (repo / "results").mkdir()
    (repo / "results" / "run.json").write_text('{"model": "gpt-5.4-mini"}\n')

    from_git = audit_source(repo)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    from_walk = audit_source(repo)

    assert from_git["file_selection"] == "git"
    for report in (from_git, from_walk):
        assert report["files_scanned"] == 1
        assert [item["path"] for item in report["references"]] == ["app.py"]


@requires_git
def test_source_audit_walks_a_path_its_enclosing_repository_ignores(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    home = _repository(tmp_path / "home")
    (home / ".gitignore").write_text("*\n")
    (home / "project").mkdir()
    (home / "project" / "app.py").write_text('a = "gpt-gone"\n')

    report = audit_source(home / "project", today=TODAY)

    assert report["file_selection"] == "filesystem"
    assert report["file_selection_reason"] == (
        "the path is ignored by its enclosing git repository"
    )
    assert report["files_scanned"] == 1
    assert report["decision"] == "fail"


@requires_git
def test_source_audit_reads_an_unignored_nested_repository_like_the_walk(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    repo = _repository(tmp_path / "repo")
    (repo / "app.py").write_text('a = "gpt-going"\n')
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-q", "-m", "initial")
    nested = _repository(repo / "nested")
    (nested / "client.py").write_text('a = "gpt-gone"\n')
    (nested / "node_modules").mkdir()
    (nested / "node_modules" / "dep.js").write_text('a = "gpt-gone"\n')
    (nested / "outside.py").symlink_to(tmp_path)

    from_git = audit_source(repo, today=TODAY)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    from_walk = audit_source(repo, today=TODAY)

    assert from_git["file_selection"] == "git"
    assert [item["path"] for item in from_git["references"]] == [
        "app.py",
        "nested/client.py",
    ]
    for key in ("files_scanned", "references", "findings", "decision"):
        assert from_git[key] == from_walk[key]


@requires_git
def test_source_audit_reports_why_git_could_not_list_files(tmp_path, monkeypatch):
    repo = _repository(tmp_path / "repo")
    (repo / "app.py").write_text('a = "gpt-5.4-mini"\n')
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")

    report = audit_source(repo)

    assert report["file_selection"] == "filesystem"
    assert report["file_selection_reason"].startswith(
        "git could not list files: detected dubious ownership in repository at "
    )
    assert [item["path"] for item in report["references"]] == ["app.py"]


@requires_git
@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        (
            "fatal: key sk-synthetic-secret rejected\nhint: second line\n",
            "git could not list files: key [REDACTED] rejected",
        ),
        (
            "\nerror: \x1b[31m" + "x" * 300,
            "git could not list files: error: [31m" + "x" * 108 + "…",
        ),
        ("", "git could not list files: exit status 128"),
    ],
)
def test_source_audit_reason_quotes_one_safe_line_of_git_stderr(
    tmp_path, monkeypatch, stderr, reason
):
    def failing_git(command, **kwargs):
        raise subprocess.CalledProcessError(128, command, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", failing_git)
    (tmp_path / "app.py").write_text('a = "gpt-5.4-mini"\n')

    report = audit_source(tmp_path)

    assert report["file_selection"] == "filesystem"
    assert report["file_selection_reason"] == reason


@pytest.mark.parametrize("git_available", [True, False])
def test_source_audit_that_reads_no_file_is_inconclusive(
    tmp_path, monkeypatch, git_available
):
    if git_available:
        if shutil.which("git") is None:
            pytest.skip("git is not installed")
        project = _repository(tmp_path / "repo")
        (project / "README.md").write_text('model = "gpt-5.4-mini"\n')
        _git(project, "add", "README.md")
    else:
        monkeypatch.setattr(shutil, "which", lambda name: None)
        project = tmp_path
        (project / "README.md").write_text('model = "gpt-5.4-mini"\n')

    report = audit_source(project)

    assert report["files_scanned"] == 0
    assert report["references"] == []
    assert report["decision"] == "inconclusive"
    assert report["next_commands"] == []


def test_source_audit_lists_each_model_once_per_line_in_source_order(tmp_path):
    (tmp_path / "models.yaml").write_text(
        'model: gpt-5.5 # "gpt-5.5"\npair: ["claude-x", "gpt-5.5", "claude-x"]\n'
    )

    report = audit_source(tmp_path)

    assert [(item["line"], item["model"]) for item in report["references"]] == [
        (1, "gpt-5.5"),
        (2, "claude-x"),
        (2, "gpt-5.5"),
    ]


def test_source_audit_of_many_references_takes_linear_time():
    count = 10_000
    text = "".join(f'm = "gpt-{index}"\n' for index in range(count))

    started = time.perf_counter()
    report = audit_source_text(Path("app.py"), text)
    elapsed = time.perf_counter() - started

    assert len(report["references"]) == count
    assert elapsed < 1


def test_source_audit_counts_only_files_it_could_read(tmp_path, monkeypatch):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    (tmp_path / "models.json").write_text('{"model": "gpt-gone"}\n', encoding="utf-16")

    only_unreadable = audit_source(tmp_path, today=TODAY)
    (tmp_path / "app.py").write_text('a = "gpt-going"\n')
    mixed = audit_source(tmp_path, today=TODAY)

    assert only_unreadable["files_scanned"] == 0
    assert only_unreadable["files_unreadable"] == 1
    assert only_unreadable["decision"] == "inconclusive"
    assert mixed["files_scanned"] == 1
    assert mixed["files_unreadable"] == 1
    assert [item["path"] for item in mixed["references"]] == ["app.py"]


def test_source_audit_reports_a_name_that_is_not_utf8_as_utf8_text(
    tmp_path, monkeypatch, non_utf8_file_names
):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    project = tmp_path / os.fsdecode(b"pro\xfeject")
    project.mkdir()
    (project / os.fsdecode(b"bad\xff.py")).write_text('q = "gpt-4o"\n')

    report = audit_source(project, today=TODAY)

    assert report["root"].endswith("pro\\xfeject")
    assert [item["path"] for item in report["references"]] == ["bad\\xff.py"]
    # A lone surrogate cannot be encoded, so this fails on any escaped byte.
    json.dumps(report, ensure_ascii=False).encode("utf-8")


@requires_git
def test_source_audit_applies_gitignore_beside_a_name_that_is_not_utf8(
    tmp_path, non_utf8_file_names
):
    repo = _repository(tmp_path / "repo")
    (repo / ".gitignore").write_text("data/\n")
    (repo / "data").mkdir()
    (repo / "data" / "ignored.py").write_text('m = "gpt-3.5-turbo-0301"\n')
    (repo / os.fsdecode(b"n\xffame.txt")).write_text("notes\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    (repo / os.fsdecode(b"n\xfeew.py")).write_text('m = "gpt-5.5"\n')

    report = audit_source(repo, today=TODAY)

    assert report["file_selection"] == "git"
    assert report["file_selection_reason"] is None
    assert [item["path"] for item in report["references"]] == ["n\\xfeew.py"]
    assert report["decision"] == "none"


def test_source_audit_counts_a_file_it_may_not_read_and_audits_the_rest(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    locked = tmp_path / "locked.py"
    locked.write_text('a = "gpt-gone"\n')
    locked.chmod(0)
    try:
        try:
            locked.read_bytes()
        except PermissionError:
            pass
        else:
            pytest.skip("file permissions do not block reads here, as for root")
        only_locked = audit_source(tmp_path, today=TODAY)
        (tmp_path / "app.py").write_text('b = "gpt-going"\n')
        mixed = audit_source(tmp_path, today=TODAY)
    finally:
        locked.chmod(0o600)

    assert only_locked["files_scanned"] == 0
    assert only_locked["files_unreadable"] == 1
    assert only_locked["decision"] == "inconclusive"
    assert mixed["files_scanned"] == 1
    assert mixed["files_unreadable"] == 1
    assert [item["model"] for item in mixed["references"]] == ["gpt-going"]
