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
        "replacement_unusable", "snapshot_stale", "route_headers", "not_affected",
    }  # fmt: skip
    _, text = _run(monkeypatch, capsys, [str(path)])
    assert f"Decision: {report['decision']}" in text.out
    for entry in report["models"]:
        assert f"{entry['provider']}:{entry['model']}" in text.out
        assert entry["outcome"] in text.out


@pytest.mark.parametrize(
    "model, plain, ci",
    [("fine", 0, 0), ("cand", 0, 1), ("soon", 0, 3)],
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
