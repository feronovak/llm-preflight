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
    monkeypatch.setattr(module, "MODEL_PAGES", {})
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
        if name.startswith("<"):
            return name.encode()
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

    _, snapshot = sw.run(None, read("tail $1.00"))
    findings, _ = sw.run(snapshot, read("tail $2.00"))
    [change] = _by_type(findings, "page-changed")
    assert change["changed_lines"] == ["- tail $1.00", "+ tail $2.00"]


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


PAD = "<p>" + "Reference text for this model page. " * 12 + "</p>"


def _single(sw, monkeypatch, provider, model):
    """Only `model` cites LIMIT, so sibling-row scoping applies."""
    monkeypatch.setattr(sw, "PUBLIC_PRICING_SOURCES", {(provider, model): LIMIT})
    monkeypatch.setattr(sw, "PUBLIC_RETIREMENTS", {})


def _second_run(sw, first, second):
    _, snapshot = sw.run(None, _reader({LIMIT: first, PAGE: first}))
    findings, _ = sw.run(snapshot, _reader({LIMIT: second, PAGE: second}))
    return _by_type(findings, "page-changed")


def test_openai_chrome_change_is_silent(sw, monkeypatch):
    _single(sw, monkeypatch, "openai", "gpt-5.6-terra")
    assert _second_run(sw, "openai_model_v1.html", "openai_model_v2_chrome.html") == []


def test_openai_deprecations_chrome_change_is_silent(sw):
    changes = _second_run(
        sw, "openai_deprecations_v1.html", "openai_deprecations_v2_chrome.html"
    )
    assert changes == []


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-haiku-4-5-20251001"])
def test_anthropic_sibling_row_change_is_silent(sw, monkeypatch, model):
    _single(sw, monkeypatch, "anthropic", model)
    changes = _second_run(
        sw, "anthropic_overview_v1.html", "anthropic_overview_v2_sibling.html"
    )
    assert changes == []


def test_price_change_in_main_is_reported(sw, monkeypatch):
    _single(sw, monkeypatch, "openai", "gpt-5.6-terra")
    [change] = _second_run(
        sw, "openai_model_v2_chrome.html", "openai_model_v3_price.html"
    )
    assert any("$2.50" in line for line in change["changed_lines"])
    assert not any("Codex" in line for line in change["changed_lines"])


def test_retirement_date_change_in_article_is_reported(sw):
    [change] = [
        c
        for c in _second_run(
            sw, "openai_deprecations_v2_chrome.html", "openai_deprecations_v3_date.html"
        )
        if c["url"] == PAGE
    ]
    assert any("2027-01-15" in line for line in change["changed_lines"])


def test_cited_row_in_comparison_table_is_reported(sw, monkeypatch):
    _single(sw, monkeypatch, "anthropic", "claude-sonnet-5-5")
    [change] = _second_run(
        sw, "anthropic_overview_v1.html", "anthropic_overview_v3_price.html"
    )
    assert any(
        line.startswith("+ ") and "$4" in line for line in change["changed_lines"]
    )


def test_catalog_page_reports_any_row(sw):
    [change] = [
        c
        for c in _second_run(
            sw, "openai_deprecations_v1.html", "openai_deprecations_v4_other_row.html"
        )
        if c["url"] == PAGE
    ]
    assert any("2026-11-20" in line for line in change["changed_lines"])


def _legacy(sw, html):
    return {
        "version": 1,
        "pages": {LIMIT: {"hash": "old", "lines": sw.normalise_html(html)}},
    }


def _legacy_run(sw, monkeypatch, old_html, new_html):
    _single(sw, monkeypatch, "openai", "gpt-5.6-terra")
    old = (FIXTURES / old_html).read_text() if old_html.endswith("html") else old_html
    findings, snapshot = sw.run(_legacy(sw, old), _reader({LIMIT: new_html}))
    return findings, snapshot


def test_legacy_entry_unchanged_page_is_silent(sw, monkeypatch):
    html = (
        "<nav><a>Pricing</a></nav><main><p>Pricing</p>"
        + PAD
        + "<p>Input $2.00 per million tokens</p></main>"
    )
    findings, snapshot = _legacy_run(sw, monkeypatch, html, html)
    assert _by_type(findings, "page-changed") == []
    assert snapshot["pages"][LIMIT]["scoped"] is True


def test_legacy_entry_chrome_change_is_silent(sw, monkeypatch):
    findings, _ = _legacy_run(
        sw, monkeypatch, "openai_model_v1.html", "openai_model_v2_chrome.html"
    )
    assert _by_type(findings, "page-changed") == []


def test_legacy_entry_real_change_is_reported(sw, monkeypatch):
    findings, _ = _legacy_run(
        sw, monkeypatch, "openai_model_v1.html", "openai_model_v3_price.html"
    )
    [change] = _by_type(findings, "page-changed")
    assert any(
        line.startswith("+ ") and "$2.50" in line for line in change["changed_lines"]
    )
    assert any(
        line.startswith("- ") and "$2.00" in line for line in change["changed_lines"]
    )


def test_legacy_entry_is_not_collapsed(sw, monkeypatch):
    chrome = "<nav>" + "".join(f"<li>Link {i}</li>" for i in range(80)) + "</nav>"
    html = chrome + "<main>" + PAD + "<p>Input $2.00</p></main>"
    findings, _ = _legacy_run(sw, monkeypatch, html, html)
    assert _by_type(findings, "fetch-failed") == []
    assert _by_type(findings, "page-changed") == []


def test_fetch_failure_keeps_legacy_entry_unmarked(sw, monkeypatch):
    _single(sw, monkeypatch, "openai", "gpt-5.6-terra")
    legacy = _legacy(sw, (FIXTURES / "openai_model_v1.html").read_text())
    _, snapshot = sw.run(legacy, _reader({LIMIT: None}))
    assert snapshot["pages"][LIMIT] == legacy["pages"][LIMIT]
    assert "scoped" not in snapshot["pages"][LIMIT]


def test_second_run_compares_scoped_entries(sw, monkeypatch):
    _, snapshot = _legacy_run(
        sw, monkeypatch, "openai_model_v1.html", "openai_model_v2_chrome.html"
    )
    findings, _ = sw.run(snapshot, _reader({LIMIT: "openai_model_v3_price.html"}))
    [change] = _by_type(findings, "page-changed")
    assert [line[:2] for line in change["changed_lines"]] == ["- ", "+ "]


def test_empty_main_is_fetch_failed(sw, monkeypatch):
    _single(sw, monkeypatch, "openai", "gpt-5.6-terra")
    html = "<nav>" + "<a>Docs link</a>" * 40 + "</nav><main></main>"
    findings, _ = sw.run(None, _reader({LIMIT: html}))
    [failed] = _by_type(findings, "fetch-failed")
    assert failed["reason"] == "near-empty text"


def test_access_denied_in_short_scoped_content_is_not_a_bot_wall(sw, monkeypatch):
    _single(sw, monkeypatch, "openai", "gpt-5.6-terra")
    html = (
        "<nav>"
        + "<a>Documentation link</a>" * 200
        + "</nav><main>"
        + PAD
        + "<p>Requests without a key get access denied.</p></main>"
    )
    findings, _ = sw.run(None, _reader({LIMIT: html}))
    assert _by_type(findings, "fetch-failed") == []


def test_page_without_landmarks_uses_whole_page(sw, monkeypatch):
    _single(sw, monkeypatch, "openai", "gpt-5.6-terra")
    html = (FIXTURES / "page_v1.html").read_text()
    _, snapshot = sw.run(None, _reader({LIMIT: "page_v1.html"}))
    assert snapshot["pages"][LIMIT]["lines"] == sw.normalise_html(html)


def test_unclosed_nav_does_not_swallow_content(sw):
    html = "<main><nav>unclosed menu</main><main>" + PAD + "Second container</main>"
    assert any("Second container" in line for line in sw.scoped_lines(html, []))
    assert "unclosed menu" not in sw.scoped_lines(html, [])


def test_nested_article_is_kept(sw):
    html = "<article><article>inner text</article>after inner</article><p>outside</p>"
    lines = sw.scoped_lines(html, [])
    assert "inner text" in lines and "after inner" in lines
    assert "outside" not in lines


def test_cited_model_variant_row_is_kept(sw):
    rows = ["pricing anthropic/claude-sonnet-5-5"]
    html = (
        "<main><table><tr><th>Claude Sonnet 5.5 (1M context)</th><td>$6</td></tr>"
        "<tr><th>Claude Fäble 5.2 — ünï</th><td>$8</td></tr></table></main>"
    )
    lines = sw.scoped_lines(html, rows)
    assert any("1M context" in line for line in lines)
    assert not any("ünï" in line or "$8" in line for line in lines)


SONNET = ["pricing anthropic/claude-sonnet-5-5"]


def _kept(sw, html, rows=SONNET):
    return " | ".join(sw.scoped_lines(html, rows))


@pytest.mark.parametrize(
    "first",
    [
        "Claude API",
        "Claude Sonnet 5.5*",
        "Claude 5.5 Sonnet",
        "Claude Sonnet 5.5, Claude Opus 5.5",
    ],
)
def test_row_that_is_not_a_different_model_id_is_kept(sw, first):
    html = f"<main><table><tr><th>{first}</th><td>$6 note</td></tr></table></main>"
    assert "$6 note" in _kept(sw, html)


def test_row_of_a_different_model_id_is_still_dropped(sw):
    html = "<main><table><tr><th>Claude Opus 5.5</th><td>$9</td></tr></table></main>"
    assert "$9" not in _kept(sw, html)


def test_unclosed_row_does_not_drop_text_after_the_table(sw):
    html = (
        "<main><table><tr><th>Claude Opus 5.5</th><td>$9</td></table>"
        "<p>text after the table</p></main>"
    )
    assert "text after the table" in _kept(sw, html)


def test_unclosed_row_does_not_drop_text_after_the_container(sw):
    html = "<main><table><tr><th>Claude Opus 5.5</th></main><p>outside main</p>"
    assert "outside main" not in _kept(sw, html + "<main>second</main>")
    assert "second" in _kept(sw, html + "<main>second</main>")


def test_partial_article_beside_a_price_table_falls_back_to_main(sw):
    html = (
        "<main><article>Promo: try our new tool</article>"
        "<table><tr><th>Claude Sonnet 5.5</th><td>$3</td></tr></table></main>"
    )
    kept = _kept(sw, html)
    assert "$3" in kept and "Promo" in kept


@pytest.mark.parametrize(
    "hidden", ["<script>var a = '<article>';</script>", "<!-- <article>x</article> -->"]
)
def test_article_in_script_or_comment_is_not_a_container(sw, hidden):
    html = f"{hidden}<main>{PAD}<p>Input $3</p></main>"
    assert "Input $3" in _kept(sw, html)


def test_dated_and_undated_citations_keep_sibling_filtering(sw):
    rows = [
        "pricing anthropic/claude-haiku-4-5",
        "pricing anthropic/claude-haiku-4-5-20251001",
    ]
    html = (
        "<main><table><tr><th>Claude Haiku 4.5</th><td>$1</td></tr>"
        "<tr><th>Claude Opus 5.5</th><td>$9</td></tr></table></main>"
    )
    kept = _kept(sw, html, rows)
    assert "$1" in kept and "$9" not in kept


def test_legacy_comparison_ignores_a_repeated_line_as_anchor(sw):
    before = ["Learn more", "Old promo line", "Body text", "Learn more", "Input $2"]
    scoped = ["Body text", "Learn more", "Input $2"]
    assert sw._legacy_changes(before, scoped, scoped) == []


def _change(sw, monkeypatch, old, new):
    _single(sw, monkeypatch, "openai", "gpt-5.6-terra")
    page = lambda body: f"<main>{PAD}{body}</main>"
    _, snapshot = sw.run(None, _reader({LIMIT: page(old)}))
    ignored: list = []
    findings, nxt = sw.run(snapshot, _reader({LIMIT: page(new)}), ignored)
    return _by_type(findings, "page-changed"), ignored, nxt


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("<p>GPT-5.6 Terra supports chat</p>", "<p>GPT-5.6 Terra supports tools</p>"),
        ("<p>Input $2.00</p>", "<p>Input $2.50</p>"),
        ("<p>Input</p><p>Output 3</p>", "<p>Input</p><p>Output 3.50</p>"),
        ("<p>Preview</p>", "<p>Preview until March 3</p>"),
        ("<p>Cutoff 2026-01-01</p>", "<p>Cutoff 2026-02-01</p>"),
        ("<p>Status: active</p>", "<p>Status: deprecated</p>"),
        ("<p>Status: active</p>", "<p>Status: Shutdown planned</p>"),
    ],
)
def test_relevant_change_is_a_finding(sw, monkeypatch, old, new):
    changes, ignored, _ = _change(sw, monkeypatch, old, new)
    assert len(changes) == 1 and ignored == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("<p>Try Codex today</p>", "<p>Build with Astra</p>"),
        ("<ul><li>Home</li></ul>", "<ul><li>Home</li><li>Guides</li></ul>"),
        ("<p>New: image tools</p>", "<p>New: voice tools</p>"),
    ],
)
def test_layout_promo_or_navigation_change_is_ignored_and_reported(
    sw, monkeypatch, old, new
):
    changes, ignored, nxt = _change(sw, monkeypatch, old, new)
    assert changes == []
    [item] = ignored
    assert item["url"] == LIMIT and item["cited_by"] == ["pricing openai/gpt-5.6-terra"]
    assert any(line.startswith(("- ", "+ ")) for line in item["changed_lines"])
    assert nxt["pages"][LIMIT]["hash"] == sw.text_hash(nxt["pages"][LIMIT]["lines"])


def test_ignored_change_is_recorded_so_it_is_not_reported_again(sw, monkeypatch):
    _, ignored, nxt = _change(sw, monkeypatch, "<p>Try Codex</p>", "<p>Try Astra</p>")
    assert len(ignored) == 1
    again: list = []
    same = _reader({LIMIT: f"<main>{PAD}<p>Try Astra</p></main>"})
    findings, _ = sw.run(nxt, same, again)
    assert _by_type(findings, "page-changed") == [] and again == []


def test_price_in_a_row_that_names_no_model_is_not_lost(sw, monkeypatch):
    changes, ignored, _ = _change(
        sw,
        monkeypatch,
        "<table><tr><td>Batch</td><td>1.00 per million</td></tr></table>",
        "<table><tr><td>Batch</td><td>0.50 per million</td></tr></table>",
    )
    assert len(changes) == 1 and ignored == []


def test_relevant_line_past_the_excerpt_cap_still_makes_a_finding(sw, monkeypatch):
    promo = "".join(f"<p>Promo {i}</p>" for i in range(30))
    changes, _, _ = _change(
        sw,
        monkeypatch,
        promo + "<p>Input $2</p>",
        promo.replace("Promo", "Ad") + "<p>Input $3</p>",
    )
    assert len(changes) == 1 and len(changes[0]["changed_lines"]) == sw.EXCERPT_LINES


def test_main_reports_ignored_changes_in_json_and_text(
    sw, monkeypatch, tmp_path, capsys
):
    _single(sw, monkeypatch, "openai", "gpt-5.6-terra")
    snap = tmp_path / "snap.json"
    argv = ["--previous", str(snap), "--write", str(snap), "--json"]
    old = f"<main>{PAD}<p>Try Codex</p></main>"
    new = f"<main>{PAD}<p>Try Astra</p></main>"
    assert sw.main(argv, _reader({LIMIT: old})) == 0
    assert json.loads(capsys.readouterr().out)["ignored"] == []
    assert sw.main(argv, _reader({LIMIT: new})) == 0
    out = json.loads(capsys.readouterr().out)
    assert [f for f in out["findings"] if f["type"] == "page-changed"] == []
    assert out["ignored"][0]["changed_lines"] == ["- Try Codex", "+ Try Astra"]
    snap.write_text(snap.read_text())
    assert sw.main(["--previous", str(snap)], _reader({LIMIT: old})) == 0
    text = capsys.readouterr().out
    assert "ignored page change" in text and "  - Try Astra" in text


GEMINI = "https://aistudio.google.com/docs/pricing"
GEMINI_MD = GEMINI + ".md"


def _gemini(sw, monkeypatch):
    monkeypatch.setattr(sw, "PUBLIC_PRICING_SOURCES", {("gemini", "example"): GEMINI})
    monkeypatch.setattr(sw, "PUBLIC_RETIREMENTS", {})


def _gemini_reader(md="gemini_page.txt", html="gemini_shell.html"):
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
    assert snapshot["pages"][GEMINI_MD]["scoped"] is True


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
    findings, _ = sw.run(snapshot, _gemini_reader(md="gemini_page_v2.txt"))
    [change] = _by_type(findings, "page-changed")
    assert change["url"] == GEMINI_MD
    assert any(l.startswith("+ ") and "$0.35" in l for l in change["changed_lines"])
    assert change["cited_by"] == ["pricing gemini/example"]


def test_markdown_is_not_parsed_as_html(sw, monkeypatch):
    _gemini(sw, monkeypatch)
    body = (FIXTURES / "gemini_page.txt").read_text() + "\n<script>\nlast line kept\n"
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
    assert snapshot["pages"][GEMINI_MD]["scoped"] is True
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


OFFICIAL = {
    "anthropic": ("https://platform.claude.com/models", "models_anthropic.html"),
    "openai": ("https://developers.openai.com/models", "models_openai.html"),
    "gemini": ("https://aistudio.google.com/docs/models", "models_gemini.md.txt"),
    "xai": ("https://docs.x.ai/models", "models_xai.html"),
}


def _official(sw, monkeypatch, **overrides):
    monkeypatch.setattr(sw, "MODEL_PAGES", {p: u for p, (u, _) in OFFICIAL.items()})
    served = {sw.watched_url(u): f for u, f in OFFICIAL.values()}
    for provider, name in overrides.items():
        served[sw.watched_url(OFFICIAL[provider][0])] = name
    base = _reader()

    def read(url):
        name = served.get(url, ...)
        if name is ...:
            return base(url)
        if name is None:
            raise sw.FetchError("HTTP 503")
        return name.encode() if name.startswith("<") else (FIXTURES / name).read_bytes()

    return read


def _new(findings):
    return {f["key"]: f for f in _by_type(findings, "new-model")}


def test_official_pages_report_unbundled_ids_with_their_source(sw, monkeypatch):
    findings, _ = sw.run(None, _official(sw, monkeypatch))
    new = _new(findings)
    assert new["new-model:anthropic:claude-haiku-9-1"]["source"] == (
        "https://platform.claude.com/models"
    )
    assert new["new-model:openai:gpt-9-nova"]["source"] == (
        "https://developers.openai.com/models"
    )
    assert new["new-model:gemini:gemini-9-argon"]["source"] == (
        "https://aistudio.google.com/docs/models.md"
    )
    assert new["new-model:xai:grok-9.1"]["source"] == "https://docs.x.ai/models"
    assert "new-model:xai:grok-9.1-0309" in new


def test_official_pages_skip_bundled_ids_prose_aliases_and_assets(sw, monkeypatch):
    keys = set(_new(sw.run(None, _official(sw, monkeypatch))[0]))
    text = " ".join(keys)
    for noise in ("5.6-terra", "claude-sonnet", "gpt-docs", "claude-api", "webp",
                  "png", "hidden", "latest", "alias", "anthropic.claude"):  # fmt: skip
        assert noise not in text
    assert "new-model:gemini:gemini-9-flash" in keys  # link slug


def test_model_seen_on_an_official_page_is_not_also_an_openrouter_finding(
    sw, monkeypatch
):
    findings, _ = sw.run(None, _official(sw, monkeypatch))
    assert [f["source"] for f in _by_type(findings, "new-model")
            if f["model"] == "gpt-9-nova"] == ["https://developers.openai.com/models"]  # fmt: skip


def test_openrouter_only_model_of_an_official_provider_is_marked(sw, monkeypatch):
    read = _official(sw, monkeypatch, openai="models_openai_without_nova.html")
    new = _new(sw.run(None, read)[0])
    assert new["new-model:openai:gpt-9-nova"]["source"] == "openrouter"
    assert new["new-model:openai:gpt-9-nova"]["openrouter_only"] is True


def test_openrouter_model_of_another_provider_is_not_marked(sw, monkeypatch):
    read = _official(sw, monkeypatch)
    monkeypatch.setattr(sw, "MODEL_PAGES", {"anthropic": OFFICIAL["anthropic"][0]})
    new = _new(sw.run(None, read)[0])
    assert new["new-model:openai:gpt-9-nova"]["openrouter_only"] is False


@pytest.mark.parametrize(
    "body, reason",
    [(None, "HTTP 503"), ("<html><body>moved</body></html>", "no model IDs listed")],
)
def test_unreadable_or_reshaped_official_page_is_fetch_failed(
    sw, monkeypatch, body, reason
):
    read = _official(sw, monkeypatch, xai=body)
    failed = {
        f["url"]: f["reason"] for f in _by_type(sw.run(None, read)[0], "fetch-failed")
    }
    assert failed == {"https://docs.x.ai/models": reason}


def test_official_findings_are_text_rendered_with_their_source(sw, monkeypatch):
    findings, _ = sw.run(None, _official(sw, monkeypatch))
    lines = sw.render_text(findings).splitlines()
    assert (
        "new-model: new-model:xai:grok-9.1 (source: https://docs.x.ai/models)" in lines
    )
    assert (
        "new-model: new-model:openai:gpt-9-nova (source: https://developers.openai.com/models)"
        in lines
    )


def test_real_model_pages_are_https_pages_with_an_id_family_each():
    sw = _load()
    assert set(sw.MODEL_PAGES) == set(sw.MODEL_ID_PREFIXES) == set(OFFICIAL)
    assert all(url.startswith("https://") for url in sw.MODEL_PAGES.values())


def test_digitless_and_o_series_ids_are_read(sw):
    body = (
        '<td>o4-mini</td><td>o3</td><a href="/api/docs/models/o3-pro">x</a>'
        '<a href="/api/docs/models/gpt-transcribe">x</a>'
        '<a href="/docs/guides/gpt-linked">x</a><p>see gpt-prose here</p>'
    )
    assert sw.model_ids("openai", body) == {
        "o4-mini", "o3", "o3-pro", "gpt-transcribe",
    }  # fmt: skip


def test_link_text_of_a_non_model_link_is_not_an_id(sw):
    body = (
        '<a href="/docs/en/api/overview">claude-api</a>'
        '<a href="/x">gpt-docs</a><a href="/api/docs/models/gpt-5.5">gpt-5.5</a>'
    )
    assert sw.model_ids("anthropic", body) == set()
    assert sw.model_ids("openai", body) == {"gpt-5.5"}


def test_official_fixture_lists_digitless_and_o_series_ids(sw, monkeypatch):
    keys = set(_new(sw.run(None, _official(sw, monkeypatch))[0]))
    assert {"new-model:openai:gpt-transcribe", "new-model:openai:o4-mini"} <= keys
    assert "new-model:openai:gpt-docs" not in keys


def test_failed_official_page_does_not_mark_openrouter_findings(sw, monkeypatch):
    findings, _ = sw.run(None, _official(sw, monkeypatch, openai=None))
    nova = _new(findings)["new-model:openai:gpt-9-nova"]
    assert nova["openrouter_only"] is False
    assert "fetch-failed:https://developers.openai.com/models" in {
        f["key"] for f in findings
    }
