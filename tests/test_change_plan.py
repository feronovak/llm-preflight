import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from llm_preflight.approval import (
    create_approval_receipt,
    verify_approval_receipt,
    write_approval_receipt,
)
from llm_preflight.change_plan import git_change_plan
from llm_preflight.cli import dry_run_plan
from llm_preflight.redaction import redact_secrets


def _git(workspace, *args):
    return subprocess.run(
        ["git", *args], cwd=workspace, check=True, text=True, capture_output=True
    )


def test_git_change_plan_reports_changed_literal_models_without_network_access(
    tmp_path,
):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test User")
    app = tmp_path / "app.py"
    app.write_text('model = "gpt-5.4-mini"\n')
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-m", "initial")
    app.write_text('model = "gpt-5.5"\n')

    plan = git_change_plan(tmp_path, "HEAD")

    assert plan["schema_version"] == 1
    assert plan["network_accessed"] is False
    assert plan["paid_work_authorized"] is False
    assert plan["reference"] == "HEAD"
    assert plan["changed_files"] == ["app.py"]
    assert plan["triggers"] == [
        {
            "kind": "model_id",
            "path": "app.py",
            "line": 1,
            "provider": "openai",
            "model": "gpt-5.5",
            "pricing_status": "pricing_known",
        }
    ]
    assert "dynamic model selection" in plan["notes"][0]


def test_git_change_plan_includes_untracked_contract_surface_files(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test User")
    tracked = tmp_path / "README.md"
    tracked.write_text("starter\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "initial")
    prompt = tmp_path / "prompts.py"
    prompt.write_text('system_prompt = "Return JSON"\n')

    plan = git_change_plan(tmp_path, "HEAD")

    assert plan["changed_files"] == ["prompts.py"]
    assert plan["triggers"] == [
        {
            "kind": "contract_surface",
            "path": "prompts.py",
            "line": 1,
            "field": "system_prompt",
        }
    ]


def test_git_change_plan_reports_deleted_contract_surfaces_from_the_reference(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test User")
    prompt = tmp_path / "prompts.py"
    prompt.write_text('system_prompt = "Return JSON"\n')
    _git(tmp_path, "add", "prompts.py")
    _git(tmp_path, "commit", "-m", "initial")
    prompt.unlink()

    plan = git_change_plan(tmp_path, "HEAD")

    assert plan["changed_files"] == ["prompts.py"]
    assert plan["deleted_files"] == ["prompts.py"]
    assert plan["triggers"] == [
        {
            "kind": "contract_surface",
            "path": "prompts.py",
            "line": 1,
            "field": "system_prompt",
            "change": "deleted",
        }
    ]


def _repository(workspace):
    workspace.mkdir()
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.email", "test@example.invalid")
    _git(workspace, "config", "user.name", "Test User")
    return workspace


def _make_stat_dirty(path):
    """Rewrite a file with an old mtime so Git must re-read its content."""
    path.write_text(path.read_text())
    os.utime(path, (946684800, 946684800))


def test_git_change_plan_never_runs_a_command_the_repository_configures(
    tmp_path, tripwire
):
    library = _repository(tmp_path / "library")
    (library / ".gitattributes").write_text("*.py filter=tripwire\n")
    (library / "client.py").write_text('model = "gpt-5.4-mini"\n')
    _git(library, "add", ".")
    _git(library, "commit", "-q", "-m", "initial")
    repo = _repository(tmp_path / "repo")
    (repo / ".gitattributes").write_text("*.py filter=tripwire\n")
    (repo / "app.py").write_text('model = "gpt-5.4-mini"\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
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
    _git(repo, "commit", "-q", "-m", "submodule")
    submodule = repo / "vendor" / "library"
    for workspace, prefix in ((repo, ""), (submodule, "submodule-")):
        _git(workspace, "config", "core.fsmonitor", tripwire(f"{prefix}fsmonitor"))
        _git(
            workspace,
            "config",
            "filter.tripwire.clean",
            tripwire(f"{prefix}clean", passthrough=True),
        )
        _git(workspace, "config", "filter.tripwire.required", "true")
    _make_stat_dirty(repo / "app.py")
    _make_stat_dirty(submodule / "client.py")

    plan = git_change_plan(repo, "HEAD")

    assert sorted(path.name for path in tmp_path.glob("*.ran")) == []
    assert plan["deleted_files"] == []


@pytest.mark.parametrize("hook_location", ["core.hooksPath", ".git/hooks"])
def test_git_change_plan_never_runs_a_repository_hook(
    tmp_path, tripwire, monkeypatch, hook_location
):
    # A global core.hooksPath would mask the repository's own hooks directory.
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = _repository(tmp_path / "repo")
    (repo / "app.py").write_text('model = "gpt-5.4-mini"\n')
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-q", "-m", "initial")
    if hook_location == "core.hooksPath":
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        _git(repo, "config", "core.hooksPath", str(hooks))
    else:
        hooks = repo / ".git" / "hooks"
    hook = hooks / "post-index-change"
    hook.write_text(Path(tripwire("hook")).read_text())
    hook.chmod(0o755)
    _make_stat_dirty(repo / "app.py")

    plan = git_change_plan(repo, "HEAD")

    assert plan["changed_files"] == []
    assert list(tmp_path.glob("*.ran")) == []


def test_git_change_plan_disables_a_filter_driver_with_an_empty_name(
    tmp_path, tripwire
):
    repo = _repository(tmp_path / "repo")
    (repo / ".gitattributes").write_text("* filter=\n")
    (repo / "app.py").write_text('model = "gpt-5.4-mini"\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(repo, "config", "filter..clean", tripwire("clean", passthrough=True))
    _git(repo, "config", "filter..required", "true")
    _make_stat_dirty(repo / "app.py")

    git_change_plan(repo, "HEAD")

    assert list(tmp_path.glob("*.ran")) == []


def test_git_change_plan_refuses_a_filter_it_cannot_disable(tmp_path, tripwire):
    repo = _repository(tmp_path / "repo")
    (repo / "app.py").write_text('model = "gpt-5.4-mini"\n')
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(repo, "config", "filter.a=b.clean", tripwire("clean", passthrough=True))
    (repo / ".git" / "info" / "attributes").write_text("*.py filter=a=b\n")
    _make_stat_dirty(repo / "app.py")

    with pytest.raises(ValueError, match="filter driver"):
        git_change_plan(repo, "HEAD")

    assert list(tmp_path.glob("*.ran")) == []


def test_git_change_plan_never_runs_a_filter_and_still_lists_a_change(
    tmp_path, tripwire
):
    repo = _repository(tmp_path / "repo")
    (repo / ".gitattributes").write_text("*.py filter=tripwire\n")
    (repo / "app.py").write_text('model = "gpt-5.4-mini"\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(
        repo,
        "config",
        "filter.tripwire.clean",
        tripwire("clean", passthrough=True),
    )
    (repo / "app.py").write_text('model = "gpt-5.5"\n')

    plan = git_change_plan(repo, "HEAD")

    assert plan["changed_files"] == ["app.py"]
    assert [trigger["model"] for trigger in plan["triggers"]] == ["gpt-5.5"]
    assert list(tmp_path.glob("*.ran")) == []


def test_git_change_plan_never_fetches_a_missing_object(tmp_path, tripwire):
    origin = _repository(tmp_path / "origin")
    (origin / "app.py").write_text('model = "gpt-5.4-mini"\n')
    _git(origin, "add", "app.py")
    _git(origin, "commit", "-q", "-m", "initial")
    _git(origin, "config", "uploadpack.allowFilter", "true")
    _git(
        tmp_path,
        "-c",
        "protocol.file.allow=always",
        "clone",
        "-q",
        "--no-checkout",
        "--filter=blob:none",
        (tmp_path / "origin").as_uri(),
        "clone",
    )
    clone = tmp_path / "clone"
    _git(clone, "config", "remote.origin.url", "ssh://example.invalid/origin")
    _git(clone, "config", "core.sshCommand", tripwire("ssh"))

    with pytest.raises(ValueError):
        git_change_plan(clone, "HEAD")

    assert list(tmp_path.glob("*.ran")) == []


def test_git_change_plan_ignores_git_environment_redirection(tmp_path, monkeypatch):
    other = _repository(tmp_path / "other")
    (other / "other.py").write_text('model = "gpt-5.4-mini"\n')
    _git(other, "add", "other.py")
    _git(other, "commit", "-q", "-m", "initial")
    repo = _repository(tmp_path / "repo")
    (repo / "README.md").write_text("starter\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial")
    (repo / "app.py").write_text('model = "gpt-5.5"\n')
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))

    plan = git_change_plan(repo, "HEAD")

    assert plan["changed_files"] == ["app.py"]


def test_git_change_plan_reports_a_name_that_is_not_utf8_as_utf8_text(
    tmp_path, non_utf8_file_names
):
    repo = _repository(tmp_path / "repo")
    gone = repo / os.fsdecode(b"g\xffone.py")
    gone.write_text('model = "gpt-5.4-mini"\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    gone.unlink()
    (repo / os.fsdecode(b"n\xfeew.py")).write_text('model = "gpt-5.5"\n')

    plan = git_change_plan(repo, "HEAD")

    assert plan["changed_files"] == ["g\\xffone.py", "n\\xfeew.py"]
    assert plan["deleted_files"] == ["g\\xffone.py"]
    assert [(item["path"], item["model"]) for item in plan["triggers"]] == [
        ("g\\xffone.py", "gpt-5.4-mini"),
        ("n\\xfeew.py", "gpt-5.5"),
    ]
    # A lone surrogate cannot be encoded, so this fails on any escaped byte.
    json.dumps(plan, ensure_ascii=False).encode("utf-8")


def test_approval_receipt_distinguishes_plans_that_differ_after_a_secret_shaped_word():
    def plan(token, api_key="sk-synthetic-one"):
        return dry_run_plan(
            {
                "name": "checkout",
                "prompt": "Reply with ok.",
                "models": [{"provider": "mock", "model": "local", "response": "ok"}],
                "request": {
                    "temperature": 0,
                    "system_prompt": f"obey {token}",
                    "api_key": api_key,
                },
                "repetitions": 1,
                "warmups": 0,
            }
        )

    now = datetime(2026, 10, 17, tzinfo=timezone.utc)
    expires_at = "2026-11-17T00:00:00+00:00"
    first = plan("sk-alpha")
    second = plan("sk-beta")
    same_key = plan("sk-alpha", api_key="sk-synthetic-two")
    receipt = create_approval_receipt(
        first,
        note="Reviewed the bounded checkout.",
        expires_at=expires_at,
        now=now,
    )

    assert "sk-alpha" not in json.dumps(receipt)
    assert verify_approval_receipt(receipt, first, now=now)["state"] == "recorded"
    assert verify_approval_receipt(receipt, second, now=now)["state"] == "mismatch"
    assert verify_approval_receipt(receipt, same_key, now=now)["state"] == "recorded"


@pytest.mark.parametrize(
    ("field", "left", "right"),
    [
        ("model", "sk-alpha", "sk-beta"),
        ("base_url", "https://sk-alpha.example/v1", "https://sk-beta.example/v1"),
        ("response", "sk-alpha", "sk-beta"),
    ],
)
def test_approval_receipt_distinguishes_model_fields_that_differ_by_a_secret_shaped_word(
    field, left, right
):
    """The receipt hashes model id, base URL and mock response as written.

    Display redacts those strings. The prompt body is not in the plan.
    """

    def plan(token):
        model = {"provider": "mock", "model": "local", "response": "ok"}
        if field == "base_url":
            model = {
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "base_url": token,
            }
        else:
            model[field] = token
        return dry_run_plan(
            {
                "name": "checkout",
                "prompt": "Reply with ok.",
                "models": [model],
                "repetitions": 1,
                "warmups": 0,
            }
        )

    now = datetime(2026, 10, 17, tzinfo=timezone.utc)
    first = plan(left)
    second = plan(right)
    receipt = create_approval_receipt(
        first,
        note="Reviewed the bounded checkout.",
        expires_at="2026-11-17T00:00:00+00:00",
        now=now,
    )

    assert first["models"][0][field] == left
    assert left not in json.dumps(redact_secrets(first))
    assert left not in json.dumps(receipt)
    assert verify_approval_receipt(receipt, first, now=now)["state"] == "recorded"
    assert verify_approval_receipt(receipt, second, now=now)["state"] == "mismatch"


def test_approval_receipt_is_bound_to_one_plan_and_expires():
    plan = {
        "benchmark": "checkout",
        "models": [{"provider": "mock", "model": "local"}],
        "possible_requests": 2,
        "maximum_estimated_cost_usd": 0.01,
    }
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    receipt = create_approval_receipt(
        plan,
        note="Reviewed the bounded checkout smoke.",
        expires_at="2026-09-05T12:00:00+00:00",
        now=now,
    )

    assert receipt["schema_version"] == 1
    assert receipt["recorded_human_approval"] is True
    assert receipt["authorizes_paid_run"] is False
    assert receipt["bounds"] == {
        "possible_requests": 2,
        "maximum_estimated_cost_usd": 0.01,
    }
    assert verify_approval_receipt(receipt, plan, now=now) == {
        "ok": True,
        "state": "recorded",
        "reason": "receipt matches the current no-spend plan and has not expired",
        "authorizes_paid_run": False,
    }
    changed_plan = {**plan, "possible_requests": 3}
    assert (
        verify_approval_receipt(receipt, changed_plan, now=now)["state"] == "mismatch"
    )
    assert (
        verify_approval_receipt(
            receipt, plan, now=datetime(2026, 9, 6, tzinfo=timezone.utc)
        )["state"]
        == "expired"
    )


def test_write_approval_receipt_keeps_an_existing_parent_directory_accessible(
    tmp_path,
):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    receipt_path = shared / "receipt.json"

    write_approval_receipt(receipt_path, {"schema_version": 1}, replace=False)

    assert stat.S_IMODE(shared.stat().st_mode) == 0o755
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600


def _repository_with_signal(workspace):
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.invalid")
    _git(workspace, "config", "user.name", "Test User")
    (workspace / "app.py").write_text('model = "gpt-5.4-mini"\n')
    (workspace / "locked.py").write_text("x = 1\n")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "initial")
    (workspace / "app.py").write_text('model = "gpt-5.5"\n')
    (workspace / "locked.py").write_text('prompt = "changed"\n')


def _deny_reading(monkeypatch, name, method):
    """Make one path unreadable even when the tests run as root."""
    original = getattr(Path, method)

    def guarded(self, *args, **kwargs):
        if self.name == name:
            raise PermissionError(13, "Permission denied", str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, method, guarded)


def test_git_change_plan_reports_a_file_it_may_not_read(tmp_path, monkeypatch):
    _repository_with_signal(tmp_path)
    locked = tmp_path / "locked.py"
    locked.chmod(0)
    _deny_reading(monkeypatch, "locked.py", "read_text")
    try:
        plan = git_change_plan(tmp_path, "HEAD")
    finally:
        locked.chmod(0o644)

    assert plan["files_unreadable"] == 1
    assert plan["unreadable_files"] == ["locked.py"]
    assert plan["plan_incomplete"] is True
    assert plan["requires_preflight_review"] is True
    assert plan["notes"][0].startswith("Plan incomplete: 1 file could not be read")
    assert [(item["path"], item["kind"]) for item in plan["triggers"]] == [
        ("app.py", "model_id")
    ]


def test_git_change_plan_reports_a_file_in_a_directory_it_may_not_enter(
    tmp_path, monkeypatch
):
    _repository_with_signal(tmp_path)
    _deny_reading(monkeypatch, "locked.py", "stat")

    plan = git_change_plan(tmp_path, "HEAD")

    assert plan["files_unreadable"] == 1
    assert plan["unreadable_files"] == ["locked.py"]
    assert plan["plan_incomplete"] is True


def test_git_change_plan_counts_a_file_that_is_not_utf8_as_unreadable(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "keep.txt").write_text("x\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    (tmp_path / "prompt.txt").write_bytes('prompt = "hi"\n'.encode("utf-16"))

    plan = git_change_plan(tmp_path, "HEAD")

    assert plan["files_unreadable"] == 1
    assert plan["unreadable_files"] == ["prompt.txt"]
    assert plan["plan_incomplete"] is True
    assert plan["requires_preflight_review"] is True
    assert plan["triggers"] == []


def test_git_change_plan_without_unreadable_files_is_not_marked_incomplete(tmp_path):
    _repository_with_signal(tmp_path)

    plan = git_change_plan(tmp_path, "HEAD")

    assert plan["files_unreadable"] == 0
    assert plan["unreadable_files"] == []
    assert plan["plan_incomplete"] is False
    assert len(plan["notes"]) == 2
    assert not plan["notes"][0].startswith("Plan incomplete")


def test_git_change_plan_does_not_count_a_dangling_symlink_as_unreadable(tmp_path):
    _repository_with_signal(tmp_path)
    (tmp_path / "dangling.py").symlink_to(tmp_path / "missing.py")

    plan = git_change_plan(tmp_path, "HEAD")

    assert plan["files_unreadable"] == 0
    assert plan["plan_incomplete"] is False


def test_git_change_plan_lists_an_unreadable_name_that_is_not_utf8(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "keep.txt").write_text("x\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    odd = os.fsdecode(b"bad-\xff.bin")
    (tmp_path / odd).write_bytes(b"\xff\xfe\x00")

    plan = git_change_plan(tmp_path, "HEAD")

    assert plan["unreadable_files"] == ["bad-\\xff.bin"]
    json.dumps(plan).encode("utf-8")
