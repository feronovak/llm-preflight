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
    monkeypatch.setattr(module, "DEPRECATION_URLS", {})
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


def _haiku_findings(sw, monkeypatch, prompt, completion):
    monkeypatch.setattr(
        sw,
        "PUBLIC_PRICING",
        {("anthropic", "claude-haiku-4-5-20251001"): (1.0, 5.0, "2026-11-04")},
    )
    item = {
        "id": "anthropic/claude-haiku-4.5",
        "pricing": {"prompt": prompt, "completion": completion},
    }
    return sw.openrouter_findings({"data": [item]})


def test_dated_bundle_id_matches_the_undated_openrouter_id(sw, monkeypatch):
    assert _haiku_findings(sw, monkeypatch, "0.000001", "0.000005") == []


def test_dated_bundle_id_still_raises_price_signal(sw, monkeypatch):
    [finding] = _haiku_findings(sw, monkeypatch, "0.000002", "0.00001")
    assert finding["key"] == "price-signal:anthropic:claude-haiku-4-5-20251001"


def test_change_past_the_old_storage_cap_still_shows(sw):
    def page(tail):
        rows = "".join(f"<p>row {i} price</p>" for i in range(6000))
        return f"<html><body>{rows}<p>{tail}</p></body></html>".encode()

    def read(tail):
        return lambda url: page(tail) if url == PAGE else _reader()(url)

    _, snapshot = sw.run(None, read("tail old value"))
    findings, _ = sw.run(snapshot, read("tail new value"))
    [change] = _by_type(findings, "page-changed")
    assert change["changed_lines"] == ["- tail old value", "+ tail new value"]


def test_diff_lines_that_look_like_file_headers_are_kept(sw):
    assert sw.changed_excerpt(["-- old value"], ["-- new value"]) == [
        "- -- old value",
        "+ -- new value",
    ]
    assert sw.changed_excerpt([], ["++ added"]) == ["+ ++ added"]


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '{"version": 1, "pages": []}',
        '{"version": 1, "pages": {"u": "x"}}',
        '{"version": 1, "pages": {"u": {"hash": "a"}}}',
    ],
)
def test_malformed_previous_snapshot_exits_2(sw, tmp_path, capsys, content):
    snap = tmp_path / "snap.json"
    snap.write_text(content)
    assert sw.main(["--previous", str(snap)], _reader()) == 2
    assert "cannot read previous snapshot" in capsys.readouterr().err


def test_unwritable_snapshot_prints_findings_then_exits_2(sw, tmp_path, capsys):
    target = tmp_path / "missing-dir" / "snap.json"
    assert sw.main(["--write", str(target), "--json"], _reader()) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["findings"]
    assert "cannot write snapshot" in captured.err


def test_snapshot_write_leaves_no_temp_file(sw, tmp_path):
    snap = tmp_path / "snap.json"
    assert sw.main(["--write", str(snap)], _reader()) == 0
    assert [p.name for p in tmp_path.iterdir()] == ["snap.json"]


def test_content_collapse_against_previous_snapshot_is_fetch_failed(sw):
    _, snapshot = sw.run(None, _reader())
    findings, next_snapshot = sw.run(snapshot, _reader({PAGE: "shell.html"}))
    assert _by_type(findings, "page-changed") == []
    assert f"fetch-failed:{PAGE}" in {f["key"] for f in findings}
    assert next_snapshot["pages"][PAGE] == snapshot["pages"][PAGE]


def test_deprecation_constants_are_watched_even_without_rows(sw, monkeypatch):
    url = "https://example.test/deprecations"
    monkeypatch.setattr(sw, "DEPRECATION_URLS", {"X_DEPRECATIONS_URL": url})
    assert sw.cited_urls()[url] == ["retirements constant X_DEPRECATIONS_URL"]


class _Response:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit):
        return self._body[:limit]


def _urlopen(sw, monkeypatch, action):
    monkeypatch.setattr(sw.urllib.request, "urlopen", action)


def test_fetch_returns_the_body(sw, monkeypatch):
    _urlopen(sw, monkeypatch, lambda request, timeout: _Response(b"ok"))
    assert sw.fetch("https://example.test/x") == b"ok"


def test_fetch_rejects_non_https(sw):
    with pytest.raises(sw.FetchError, match="not an https URL"):
        sw.fetch("http://example.test/x")


def test_fetch_reports_http_status_and_timeouts(sw, monkeypatch):
    def http_error(request, timeout):
        raise sw.urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)

    def timed_out(request, timeout):
        raise TimeoutError

    _urlopen(sw, monkeypatch, http_error)
    with pytest.raises(sw.FetchError, match="HTTP 503"):
        sw.fetch("https://example.test/x")
    _urlopen(sw, monkeypatch, timed_out)
    with pytest.raises(sw.FetchError, match="TimeoutError"):
        sw.fetch("https://example.test/x")


def test_fetch_rejects_an_oversize_body(sw, monkeypatch):
    big = b"x" * (sw.MAX_BYTES + 1)
    _urlopen(sw, monkeypatch, lambda request, timeout: _Response(big))
    with pytest.raises(sw.FetchError, match="too large"):
        sw.fetch("https://example.test/x")


GEMINI = "https://aistudio.google.com/docs/pricing"
GEMINI_MD = GEMINI + ".md"


def _gemini(sw, monkeypatch):
    monkeypatch.setattr(sw, "PUBLIC_PRICING_SOURCES", {("gemini", "example"): GEMINI})
    monkeypatch.setattr(sw, "PUBLIC_RETIREMENTS", {})


def _gemini_reader(md="gemini_page.md", html="gemini_shell.html"):
    def read(url):
        if url == ROUTER:
            return (FIXTURES / "openrouter.json").read_bytes()
        name = {GEMINI: html, GEMINI_MD: md}.get(url)
        if name is None:
            raise _load().FetchError("HTTP 404")
        return (FIXTURES / name).read_bytes()

    return read


def test_gemini_docs_are_read_through_markdown_twins(sw, monkeypatch):
    _gemini(sw, monkeypatch)
    findings, snapshot = sw.run(None, _gemini_reader())
    assert _by_type(findings, "fetch-failed") == []
    assert set(snapshot["pages"]) == {GEMINI_MD}
    lines = snapshot["pages"][GEMINI_MD]["lines"]
    assert "| example-flash | $0.30 | $2.50 |" in lines
    assert any("Café" in line for line in lines)


def test_cited_urls_watch_gemini_docs_through_markdown_twins():
    sw = _load()
    cites = sw.cited_urls()
    gemini = {u for u in cites if u.startswith("https://aistudio.google.com/docs/")}
    assert gemini and all(u.endswith(".md") for u in gemini)
    assert "https://aistudio.google.com/docs/models/gemini-4-argon.md" in gemini
    assert (
        "retirement gemini/gemini-4-argon"
        in cites["https://aistudio.google.com/docs/models/gemini-4-argon.md"]
    )


def test_markdown_page_change_reports_excerpt_and_citing_rows(sw, monkeypatch):
    _gemini(sw, monkeypatch)
    _, snapshot = sw.run(None, _gemini_reader())
    findings, _ = sw.run(snapshot, _gemini_reader(md="gemini_page_v2.md"))
    [change] = _by_type(findings, "page-changed")
    assert change["url"] == GEMINI_MD
    assert any(l.startswith("+ ") and "$0.35" in l for l in change["changed_lines"])
    assert change["cited_by"] == ["pricing gemini/example"]


def test_markdown_is_not_parsed_as_html(sw, monkeypatch):
    _gemini(sw, monkeypatch)
    body = (FIXTURES / "gemini_page.md").read_text() + "\n<script>\nlast line kept\n"
    findings, snapshot = sw.run(
        None,
        lambda u: (
            body.encode()
            if u == GEMINI_MD
            else (FIXTURES / "openrouter.json").read_bytes()
        ),
    )
    lines = snapshot["pages"][GEMINI_MD]["lines"]
    assert any("`<model>`" in line for line in lines)
    assert lines[-1] == "last line kept"
    assert _by_type(findings, "fetch-failed") == []


def test_html_served_at_markdown_url_is_fetch_failed(sw, monkeypatch):
    _gemini(sw, monkeypatch)
    _, snapshot = sw.run(None, _gemini_reader())
    findings, pages = sw.watch_pages(snapshot, _gemini_reader(md="gemini_shell.html"))
    [failed] = _by_type(findings, "fetch-failed")
    assert failed["reason"] == "not markdown"
    assert _by_type(findings, "page-changed") == []
    assert pages[GEMINI_MD] == snapshot["pages"][GEMINI_MD]


@pytest.mark.parametrize("body", ["", "# Title\n\nshort"])
def test_short_markdown_body_is_near_empty(sw, monkeypatch, body):
    _gemini(sw, monkeypatch)
    findings, _ = sw.run(
        None,
        lambda u: (
            body.encode()
            if u == GEMINI_MD
            else (FIXTURES / "openrouter.json").read_bytes()
        ),
    )
    [failed] = _by_type(findings, "fetch-failed")
    assert failed["reason"] == "near-empty text"


def test_old_html_snapshot_entry_is_not_compared_with_markdown(sw, monkeypatch):
    _gemini(sw, monkeypatch)
    old = {"hash": "x", "lines": [f"old html line {i}" for i in range(500)]}
    previous = {"version": 1, "pages": {GEMINI: old}}
    findings, snapshot = sw.run(previous, _gemini_reader())
    assert _by_type(findings, "page-changed") == []
    assert _by_type(findings, "fetch-failed") == []
    assert GEMINI not in snapshot["pages"]


def test_other_providers_keep_their_html_url(sw):
    assert sw.watched_url(PAGE) == PAGE
    _, snapshot = sw.run(None, _reader())
    assert "<" not in " ".join(snapshot["pages"][PAGE]["lines"])
    assert set(snapshot["pages"]) == {PAGE, LIMIT}
