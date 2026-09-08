import stat
import subprocess
from datetime import datetime, timezone

from llm_preflight.approval import (
    create_approval_receipt,
    verify_approval_receipt,
    write_approval_receipt,
)
from llm_preflight.change_plan import git_change_plan


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
