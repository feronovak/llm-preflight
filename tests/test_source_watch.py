import functools
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests/fixtures/source_watch"
PAGE = "https://example.test/pricing"
LIMIT = "https://example.test/limits"
ROUTER = "https://openrouter.ai/api/v1/models"


@functools.cache
def _load():
    spec = importlib.util.spec_from_file_location(
        "source_watch", ROOT / "scripts/source_watch.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sw(monkeypatch):
    module = _load()
    monkeypatch.setattr(
        module,
        "PUBLIC_PRICING",
        {
            ("openai", "gpt-5.6-terra"): (2.0, 12.0, "2026-11-04"),
            ("openai", "gpt-5.6-sol"): (4.0, 20.0, "2026-11-04"),
            ("anthropic", "claude-sonnet-5-5"): (3.0, 15.0, "2026-11-04"),
        },
    )
    monkeypatch.setattr(
        module,
        "PUBLIC_PRICING_SOURCES",
        {
            ("openai", "gpt-5.6-terra"): PAGE,
            ("openai", "gpt-5.6-sol"): PAGE,
            ("anthropic", "claude-sonnet-5-5"): LIMIT,
        },
    )
    monkeypatch.setattr(
        module,
        "PUBLIC_RETIREMENTS",
        {("openai", "gpt-4"): {"source_url": PAGE, "status": "retired"}},
    )
    return module


def _reader(pages=None):
    pages = pages or {}

    def read(url):
        if url == ROUTER:
            return (FIXTURES / "openrouter.json").read_bytes()
        name = pages.get(url, "page_v1.html")
        if name is None:
            raise _load().FetchError("HTTP 503")
        return (FIXTURES / name).read_bytes()

    return read


def _by_type(findings, kind):
    return [f for f in findings if f["type"] == kind]


def test_new_model_on_a_covered_provider(sw):
    findings, _ = sw.run(None, _reader())
    assert [f["key"] for f in _by_type(findings, "new-model")] == [
        "new-model:openai:gpt-9-nova"
    ]


def test_uncovered_provider_free_variant_and_router_are_ignored(sw):
    findings, _ = sw.run(None, _reader())
    text = json.dumps(findings)
    assert "unlisted-lab" not in text
    assert ":free" not in text
    assert "openrouter/auto" not in text


def test_price_signal_when_openrouter_differs(sw):
    findings, _ = sw.run(None, _reader())
    [signal] = _by_type(findings, "price-signal")
    assert signal["key"] == "price-signal:openai:gpt-5.6-sol"
    assert signal["bundled_per_million"] == {"input": 4.0, "output": 20.0}
    assert signal["openrouter_per_million"] == {"input": 5.0, "output": 20.0}


def test_normalised_id_matches_and_equal_price_is_silent(sw):
    keys = {f["key"] for f in sw.run(None, _reader())[0]}
    assert "price-signal:anthropic:claude-sonnet-5-5" not in keys
    assert "new-model:anthropic:claude-sonnet-5.5" not in keys
    assert "price-signal:openai:gpt-5.6-terra" not in keys


def test_first_run_reports_no_page_changes(sw):
    findings, snapshot = sw.run(None, _reader())
    assert _by_type(findings, "page-changed") == []
    assert set(snapshot["pages"]) == {PAGE, LIMIT}


def test_changed_page_reports_excerpt_and_citing_rows(sw):
    _, snapshot = sw.run(None, _reader())
    findings, _ = sw.run(snapshot, _reader({PAGE: "page_v2.html"}))
    [change] = _by_type(findings, "page-changed")
    assert change["key"].startswith(f"page-changed:{PAGE}:")
    lines = change["changed_lines"]
    assert any(line.startswith("- ") and "$3.00" in line for line in lines)
    assert any(line.startswith("+ ") and "$2.50" in line for line in lines)
    assert change["cited_by"] == [
        "pricing openai/gpt-5.6-sol",
        "pricing openai/gpt-5.6-terra",
        "retirement openai/gpt-4",
    ]


def test_unchanged_page_is_silent(sw):
    _, snapshot = sw.run(None, _reader())
    findings, _ = sw.run(snapshot, _reader())
    assert _by_type(findings, "page-changed") == []


def test_fetch_failure_and_bot_wall_are_not_changes(sw):
    _, snapshot = sw.run(None, _reader())
    findings, next_snapshot = sw.run(
        snapshot, _reader({PAGE: None, LIMIT: "botwall.html"})
    )
    assert _by_type(findings, "page-changed") == []
    failed = {f["key"]: f["reason"] for f in _by_type(findings, "fetch-failed")}
    assert failed == {
        f"fetch-failed:{PAGE}": "HTTP 503",
        f"fetch-failed:{LIMIT}": "bot wall",
    }
    assert next_snapshot["pages"] == snapshot["pages"]


def test_first_run_still_reports_fetch_failed(sw):
    findings, _ = sw.run(None, _reader({PAGE: "botwall.html"}))
    assert [f["key"] for f in _by_type(findings, "fetch-failed")] == [
        f"fetch-failed:{PAGE}"
    ]


def test_openrouter_failure_is_reported_not_raised(sw):
    def read(url):
        if url == ROUTER:
            raise sw.FetchError("HTTP 500")
        return (FIXTURES / "page_v1.html").read_bytes()

    findings, _ = sw.run(None, read)
    assert f"fetch-failed:{ROUTER}" in {f["key"] for f in findings}
    assert _by_type(findings, "new-model") == []


def test_main_round_trips_snapshot_with_json_output(sw, tmp_path, capsys):
    snap = tmp_path / "snap.json"
    argv = ["--previous", str(snap), "--write", str(snap), "--json"]
    assert sw.main(argv, _reader()) == 0
    first = json.loads(capsys.readouterr().out)["findings"]
    assert {f["type"] for f in first} == {"new-model", "price-signal"}
    assert sw.main(argv, _reader({PAGE: "page_v2.html"})) == 0
    second = json.loads(capsys.readouterr().out)["findings"]
    assert "page-changed" in {f["type"] for f in second}


def test_main_rejects_a_corrupt_previous_snapshot(sw, tmp_path, capsys):
    snap = tmp_path / "snap.json"
    snap.write_text("{not json")
    assert sw.main(["--previous", str(snap)], _reader()) == 2
    assert "cannot read previous snapshot" in capsys.readouterr().err


def test_cited_urls_cover_the_real_bundle():
    urls = _load().cited_urls()
    assert all(url.startswith("https://") for url in urls)
    assert len(urls) >= 10
