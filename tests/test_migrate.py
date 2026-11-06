import json
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
