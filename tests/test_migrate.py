import json
import shlex
import sys
from datetime import date
from pathlib import Path

import pytest

from llm_preflight import cli, migrate, retirements

TODAY = date(2026, 11, 5)
URL = "https://example.test/deprecations"


def _row(status, *, replacement=None, as_of="2026-11-01", date_=None):
    row = {"status": status, "as_of": as_of, "source_url": URL}
    if replacement:
        row["replacement"] = replacement
    if date_:
        row["retirement_date"] = date_
    return row


@pytest.fixture
def rows(monkeypatch):
    table = {
        ("openai", "old"): _row("retired", replacement="new", date_="2026-10-01"),
        ("openai", "new"): _row("active"),
        ("openai", "cand"): _row("retired", replacement="fresh", date_="2026-10-01"),
        ("openai", "hdr"): _row("retired", replacement="fresh", date_="2026-10-01"),
        ("openai", "norepl"): _row("retired", date_="2026-10-01"),
        ("openai", "modeonly"): _row("retired", date_="2026-10-01"),
        ("openai", "stale-old"): _row(
            "retired", replacement="new", as_of="2026-01-01", date_="2026-02-01"
        ),
        ("openai", "chain-old"): _row(
            "retired", replacement="dying", date_="2026-10-01"
        ),
        ("openai", "dying"): _row("deprecated", replacement="new", date_="2027-01-14"),
        ("openai", "soon"): _row("deprecated", replacement="new", date_="2027-01-14"),
        ("openai", "fine"): _row("active"),
        ("openai", "staleact"): _row("active", as_of="2026-01-01"),
        ("openai", "chain-dead"): _row(
            "retired", replacement="gone", date_="2026-10-01"
        ),
        ("openai", "gone"): _row("retired", date_="2026-09-01"),
        ("openai_compatible", "legacy"): _row(
            "retired", replacement="new", date_="2026-10-01"
        ),
    }
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", table)
    return table


def _write(tmp_path: Path, models, **extra) -> Path:
    path = tmp_path / "bench.json"
    config = {"name": "bench", "prompt": "hi", "models": models, **extra}
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return path


def _m(model, provider="openai", **extra):
    return {"provider": provider, "model": model, **extra}


def _entry(report, model):
    return next(m for m in report["models"] if m["model"] == model)


def test_retired_id_without_replacement_stops_and_writes_nothing(rows, tmp_path):
    path = _write(tmp_path, [_m("norepl")])
    before = sorted(p.name for p in tmp_path.iterdir())
    report = migrate.build_report(path, TODAY)
    entry = _entry(report, "norepl")
    assert entry["outcome"] == "no_named_replacement"
    assert entry["replacement"] is None
    assert report["decision"] == "fail"
    assert report["candidate_config"] is None
    assert report["paid_requests_made"] == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_retired_id_with_named_replacement_is_candidate(rows, tmp_path):
    report = migrate.build_report(_write(tmp_path, [_m("cand")]), TODAY)
    entry = _entry(report, "cand")
    assert entry["outcome"] == "candidate"
    assert entry["replacement"] == "fresh"
    assert report["decision"] == "fail"


def test_retired_model_reached_through_alias_is_classified(rows, tmp_path):
    path = _write(
        tmp_path, ["main"], aliases={"main": {"provider": "openai", "model": "cand"}}
    )
    entry = _entry(migrate.build_report(path, TODAY), "cand")
    assert entry["outcome"] == "candidate"
    path = _write(tmp_path, ["ghost"], aliases={"main": _m("cand")})
    with pytest.raises(ValueError, match="alias"):
        migrate.build_report(path, TODAY)


def test_mode_setting_row_reports_no_named_replacement(rows, tmp_path):
    report = migrate.build_report(_write(tmp_path, [_m("modeonly")]), TODAY)
    entry = _entry(report, "modeonly")
    assert entry["outcome"] == "no_named_replacement"
    assert entry["replacement"] is None
    assert report["decision"] == "fail"


def test_replacement_already_in_config_reuses_user_row(rows, tmp_path):
    path = _write(tmp_path, [_m("old"), _m("new")])
    report = migrate.build_report(path, TODAY)
    entry = _entry(report, "old")
    assert entry["outcome"] == "replacement_in_config"
    assert entry["replaced_by_existing_row"] is True
    assert _entry(report, "new")["outcome"] == "not_affected"


def test_stale_row_stops_even_when_retired(rows, tmp_path):
    report = migrate.build_report(_write(tmp_path, [_m("stale-old")]), TODAY)
    entry = _entry(report, "stale-old")
    assert entry["outcome"] == "snapshot_stale"
    assert entry["next_step"] == f"update llm-preflight or review {URL}"
    assert report["decision"] == "fail"


def test_retiring_replacement_stops_without_following_chain(rows, tmp_path):
    report = migrate.build_report(_write(tmp_path, [_m("chain-old")]), TODAY)
    entry = _entry(report, "chain-old")
    assert entry["outcome"] == "replacement_unusable"
    assert entry["replacement"] == "dying"
    assert entry["replacement_status"] == "retiring"


def test_unknown_replacement_status_never_reported_active(rows, tmp_path):
    entry = _entry(migrate.build_report(_write(tmp_path, [_m("cand")]), TODAY), "cand")
    assert entry["outcome"] == "candidate"
    assert entry["replacement_status"] == "unknown"


def test_route_headers_row_stops(rows, tmp_path):
    path = _write(tmp_path, [_m("hdr", headers={"X-Team": "a"})])
    assert (
        _entry(migrate.build_report(path, TODAY), "hdr")["outcome"] == "route_headers"
    )


def test_retiring_model_is_inconclusive(rows, tmp_path):
    report = migrate.build_report(_write(tmp_path, [_m("soon")]), TODAY)
    assert _entry(report, "soon")["outcome"] == "candidate"
    assert report["decision"] == "inconclusive"


def test_discovery_ignored_without_network(rows, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network")

    monkeypatch.setattr("socket.socket", boom)
    path = _write(tmp_path, [_m("fine")], discovery={"providers": ["openai"]})
    report = migrate.build_report(path, TODAY)
    assert any("discovery" in w for w in report["warnings"])
    assert report["decision"] == "pass"
    assert _entry(report, "fine")["outcome"] == "not_affected"


def test_unicode_config_name_and_empty_models_error(rows, tmp_path):
    path = tmp_path / "bänch-ü.json"
    path.write_text(
        json.dumps({"name": "ü", "prompt": "x", "models": []}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="models"):
        migrate.build_report(path, TODAY)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        migrate.build_report(path, TODAY)


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["llm-preflight", "migrate", *argv])
    monkeypatch.setattr(cli, "today_utc", lambda: TODAY)
    try:
        cli.main()
        code = 0
    except SystemExit as exc:
        code = exc.code
    return code, capsys.readouterr()


def _every_path_models():
    return [
        _m("old"),
        _m("new"),
        _m("cand"),
        _m("hdr", headers={"X-Team": "a"}),
        _m("modeonly"),
        _m("stale-old"),
        _m("chain-old"),
        _m("fine"),
        _m("soon"),
        _m("cand", base_url="https://gw.example/v1"),
    ]


def test_source_config_is_byte_identical_after_every_path(
    rows, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, _every_path_models())
    before = path.read_bytes()
    listing = sorted(p.name for p in tmp_path.iterdir())
    for flags in ([], ["--ci"], ["--json"], ["--ci", "--json"]):
        _run(monkeypatch, capsys, [str(path), *flags])
        assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == listing
    target = tmp_path / "out.json"
    for flags in (["--output", str(target)], ["--output", str(target), "--replace"]):
        _run(monkeypatch, capsys, [str(path), *flags])
        assert path.read_bytes() == before
    for flags in (["--output", str(path)], ["--output", str(path), "--replace"]):
        _run(monkeypatch, capsys, [str(path), *flags])
        assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([*listing, "out.json"])


def _expected_block(entry):
    arrow = ""
    if entry["replacement"]:
        arrow = f" -> {entry['replacement']}"
        if entry["replacement_status"]:
            arrow += f" ({entry['replacement_status']})"
    head = (
        f"  {entry['provider']}:{entry['model']} \u2014 {entry['status']} "
        f"[{entry['outcome']}]{arrow}"
    )
    lines = [head]
    if entry["retirement_date"]:
        lines.append(f"    Date: {entry['retirement_date']}")
    if entry["source_url"]:
        lines.append(f"    Source: {entry['source_url']}")
    lines.append(f"    Next: {entry['next_step']}")
    return "\n".join(lines) + "\n"


def test_text_and_json_agree_on_every_outcome(rows, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, _every_path_models())
    _, out = _run(monkeypatch, capsys, [str(path), "--json"])
    report = json.loads(out.out)
    assert set(report) == {
        "schema_version", "kind", "decision", "models", "candidate_config",
        "plan", "approval", "smoke", "paid_requests_made", "warnings", "next_steps",
    }  # fmt: skip
    assert {m["outcome"] for m in report["models"]} == {
        "candidate", "replacement_in_config", "no_named_replacement",
        "replacement_unusable", "snapshot_stale", "route_headers",
        "route_base_url", "not_affected",
    }  # fmt: skip
    _, text = _run(monkeypatch, capsys, [str(path)])
    assert text.out.startswith(f"Decision: {report['decision']}\n")
    blocks = "".join(_expected_block(e) for e in report["models"])
    body = text.out.split("\n  ", 1)[1]
    assert ("  " + body).startswith(blocks)
    assert ("  " + body).removeprefix(blocks) == (
        "Candidate config: not written (add --output PATH)\n"
    )


@pytest.mark.parametrize(
    "model, plain, ci",
    [
        ("fine", 0, 0),
        ("cand", 0, 1),
        ("soon", 0, 3),
        ("staleact", 0, 3),
        ("stale-old", 0, 1),
    ],
)
def test_exit_codes_table(rows, tmp_path, monkeypatch, capsys, model, plain, ci):
    path = _write(tmp_path, [_m(model)])
    assert _run(monkeypatch, capsys, [str(path)])[0] == plain
    assert _run(monkeypatch, capsys, [str(path), "--ci"])[0] == ci
    missing = tmp_path / "nope.json"
    assert _run(monkeypatch, capsys, [str(missing)])[0] == 2
    assert _run(monkeypatch, capsys, [str(missing), "--ci"])[0] == 2


@pytest.mark.parametrize(
    "bad", [{"provider": ["x"], "model": "m"}, {"provider": None, "model": "m"}]
)
def test_non_string_provider_is_a_config_error(
    rows, tmp_path, monkeypatch, capsys, bad
):
    path = _write(tmp_path, [bad])
    assert _run(monkeypatch, capsys, [str(path), "--ci"])[0] == 2
    assert _run(monkeypatch, capsys, [str(path)])[0] == 2


@pytest.mark.parametrize(
    "extra",
    [
        {"models": 5, "aliases": {"main": {"provider": "openai", "model": "x"}}},
        {"models": None, "aliases": {"main": {"provider": "openai", "model": "x"}}},
        {"models": ["main"], "aliases": ["main"]},
        {"models": ["m"], "aliases": "main"},
    ],
)
def test_malformed_models_or_aliases_is_a_config_error(
    rows, tmp_path, monkeypatch, capsys, extra
):
    path = tmp_path / "bench.json"
    path.write_text(json.dumps({"prompt": "p", **extra}), encoding="utf-8")
    assert _run(monkeypatch, capsys, [str(path), "--ci"])[0] == 2
    assert _run(monkeypatch, capsys, [str(path)])[0] == 2


def _decision_of(path, **kw):
    return migrate.build_report(path, TODAY)["decision"]


def test_decision_is_worst_row_not_first(rows, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("fine"), _m("cand")])
    assert _decision_of(path) == "fail"
    assert _run(monkeypatch, capsys, [str(path), "--ci"])[0] == 1


def test_stale_active_row_is_snapshot_stale_and_inconclusive(rows, tmp_path):
    report = migrate.build_report(_write(tmp_path, [_m("staleact")]), TODAY)
    assert _entry(report, "staleact")["outcome"] == "snapshot_stale"
    assert report["decision"] == "inconclusive"


def test_retired_replacement_is_unusable(rows, tmp_path):
    entry = _entry(
        migrate.build_report(_write(tmp_path, [_m("chain-dead")]), TODAY),
        "chain-dead",
    )
    assert entry["outcome"] == "replacement_unusable"
    assert entry["replacement_status"] == "retired"


def test_unusable_replacement_wins_over_listed_and_headers(rows, tmp_path):
    path = _write(tmp_path, [_m("chain-old", headers={"a": "b"}), _m("dying")])
    assert _entry(migrate.build_report(path, TODAY), "chain-old")["outcome"] == (
        "replacement_unusable"
    )


def test_listed_replacement_wins_over_headers(rows, tmp_path):
    path = _write(tmp_path, [_m("old", headers={"a": "b"}), _m("new")])
    assert _entry(migrate.build_report(path, TODAY), "old")["outcome"] == (
        "replacement_in_config"
    )


def test_listed_replacement_matches_prefixed_id_and_same_provider(rows, tmp_path):
    path = _write(tmp_path, [_m("old"), _m("vendor/new")])
    assert _entry(migrate.build_report(path, TODAY), "old")["outcome"] == (
        "replacement_in_config"
    )
    path = _write(tmp_path, [_m("old"), _m("new", provider="gemini")])
    assert _entry(migrate.build_report(path, TODAY), "old")["outcome"] == "candidate"


def test_missing_provider_defaults_to_openai_compatible(rows, tmp_path):
    path = _write(tmp_path, [{"model": "legacy"}, {"model": "new"}])
    entry = _entry(migrate.build_report(path, TODAY), "legacy")
    assert entry["provider"] == "openai_compatible"
    assert entry["outcome"] == "replacement_in_config"
    path = _write(tmp_path, [{"model": "legacy"}, _m("new")])
    assert _entry(migrate.build_report(path, TODAY), "legacy")["outcome"] == (
        "candidate"
    )


def test_snapshot_stale_does_not_report_replacement_active(
    rows, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("stale-old")])
    entry = _entry(migrate.build_report(path, TODAY), "stale-old")
    assert entry["replacement"] == "new"
    assert entry["replacement_status"] is None
    _, out = _run(monkeypatch, capsys, [str(path)])
    assert "(active)" not in out.out


def test_text_prints_retirement_date_and_source(rows, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("cand")])
    _, out = _run(monkeypatch, capsys, [str(path)])
    assert "Date: 2026-10-01" in out.out
    assert f"Source: {URL}" in out.out


GW = "https://gw.example/v1"


def test_custom_base_url_row_stops(rows, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("cand", base_url=GW)])
    report = migrate.build_report(path, TODAY)
    entry = _entry(report, "cand")
    assert entry["outcome"] == "route_base_url"
    assert entry["replacement"] == "fresh"
    assert "--quick" not in entry["next_step"]
    assert entry["next_step"] == (
        "the provider names fresh for its public route, but this row sets a custom "
        "base_url; check that your route serves fresh, add it to this config by "
        "hand with your own prices, then run --dry-run on this config"
    )
    _, out = _run(monkeypatch, capsys, [str(path)])
    _, js = _run(monkeypatch, capsys, [str(path), "--json"])
    assert GW not in out.out + js.out


@pytest.mark.parametrize(
    "model, decision, plain, ci",
    [("cand", "fail", 0, 1), ("soon", "inconclusive", 0, 3)],
)
def test_custom_base_url_keeps_verdict_decision_and_exit(
    rows, tmp_path, monkeypatch, capsys, model, decision, plain, ci
):
    path = _write(tmp_path, [_m(model, base_url=GW)])
    report = migrate.build_report(path, TODAY)
    assert _entry(report, model)["outcome"] == "route_base_url"
    assert report["decision"] == decision
    assert _run(monkeypatch, capsys, [str(path)])[0] == plain
    assert _run(monkeypatch, capsys, [str(path), "--ci"])[0] == ci


def test_stale_custom_base_url_row_reports_snapshot_stale(rows, tmp_path):
    path = _write(tmp_path, [_m("stale-old", base_url=GW)])
    assert _entry(migrate.build_report(path, TODAY), "stale-old")["outcome"] == (
        "snapshot_stale"
    )


def test_public_base_url_with_trailing_slash_is_not_custom(rows, tmp_path):
    path = _write(tmp_path, [_m("cand", base_url="https://api.openai.com/v1/")])
    assert _entry(migrate.build_report(path, TODAY), "cand")["outcome"] == "candidate"


def test_null_base_url_is_custom_without_crash(rows, tmp_path):
    path = _write(tmp_path, [_m("cand", base_url=None)])
    assert _entry(migrate.build_report(path, TODAY), "cand")["outcome"] == (
        "route_base_url"
    )


def test_custom_api_key_env_only_stays_candidate(rows, tmp_path):
    path = _write(tmp_path, [_m("cand", api_key_env="TEAM_SECRET_NAME")])
    report = migrate.build_report(path, TODAY)
    entry = _entry(report, "cand")
    assert entry["outcome"] == "candidate"
    assert "--quick" in entry["next_step"]
    assert "keep this row's api_key_env" in entry["next_step"]
    assert "TEAM_SECRET_NAME" not in json.dumps(report["models"])
    assert "TEAM_SECRET_NAME" not in json.dumps(report["next_steps"])


def test_default_api_key_env_is_not_custom(rows, tmp_path):
    path = _write(tmp_path, [_m("cand", api_key_env="OPENAI_API_KEY")])
    assert (
        "api_key_env"
        not in _entry(migrate.build_report(path, TODAY), "cand")["next_step"]
    )


def test_replacement_on_other_base_url_is_not_in_config(rows, tmp_path):
    path = _write(tmp_path, [_m("cand", base_url=GW), _m("fresh")])
    assert _entry(migrate.build_report(path, TODAY), "cand")["outcome"] == (
        "route_base_url"
    )
    path = _write(tmp_path, [_m("cand"), _m("fresh", base_url=GW)])
    assert _entry(migrate.build_report(path, TODAY), "cand")["outcome"] == "candidate"


def test_replacement_on_same_custom_base_url_is_in_config(rows, tmp_path):
    path = _write(tmp_path, [_m("cand", base_url=GW), _m("fresh", base_url=GW + "/")])
    entry = _entry(migrate.build_report(path, TODAY), "cand")
    assert entry["outcome"] == "replacement_in_config"
    assert entry["next_step"] == (
        "fresh is already in this config; run --dry-run on this config"
    )


def test_route_headers_next_step_has_no_quick_command(rows, tmp_path):
    path = _write(tmp_path, [_m("hdr", headers={"X-Team": "a"})])
    entry = _entry(migrate.build_report(path, TODAY), "hdr")
    assert entry["next_step"] == (
        "this row sets custom headers that are not copied; add fresh by hand, "
        "then run --dry-run on this config"
    )


def test_base_url_and_headers_row_reports_route_base_url(rows, tmp_path):
    path = _write(tmp_path, [_m("cand", base_url=GW, headers={"X-Team": "a"})])
    assert _entry(migrate.build_report(path, TODAY), "cand")["outcome"] == (
        "route_base_url"
    )


def test_alias_carrying_base_url_stops(rows, tmp_path):
    path = _write(tmp_path, ["gw"], aliases={"gw": _m("cand", base_url=GW)})
    assert _entry(migrate.build_report(path, TODAY), "cand")["outcome"] == (
        "route_base_url"
    )


KEY = "sk-" + "A1b2C3d4E5f6G7h8"


def test_key_shaped_model_is_redacted_in_text_and_json(
    rows, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m(KEY)])
    for flags in ([], ["--json"], ["--ci"]):
        out = _run(monkeypatch, capsys, [str(path), *flags])[1].out
        assert KEY not in out
        assert "[REDACTED]" in out


def test_json_output_is_ascii_safe_for_non_ascii_model(
    rows, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("modèle-ü")])
    out = _run(monkeypatch, capsys, [str(path), "--json", "--ci"])[1].out
    assert out.isascii()
    assert json.loads(out)["models"][0]["model"] == "modèle-ü"


def test_control_characters_in_model_are_escaped(rows, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("x\nDecision: pass\x1b[31m")])
    out = _run(monkeypatch, capsys, [str(path)])[1].out
    assert [ln for ln in out.splitlines() if ln.startswith("Decision:")] == [
        "Decision: none"
    ]
    assert "\x1b" not in out.replace("\\x1b", "")
    assert all(ch.isprintable() or ch == "\n" for ch in out)


def test_deeply_nested_json_is_a_config_error(rows, tmp_path, monkeypatch, capsys):
    path = tmp_path / "deep.json"
    path.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    assert _run(monkeypatch, capsys, [str(path), "--ci"])[0] == 2
    path.write_text('{"models": [' + "[" * 100000, encoding="utf-8")
    assert _run(monkeypatch, capsys, [str(path), "--ci"])[0] == 2


def test_deep_nesting_beyond_aliases_is_a_config_error(
    rows, tmp_path, monkeypatch, capsys
):
    path = tmp_path / "deep-alias.json"
    nested = "[" * 600 + "]" * 600
    path.write_text(
        '{"aliases": {"main": {"provider": "openai", "model": "cand"}}, '
        f'"models": ["main"], "x": {nested}}}',
        encoding="utf-8",
    )
    for flags in ([], ["--ci"], ["--json"]):
        assert _run(monkeypatch, capsys, [str(path), *flags])[0] == 2


# --- candidate config, plan and approval (slice B) ---------------------------


@pytest.fixture
def priced(rows):
    rows[("openai", "oldp")] = _row(
        "retired", replacement="gpt-5.6-luna", date_="2026-10-01"
    )
    rows[("openai", "oldp2")] = _row(
        "retired", replacement="gpt-5.6-luna", date_="2026-10-01"
    )
    rows[("openai", "gpt-5.6-luna")] = _row("active")
    return rows


def _migrate(monkeypatch, capsys, path, *flags):
    return _run(monkeypatch, capsys, [str(path), *flags])


def test_retired_id_with_named_replacement_reaches_plan(
    priced, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("oldp")])
    target = tmp_path / "migrate.json"
    code, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--json")
    assert code == 0
    report = json.loads(out.out)
    written = json.loads(target.read_text(encoding="utf-8"))
    assert [m["model"] for m in written["models"]] == ["gpt-5.6-luna"]
    assert report["candidate_config"]["path"] == str(target)
    assert report["candidate_config"]["config"] == written
    assert report["plan"]["maximum_estimated_cost_usd"] is not None
    assert [m["model"] for m in report["plan"]["models"]] == ["gpt-5.6-luna"]
    assert report["approval"]["state"] == "missing"
    assert report["paid_requests_made"] == 0
    assert any("--approval-receipt" in step for step in report["next_steps"])
    assert any("--run" in step for step in report["next_steps"])
    assert written["repetitions"] == 1
    assert written["save_responses"] == "failures"


def test_candidate_reloads_with_prompt_file_and_alias(
    priced, tmp_path, monkeypatch, capsys
):
    (tmp_path / "p.txt").write_text("hello", encoding="utf-8")
    path = tmp_path / "bench.json"
    path.write_text(
        json.dumps(
            {
                "name": "bench",
                "prompts": [{"name": "one", "prompt_file": "p.txt"}],
                "aliases": {"legacy": {"provider": "openai", "model": "oldp"}},
                "environments": {"x": {"repetitions": 9}},
                "discovery": [{"provider": "openai"}],
                "models": ["legacy"],
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "migrate.json"
    code, _ = _migrate(monkeypatch, capsys, path, "--output", str(target))
    assert code == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert not {"aliases", "environments", "discovery"} & set(written)
    assert written["prompts"] == [{"name": "one", "prompt_file": "p.txt"}]
    from llm_preflight.runner import load_config

    assert load_config(target)["models"][0]["model"] == "gpt-5.6-luna"


def test_old_model_price_not_carried_to_replacement(
    priced, tmp_path, monkeypatch, capsys
):
    row = _m(
        "oldp",
        base_url="https://api.openai.com/v1/",
        api_key_env="MY_KEY",
        api_version="v9",
        input_cost_per_million=99,
        output_cost_per_million=99,
        max_output_tokens=7,
        capabilities={"x": 1},
    )
    path = _write(tmp_path, [row])
    target = tmp_path / "migrate.json"
    _migrate(monkeypatch, capsys, path, "--output", str(target))
    new = json.loads(target.read_text(encoding="utf-8"))["models"][0]
    assert new == {
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "base_url": "https://api.openai.com/v1/",
        "api_key_env": "MY_KEY",
        "api_version": "v9",
    }


def test_headers_row_stops_and_no_secret_written(rows, tmp_path, monkeypatch, capsys):
    secret = "sk-SECRETVALUE123"
    path = _write(
        tmp_path,
        [_m("hdr", headers={"Authorization": f"Bearer {secret}"}), _m("cand")],
        note=f"key {secret}",
    )
    target = tmp_path / "migrate.json"
    code, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--json")
    assert code == 0
    assert secret not in out.out
    written = target.read_text(encoding="utf-8")
    assert secret not in written and "Authorization" not in written
    assert [m["model"] for m in json.loads(written)["models"]] == ["fresh"]
    report = json.loads(out.out)
    assert any("redact" in w.lower() for w in report["warnings"])


def test_two_models_same_replacement_one_row(priced, tmp_path, monkeypatch, capsys):
    path = _write(
        tmp_path,
        [_m("oldp", api_key_env="KEY_A"), _m("oldp2", api_key_env="KEY_B")],
    )
    target = tmp_path / "migrate.json"
    _, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--json")
    rows_ = json.loads(target.read_text(encoding="utf-8"))["models"]
    assert [(r["model"], r["api_key_env"]) for r in rows_] == [
        ("gpt-5.6-luna", "KEY_A")
    ]
    warnings = json.loads(out.out)["warnings"]
    assert any("KEY_A" in w and "KEY_B" in w for w in warnings)


def test_same_replacement_same_key_is_deduplicated_silently(
    priced, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("oldp"), _m("oldp2")])
    target = tmp_path / "migrate.json"
    _, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--json")
    assert len(json.loads(target.read_text(encoding="utf-8"))["models"]) == 1
    assert json.loads(out.out)["warnings"] == []


def test_existing_output_needs_replace(priced, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("oldp")])
    target = tmp_path / "migrate.json"
    target.write_text("keep", encoding="utf-8")
    code, out = _migrate(monkeypatch, capsys, path, "--output", str(target))
    assert code == 2
    assert target.read_text(encoding="utf-8") == "keep"
    assert "--replace" in out.err
    code, _ = _migrate(monkeypatch, capsys, path, "--output", str(target), "--replace")
    assert code == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["models"][0]["model"] == "gpt-5.6-luna"


def test_output_outside_config_dir_rejected(priced, tmp_path, monkeypatch, capsys):
    sub = tmp_path / "sub"
    sub.mkdir()
    path = _write(sub, [_m("oldp")])
    for target in (tmp_path / "out.json", sub / "nested" / "out.json"):
        code, out = _migrate(monkeypatch, capsys, path, "--output", str(target))
        assert code == 2
        assert "directory" in out.err
        assert not target.exists()


def test_output_cannot_be_the_source_config(priced, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("oldp")])
    before = path.read_bytes()
    code, _ = _migrate(monkeypatch, capsys, path, "--output", str(path), "--replace")
    assert code == 2
    assert path.read_bytes() == before


def test_without_output_nothing_is_written_and_plan_is_absent(
    priced, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("oldp")])
    listing = sorted(p.name for p in tmp_path.iterdir())
    code, out = _migrate(monkeypatch, capsys, path, "--json")
    report = json.loads(out.out)
    assert code == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == listing
    assert report["candidate_config"]["path"] is None
    assert report["plan"] is None
    assert any("--output" in step for step in report["next_steps"])


def test_no_candidate_row_writes_nothing(rows, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("norepl")])
    target = tmp_path / "migrate.json"
    _, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--json")
    assert not target.exists()
    report = json.loads(out.out)
    assert report["candidate_config"] is None
    assert report["plan"] is None


def test_unpriced_replacement_is_unbounded(rows, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("cand")])
    target = tmp_path / "migrate.json"
    _, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--json")
    report = json.loads(out.out)
    assert report["plan"]["maximum_estimated_cost_usd"] is None
    assert any("unbounded" in step.lower() for step in report["next_steps"])


def test_custom_base_url_never_reaches_candidate(priced, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("oldp", base_url="https://gw.example/v1"), _m("oldp2")])
    target = tmp_path / "migrate.json"
    _migrate(monkeypatch, capsys, path, "--output", str(target))
    assert "gw.example" not in target.read_text(encoding="utf-8")


def test_text_report_shows_candidate_plan_and_approval(
    priced, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("oldp")])
    target = tmp_path / "migrate.json"
    _, out = _migrate(monkeypatch, capsys, path, "--output", str(target))
    assert f"Candidate config: {target}" in out.out
    assert "Plan:" in out.out
    assert "Approval: missing" in out.out
    assert "--approval-receipt" in out.out and "--run" in out.out


def test_replace_without_output_is_usage_error(priced, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("oldp")])
    code, _ = _migrate(monkeypatch, capsys, path, "--replace")
    assert code == 2


def _out(monkeypatch, capsys, path, target, *flags):
    return _migrate(monkeypatch, capsys, path, "--output", str(target), *flags)


def test_second_replacement_already_in_config_reaches_plan(
    priced, tmp_path, monkeypatch, capsys
):
    priced[("openai", "oldq")] = _row(
        "retired", replacement="gpt-5.6-terra", date_="2026-10-01"
    )
    path = _write(
        tmp_path,
        [_m("oldp"), _m("oldq"), _m("gpt-5.6-terra", api_key_env="OWN", extra_x=1)],
    )
    target = tmp_path / "migrate.json"
    _, out = _out(monkeypatch, capsys, path, target, "--json")
    written = json.loads(target.read_text(encoding="utf-8"))["models"]
    assert [m["model"] for m in written] == ["gpt-5.6-luna", "gpt-5.6-terra"]
    assert written[1] == _m("gpt-5.6-terra", api_key_env="OWN", extra_x=1)
    assert [m["model"] for m in json.loads(out.out)["plan"]["models"]] == [
        "gpt-5.6-luna",
        "gpt-5.6-terra",
    ]


def test_priced_own_row_for_unpriced_replacement_reaches_plan(
    rows, tmp_path, monkeypatch, capsys
):
    own = _m("fresh", input_cost_per_million=1, output_cost_per_million=2)
    path = _write(tmp_path, [_m("cand"), own])
    target = tmp_path / "migrate.json"
    code, out = _out(monkeypatch, capsys, path, target, "--json")
    report = json.loads(out.out)
    assert code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["models"] == [own]
    assert report["plan"]["maximum_estimated_cost_usd"] is not None


def test_own_row_with_headers_is_not_written(rows, tmp_path, monkeypatch, capsys):
    own = _m("fresh", headers={"X-Team": "a"})
    path = _write(
        tmp_path, [_m("cand"), own, _m("cand", base_url="https://gw.example/v1")]
    )
    target = tmp_path / "migrate.json"
    _, out = _out(monkeypatch, capsys, path, target, "--json")
    assert not target.exists()
    assert any("headers" in w for w in json.loads(out.out)["warnings"])


def test_non_string_name_is_a_config_error(priced, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("oldp")], name=123)
    for flags in ([], ["--ci"], ["--output", str(tmp_path / "o.json")]):
        assert _migrate(monkeypatch, capsys, path, *flags)[0] == 2
    assert not (tmp_path / "o.json").exists()


def test_unbounded_step_and_no_none_in_text(rows, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("cand")])
    target = tmp_path / "migrate.json"
    _, out = _out(monkeypatch, capsys, path, target)
    assert "None" not in out.out
    assert migrate._UNBOUNDED_STEP in out.out


def test_invalid_candidate_leaves_no_file_and_keeps_the_old_one(
    priced, tmp_path, monkeypatch, capsys
):
    path = tmp_path / "bench.json"
    path.write_text(json.dumps({"name": "b", "models": [_m("oldp")]}), encoding="utf-8")
    target = tmp_path / "migrate.json"
    code, _ = _out(monkeypatch, capsys, path, target)
    assert code == 2 and not target.exists()
    target.write_text("keep", encoding="utf-8")
    code, _ = _out(monkeypatch, capsys, path, target, "--replace")
    assert code == 2
    assert target.read_text(encoding="utf-8") == "keep"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bench.json", "migrate.json"]


def test_key_warning_names_provider_default(priced, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("oldp"), _m("oldp2", api_key_env="K_B")])
    _, out = _out(monkeypatch, capsys, path, tmp_path / "m.json", "--json")
    warning = json.loads(out.out)["warnings"][0]
    assert "None" not in warning and "provider default" in warning and "K_B" in warning


@pytest.mark.parametrize(
    "url, secret",
    [
        ("https://u:PASSWD123@gw.example/v1", "PASSWD123"),
        ("https://gw.example/v1?api_key=QKEY456", "QKEY456"),
        ("https://gw.example/v1#FRAG789", "FRAG789"),
        ("https://gw.internal.example/tenant-PATHTOK/v1", "PATHTOK"),
        ("https://gw.example/v1;k=SEMIK", "SEMIK"),
        ("gw.example/PLAINTOK/v1", "PLAINTOK"),
        (None, "None"),
        (5, "5"),
    ],
)
def test_own_row_with_custom_url_is_not_written_or_printed(
    rows, tmp_path, monkeypatch, capsys, url, secret
):
    path = _write(tmp_path, [_m("cand", base_url=url), _m("fresh", base_url=url)])
    target = tmp_path / "migrate.json"
    for flags in ([], ["--output", str(target)]):
        _, out = _migrate(monkeypatch, capsys, path, "--json", *flags)
        report = json.loads(out.out)
        assert secret not in json.dumps(report["warnings"] + report["next_steps"])
        if isinstance(url, str):
            assert secret not in out.out
        assert any("custom base_url" in w for w in report["warnings"])
        assert report["candidate_config"] is None and report["plan"] is None
    assert not target.exists()


@pytest.mark.parametrize("gateway_first", [False, True])
def test_one_row_per_replacement_across_routes(
    priced, tmp_path, monkeypatch, capsys, gateway_first
):
    priced[("openai", "oldq")] = _row(
        "retired", replacement="gpt-5.6-luna", date_="2026-10-01"
    )
    gw = "https://gw.example/tenant-PATHTOK/v1"
    models = [_m("oldq", base_url=gw), _m("gpt-5.6-luna", base_url=gw)]
    models = [*models, _m("oldp")] if gateway_first else [_m("oldp"), *models]
    path = _write(tmp_path, models)
    target = tmp_path / "migrate.json"
    _, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--json")
    report = json.loads(out.out)
    written = json.loads(target.read_text(encoding="utf-8"))["models"]
    assert [m["model"] for m in written] == ["gpt-5.6-luna"]
    assert "base_url" not in written[0]
    assert [m["model"] for m in report["plan"]["models"]] == ["gpt-5.6-luna"]
    assert "PATHTOK" not in out.out and "PATHTOK" not in target.read_text("utf-8")
    assert report["warnings"] == [
        (
            "gpt-5.6-luna sets a custom base_url, which is not copied; add it to a "
            "candidate config by hand"
        )
    ]


def test_custom_base_url_never_reaches_own_row_path_token(
    priced, tmp_path, monkeypatch, capsys
):
    gw = "https://gw.internal.example/tenant-abc/v1"
    path = _write(
        tmp_path,
        [
            _m("oldp", base_url=gw),
            _m("gpt-5.6-luna", base_url=gw, input_cost_per_million=1),
        ],
    )
    target = tmp_path / "migrate.json"
    for flags in ([], ["--output", str(target)]):
        _, out = _migrate(monkeypatch, capsys, path, "--json", *flags)
        assert "tenant-abc" not in out.out
    assert not target.exists()


def test_own_public_row_is_still_written(priced, tmp_path, monkeypatch, capsys):
    own = _m(
        "gpt-5.6-luna",
        base_url="https://api.openai.com/v1/",
        input_cost_per_million=1,
        output_cost_per_million=2,
    )
    path = _write(tmp_path, [_m("oldp"), own])
    target = tmp_path / "migrate.json"
    _migrate(monkeypatch, capsys, path, "--output", str(target))
    assert json.loads(target.read_text(encoding="utf-8"))["models"] == [own]


@pytest.mark.parametrize("status, plain, ci", [("retired", 0, 1), ("deprecated", 0, 3)])
def test_custom_own_row_keeps_outcome_and_decision(
    rows, tmp_path, monkeypatch, capsys, status, plain, ci
):
    rows[("openai", "src")] = _row(
        status,
        replacement="dest",
        date_="2027-01-14" if status != "retired" else "2026-10-01",
    )
    rows[("openai", "dest")] = _row("active")
    gw = "https://gw.example/v1"
    path = _write(tmp_path, [_m("src", base_url=gw), _m("dest", base_url=gw)])
    target = tmp_path / "migrate.json"
    args = ["--output", str(target), "--json"]
    code, out = _migrate(monkeypatch, capsys, path, *args)
    assert code == plain
    assert json.loads(out.out)["models"][0]["outcome"] == "replacement_in_config"
    assert _migrate(monkeypatch, capsys, path, *args, "--ci")[0] == ci


def test_only_custom_own_row_writes_nothing(priced, tmp_path, monkeypatch, capsys):
    gw = "https://gw.example/v1"
    path = _write(tmp_path, [_m("oldp", base_url=gw), _m("gpt-5.6-luna", base_url=gw)])
    target = tmp_path / "migrate.json"
    target.write_text("keep", encoding="utf-8")
    code, _ = _migrate(monkeypatch, capsys, path, "--output", str(target), "--replace")
    assert code == 0
    assert target.read_bytes() == b"keep"


def test_top_level_base_url_not_copied(priced, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("oldp")], base_url="https://gw.example/TOPTOK")
    target = tmp_path / "migrate.json"
    _, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--json")
    assert "TOPTOK" not in target.read_text(encoding="utf-8")
    assert "TOPTOK" not in out.out


def test_row_warning_appears_once(priced, tmp_path, monkeypatch, capsys):
    priced[("openai", "oldq")] = _row(
        "retired", replacement="gpt-5.6-luna", date_="2026-10-01"
    )
    gw = "https://gw.example/v1"
    path = _write(
        tmp_path,
        [
            _m("oldp", base_url=gw),
            _m("oldq", base_url=gw),
            _m("gpt-5.6-luna", base_url=gw),
        ],
    )
    _, out = _migrate(monkeypatch, capsys, path, "--json")
    warnings = json.loads(out.out)["warnings"]
    assert len(warnings) == len(set(warnings)) == 1


def test_redacted_structure_stops_with_output(priced, tmp_path, monkeypatch, capsys):
    target = tmp_path / "migrate.json"
    target.write_text("keep", encoding="utf-8")
    for extra in (
        {"request": {"response_format": {"properties": {"token": {"type": "string"}}}}},
        {
            "validation": {
                "json_schema": {"properties": {"password": {"type": "string"}}}
            }
        },
    ):
        path = _write(tmp_path, [_m("oldp")], **extra)
        code, out = _migrate(
            monkeypatch, capsys, path, "--output", str(target), "--replace"
        )
        assert code == 2
        assert "token" in out.err or "password" in out.err
        assert target.read_bytes() == b"keep"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bench.json", "migrate.json"]


def test_redacted_structure_keeps_verdict_without_output(
    priced, tmp_path, monkeypatch, capsys
):
    extra = {"request": {"response_format": {"properties": {"token": {"type": "x"}}}}}
    path = _write(tmp_path, [_m("oldp")], **extra)
    code, out = _migrate(monkeypatch, capsys, path, "--ci", "--json")
    report = json.loads(out.out)
    assert code == 1 and report["decision"] == "fail"
    assert report["candidate_config"] is None
    assert any(
        "request.response_format.properties.token" in w for w in report["warnings"]
    )


def test_redacted_string_still_warns(rows, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("cand")], note="key sk-ABCDEF123456")
    target = tmp_path / "migrate.json"
    code, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--json")
    assert code == 0 and target.exists()
    assert any("redacted" in w for w in json.loads(out.out)["warnings"])


@pytest.mark.parametrize(
    "extra",
    [{"presets": 5}, {"prompt": 5}, {"profiles": 5}, {"request": 5}],
)
def test_wrong_typed_config_in_plan_step_exits_2(
    priced, tmp_path, monkeypatch, capsys, extra
):
    path = _write(tmp_path, [_m("oldp")], **extra)
    target = tmp_path / "migrate.json"
    for flags in (["--output", str(target)], ["--output", str(target), "--ci"]):
        code, out = _migrate(monkeypatch, capsys, path, *flags)
        assert code == 2 and "Traceback" not in out.err
    assert not target.exists()


def test_wrong_typed_own_row_in_plan_step_exits_2(
    priced, tmp_path, monkeypatch, capsys
):
    own = _m("gpt-5.6-luna", capabilities=5)
    path = _write(tmp_path, [_m("oldp"), own])
    target = tmp_path / "migrate.json"
    code, _ = _migrate(monkeypatch, capsys, path, "--output", str(target), "--ci")
    assert code == 2 and not target.exists()


def test_same_replacement_different_api_version_warns(
    priced, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("oldp"), _m("oldp2", api_version="v2")])
    _, out = _migrate(monkeypatch, capsys, path, "--json")
    warning = json.loads(out.out)["warnings"][0]
    assert (
        "api_version" in warning and "provider default" in warning and "v2" in warning
    )


def test_output_hard_link_to_source_rejected(priced, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("oldp")])
    link = tmp_path / "Bench-link.json"
    link.hardlink_to(path)
    before = path.read_bytes()
    code, _ = _migrate(monkeypatch, capsys, path, "--output", str(link), "--replace")
    assert code == 2
    assert path.read_bytes() == before


# --- --run: approved bounded smoke --------------------------------------------

PASS = {"state": "pass", "reason": "ok"}


def _main(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["llm-preflight", *argv])
    try:
        cli.main()
        code = 0
    except SystemExit as exc:
        code = exc.code
    return code, capsys.readouterr()


@pytest.fixture
def spend(monkeypatch):
    """Count every provider call and env load; the fake smoke passes."""
    calls = {
        "benchmark": 0,
        "env": 0,
        "decision": PASS,
        "samples": [{"ok": True, "attempts": 1}, {"ok": True}],
    }

    def benchmark(config, **kwargs):
        calls["benchmark"] += 1
        return {
            "decision": dict(calls["decision"]),
            "models": [{"samples": list(calls["samples"])}],
        }

    def load_env(path):
        calls["env"] += 1
        return set()

    monkeypatch.setattr(cli, "run_benchmark", benchmark)
    monkeypatch.setattr(cli, "load_env_file", load_env)
    monkeypatch.setattr(cli, "redact_result", lambda result: result)
    monkeypatch.setattr(cli, "save_result", lambda result, out: out / "saved.json")
    return calls


def _none_spent(spend):
    return spend["benchmark"] == 0 and spend["env"] == 0


def _setup(monkeypatch, capsys, tmp_path, models, **extra):
    path = _write(tmp_path, models, **extra)
    target = tmp_path / "migrate.json"
    receipt = tmp_path / "migrate.approval.json"
    _migrate(monkeypatch, capsys, path, "--output", str(target))
    return path, target, receipt


def _record(spend, monkeypatch, capsys, target, receipt, *flags):
    code, out = _main(
        monkeypatch,
        capsys,
        [
            str(target),
            "--dry-run",
            "--approval-receipt",
            str(receipt),
            "--approval-note",
            "reviewed",
            "--approval-expires-at",
            "2099-01-01T00:00:00+00:00",
            *flags,
        ],
    )
    assert code == 0, out.err
    spend["env"] = 0


def _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, *flags):
    return _migrate(
        monkeypatch,
        capsys,
        path,
        "--output",
        str(target),
        "--run",
        "--verify-approval-receipt",
        str(receipt),
        "--output-dir",
        str(tmp_path / "res"),
        *flags,
    )


def _edit(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_run_without_receipt_ends_at_plan_and_names_approval(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, _receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    code, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--run")
    assert code == 1  # a retired model is still unresolved
    assert "Approval: missing" in out.out
    assert "--approval-receipt" in out.out
    assert _none_spent(spend)


def test_run_without_output_is_usage_error(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("oldp")])
    code, _ = _migrate(monkeypatch, capsys, path, "--run")
    assert code == 2 and _none_spent(spend)


def test_run_with_recorded_receipt_runs_smoke_once_and_reports(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    _record(spend, monkeypatch, capsys, target, receipt)
    code, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    report = json.loads(out.out)
    assert code == 0 and spend["benchmark"] == 1
    assert report["approval"]["state"] == "recorded"
    assert report["smoke"]["state"] == "pass"
    assert report["paid_requests_made"] == 2
    assert report["decision"] == "pass"
    assert report["models"][0]["smoke"] == {"state": "pass"}


def _case_expired(target, receipt):
    _edit(receipt, lambda d: d.update(expires_at="2000-01-01T00:00:00+00:00"))


def _case_mismatch(target, receipt):
    _edit(receipt, lambda d: d.update(plan_sha256="0" * 64))


def _case_invalid(target, receipt):
    receipt.write_text("{not json", encoding="utf-8")


def _case_overflow_expiry(target, receipt):
    _edit(receipt, lambda d: d.update(expires_at="0001-01-01T00:00:00+23:59"))


def _case_bounds(target, receipt):
    bounds = {"possible_requests": 1, "maximum_estimated_cost_usd": 9}
    _edit(receipt, lambda d: d.update(bounds=bounds))


def _case_candidate_changed(target, receipt):
    _edit(target, lambda d: d.update(repetitions=3))


@pytest.mark.parametrize(
    "state, tamper",
    [
        ("missing", None),
        ("expired", _case_expired),
        ("mismatch", _case_mismatch),
        ("invalid", _case_invalid),
        ("invalid", _case_overflow_expiry),
        ("mismatch", _case_bounds),
        ("candidate_changed", _case_candidate_changed),
    ],
)
def test_no_provider_call_or_env_load_unless_gate_passes(
    priced, spend, tmp_path, monkeypatch, capsys, state, tamper
):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    if state != "missing":
        _record(spend, monkeypatch, capsys, target, receipt)
    if tamper:
        tamper(target, receipt)
    code, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    report = json.loads(out.out)
    assert report["approval"]["state"] == state
    assert report["smoke"] is None and report["paid_requests_made"] == 0
    assert code == 1 and _none_spent(spend)


def test_unbounded_plan_never_runs(rows, spend, tmp_path, monkeypatch, capsys):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("cand")])
    _record(spend, monkeypatch, capsys, target, receipt)
    _, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    assert json.loads(out.out)["approval"]["state"] == "unbounded"
    assert _none_spent(spend)


def test_receipt_without_run_only_reports_state(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    _record(spend, monkeypatch, capsys, target, receipt)
    _, out = _migrate(
        monkeypatch,
        capsys,
        path,
        "--output",
        str(target),
        "--verify-approval-receipt",
        str(receipt),
        "--json",
    )
    report = json.loads(out.out)
    assert report["approval"]["state"] == "recorded"
    assert report["smoke"] is None and _none_spent(spend)


def test_verify_receipt_without_output_is_usage_error(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("oldp")])
    code, _ = _migrate(
        monkeypatch, capsys, path, "--verify-approval-receipt", str(tmp_path / "r")
    )
    assert code == 2


def test_budget_excess_stops_before_run(priced, spend, tmp_path, monkeypatch, capsys):
    path, target, receipt = _setup(
        monkeypatch,
        capsys,
        tmp_path,
        [_m("oldp")],
        max_estimated_cost_usd=0.0000001,
    )
    _record(spend, monkeypatch, capsys, target, receipt)
    code, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert code == 2 and "exceeds" in out.err
    assert _none_spent(spend)


def test_receipt_from_documented_command_verifies_in_migrate(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("oldp")])
    target = tmp_path / "migrate.json"
    _, out = _migrate(monkeypatch, capsys, path, "--output", str(target), "--json")
    approval = json.loads(out.out)["approval"]
    command = approval["record_command"].replace(
        "<ISO-8601 time with timezone>", "2099-01-01T00:00:00+00:00"
    )
    record = shlex.split(command)[1:]
    record[record.index("--approval-note") + 1] = "reviewed"
    code, out = _main(monkeypatch, capsys, record)
    assert code == 0, out.err
    run = shlex.split(approval["run_command"])[1:]
    code, _ = _main(monkeypatch, capsys, [*run, "--output-dir", str(tmp_path / "r")])
    assert code == 0 and spend["benchmark"] == 1


def test_smoke_flag_on_candidate_keeps_receipt_valid(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    _record(spend, monkeypatch, capsys, target, receipt, "--smoke")
    code, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    assert json.loads(out.out)["approval"]["state"] == "recorded"
    assert code == 0 and spend["benchmark"] == 1


def test_changed_retry_settings_invalidate_receipt(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    _record(spend, monkeypatch, capsys, target, receipt)
    _edit(path, lambda d: d.update(request={"retry": {"max_attempts": 4}}))
    _migrate(monkeypatch, capsys, path, "--output", str(target), "--replace")
    _, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    assert json.loads(out.out)["approval"]["state"] == "mismatch"
    assert _none_spent(spend)


def test_run_accepts_existing_output_without_replace_and_never_writes(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    before = target.read_bytes()
    code, _ = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert code == 1 and target.read_bytes() == before


def test_replace_cannot_combine_with_run(priced, spend, tmp_path, monkeypatch, capsys):
    path, target, _ = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    code, _ = _migrate(
        monkeypatch, capsys, path, "--output", str(target), "--run", "--replace"
    )
    assert code == 2


def test_prompts_only_config_says_to_select_a_prompt(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path = tmp_path / "bench.json"
    config = {
        "name": "b",
        "prompts": [{"name": "a", "prompt": "hi"}],
        "models": [_m("oldp")],
    }
    path.write_text(json.dumps(config), encoding="utf-8")
    target = tmp_path / "migrate.json"
    receipt = tmp_path / "r.json"
    _, out = _migrate(monkeypatch, capsys, path, "--output", str(target))
    assert "select a custom prompt before running the benchmark" in out.out
    _record(spend, monkeypatch, capsys, target, receipt)
    code, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert code == 2 and "select a custom prompt" in out.err
    assert _none_spent(spend)


@pytest.mark.parametrize(
    "model, plain, strict", [("old", 0, 1), ("soon", 0, 3), ("fine", 0, 0)]
)
def test_exit_codes_table_plain_and_ci(
    rows, spend, tmp_path, monkeypatch, capsys, model, plain, strict
):
    path = _write(tmp_path, [_m(model)])
    assert _migrate(monkeypatch, capsys, path)[0] == plain
    assert _migrate(monkeypatch, capsys, path, "--ci")[0] == strict


@pytest.mark.parametrize(
    "state, expected", [("pass", 0), ("fail", 1), ("inconclusive", 3)]
)
def test_exit_codes_table_run(
    priced, spend, tmp_path, monkeypatch, capsys, state, expected
):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    _record(spend, monkeypatch, capsys, target, receipt)
    spend["decision"] = {"state": state, "reason": "x"}
    code, _ = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert code == expected


def test_route_base_url_rows_keep_their_decision_after_smoke(
    priced, spend, tmp_path, monkeypatch, capsys
):
    models = [_m("oldp"), _m("old", base_url="https://gw.example/v1")]
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, models)
    _record(spend, monkeypatch, capsys, target, receipt)
    code, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    report = json.loads(out.out)
    by = {m["model"]: m for m in report["models"]}
    assert by["old"]["outcome"] == "route_base_url" and by["old"]["smoke"] is None
    assert by["oldp"]["smoke"] == {"state": "pass"}
    assert report["decision"] == "fail" and code == 1


def test_custom_route_row_with_listed_replacement_keeps_its_decision(
    priced, spend, tmp_path, monkeypatch, capsys
):
    gateway = "https://gw.example/v1"
    models = [
        _m("oldp"),
        _m("oldp2", base_url=gateway),
        _m("gpt-5.6-luna", base_url=gateway),
    ]
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, models)
    _record(spend, monkeypatch, capsys, target, receipt)
    code, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    by = {m["model"]: m for m in json.loads(out.out)["models"]}
    assert by["oldp"]["smoke"] == {"state": "pass"}
    assert by["oldp2"]["smoke"] is None
    assert code == 1


def test_text_report_shows_smoke(priced, spend, tmp_path, monkeypatch, capsys):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    _record(spend, monkeypatch, capsys, target, receipt)
    _, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert "Exit 0 (--run)." in out.out and "Smoke: pass (2 requests)" in out.out


def test_next_pointer_is_text_only(rows, tmp_path, monkeypatch, capsys):
    path = _write(tmp_path, [_m("old")])
    for flag in ("--doctor", "--dry-run"):
        _, out = _main(monkeypatch, capsys, [str(path), flag])
        assert "llm-preflight migrate" in out.out and "--output" in out.out
        _, out = _main(monkeypatch, capsys, [str(path), flag, "--json"])
        assert "llm-preflight migrate" not in out.out
        json.loads(out.out)


def _approved_smoke(spend, monkeypatch, capsys, tmp_path, *flags):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    _record(spend, monkeypatch, capsys, target, receipt)
    return path, target, receipt


def test_next_steps_after_smoke_name_adoption_and_not_a_second_run(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _approved_smoke(spend, monkeypatch, capsys, tmp_path)
    _, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    report = json.loads(out.out)
    steps = " ".join(report["next_steps"]) + report["models"][0]["next_step"]
    assert "record approval" not in steps and "run the smoke" not in steps
    assert "preview it with" not in steps
    assert "your step" in steps and "source config is unchanged" in steps
    _, text = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert "Next: smoke done for gpt-5.6-luna" in text.out


def test_paid_requests_count_attempts_sent_from_real_sample_shape(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _approved_smoke(spend, monkeypatch, capsys, tmp_path)
    spend["samples"] = [{"ok": False, "attempts": 3, "retry_count": 2}]
    _, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    assert json.loads(out.out)["paid_requests_made"] == 3
    spend["samples"] = [
        {
            "ok": False,
            "attempts": 1,
            "error": "environment variable 'K' is not set",
            "failure_category": "credentials",
        }
    ]
    _, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    assert json.loads(out.out)["paid_requests_made"] == 0


def test_candidate_changed_names_the_rewrite_and_not_record_or_run(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _approved_smoke(spend, monkeypatch, capsys, tmp_path)
    _edit(target, lambda d: d.update(repetitions=3))
    _, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    report = json.loads(out.out)
    steps = " ".join(report["next_steps"])
    assert "--replace" in steps and "record approval" not in steps
    assert "run_command" not in report["approval"]
    _, text = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert "nothing was written" in text.out and "--replace" in text.out
    assert "only the candidate config was written" not in text.out


def test_absent_candidate_file_is_named_and_not_claimed_written(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path = _write(tmp_path, [_m("oldp")])
    target = tmp_path / "nofile.json"
    _, out = _migrate(
        monkeypatch, capsys, path, "--output", str(target), "--run", "--json"
    )
    report = json.loads(out.out)
    assert report["approval"]["state"] == "candidate_changed"
    assert "does not exist" in report["approval"]["reason"]
    assert not target.exists() and _none_spent(spend)
    _, text = _migrate(monkeypatch, capsys, path, "--output", str(target), "--run")
    assert "was written" not in text.out.replace("nothing was written", "")


def test_receipt_check_text_does_not_claim_a_write(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _approved_smoke(spend, monkeypatch, capsys, tmp_path)
    _, out = _migrate(
        monkeypatch,
        capsys,
        path,
        "--output",
        str(target),
        "--verify-approval-receipt",
        str(receipt),
    )
    assert "nothing was written" in out.out


@pytest.mark.parametrize(
    "key, value", [("max_requests", []), ("max_estimated_cost_usd", {})]
)
def test_wrong_typed_budget_setting_is_a_config_error(
    priced, spend, tmp_path, monkeypatch, capsys, key, value
):
    path, target, receipt = _setup(monkeypatch, capsys, tmp_path, [_m("oldp")])
    _record(spend, monkeypatch, capsys, target, receipt)
    _edit(path, lambda d: d.update({key: value}))
    _migrate(monkeypatch, capsys, path, "--output", str(target), "--replace")
    _record(spend, monkeypatch, capsys, target, receipt, "--replace-approval-receipt")
    code, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert code == 2 and "Traceback" not in out.err and _none_spent(spend)


def test_keyboard_interrupt_during_smoke_exits_130(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _approved_smoke(spend, monkeypatch, capsys, tmp_path)

    def interrupted(config, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_benchmark", interrupted)
    code, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert code == 130 and "Benchmark cancelled" in out.err


@pytest.mark.parametrize(
    "state, adopts", [("pass", True), ("fail", False), ("inconclusive", False)]
)
def test_adoption_step_only_after_a_pass(
    priced, spend, tmp_path, monkeypatch, capsys, state, adopts
):
    path, target, receipt = _approved_smoke(spend, monkeypatch, capsys, tmp_path)
    spend["decision"] = {"state": state, "reason": "contract broke"}
    _, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt, "--json")
    report = json.loads(out.out)
    steps = " ".join(report["next_steps"]) + report["models"][0]["next_step"]
    assert "record approval" not in steps and "run the smoke" not in steps
    if adopts:
        assert "your step" in steps
    else:
        assert "your step" not in steps
        assert "contract broke" in steps and "saved.json" in steps
        assert "do not adopt" in steps
    _, text = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert ("smoke done" in text.out) is adopts
    assert "only the smoke result files were written" in text.out


def _real_samples(monkeypatch, answers, key_set=True):
    """Samples from the real client with the network answering `answers`."""
    import io
    import urllib.error

    from llm_preflight import client

    codes = iter(answers)

    def refuse(request, timeout=None):
        code = next(codes)
        raise urllib.error.HTTPError(request.full_url, code, "x", {}, io.BytesIO(b"no"))

    monkeypatch.setattr(client, "open_public_url", refuse)
    monkeypatch.setattr(client, "require_http_url", lambda url, **_: None)
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    monkeypatch.setenv("MIGRATE_TEST_KEY", "k") if key_set else monkeypatch.delenv(
        "MIGRATE_TEST_KEY", raising=False
    )
    model = {
        "provider": "openai",
        "model": "m",
        "base_url": "https://api.example.test/v1",
        "api_key_env": "MIGRATE_TEST_KEY",
    }
    options = {"retry": {"max_attempts": 3}}
    sample = client.create_client(model, 5).run("hi", options)
    return [sample]


@pytest.mark.parametrize(
    "answers, key_set, sent",
    [([401], True, 1), ([403], True, 1), ([429, 429, 401], True, 3), ([], False, 0)],
)
def test_paid_requests_from_the_real_client(monkeypatch, answers, key_set, sent):
    samples = _real_samples(monkeypatch, answers, key_set)
    assert sum(migrate._attempts_sent(sample) for sample in samples) == sent


def test_wrong_typed_setting_inside_the_run_is_a_config_error(
    priced, spend, tmp_path, monkeypatch, capsys
):
    path, target, receipt = _approved_smoke(spend, monkeypatch, capsys, tmp_path)

    def broken(config, **kwargs):
        raise TypeError("bad")

    monkeypatch.setattr(cli, "run_benchmark", broken)
    code, out = _smoke(monkeypatch, capsys, tmp_path, path, target, receipt)
    assert code == 2 and "Traceback" not in out.err
