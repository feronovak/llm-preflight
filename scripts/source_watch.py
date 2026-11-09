"""Nightly source watch: compare public upstream sources with the bundle.

Reads the bundled pricing and retirement data, fetches the public OpenRouter
model list and every official page the bundle cites, and reports what changed:
a new model, a price signal, a changed page, a page that could not be read.
It never edits bundled data; OpenRouter is a signal, the official page is the
source. State is one snapshot file: `--previous` in, `--write` out.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm_preflight.catalog import _normalized_model_id
from llm_preflight.pricing import PUBLIC_PRICING, PUBLIC_PRICING_SOURCES
from llm_preflight.retirements import (
    ANTHROPIC_DEPRECATIONS_URL,
    GEMINI_DEPRECATIONS_URL,
    OPENAI_DEPRECATIONS_URL,
    PUBLIC_RETIREMENTS,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
DEPRECATION_URLS = {
    "ANTHROPIC_DEPRECATIONS_URL": ANTHROPIC_DEPRECATIONS_URL,
    "OPENAI_DEPRECATIONS_URL": OPENAI_DEPRECATIONS_URL,
    "GEMINI_DEPRECATIONS_URL": GEMINI_DEPRECATIONS_URL,
}
SNAPSHOT_VERSION = 1
TIMEOUT_SECONDS = 20
MAX_BYTES = 5_000_000
MIN_TEXT_CHARS = 200
BOT_WALL_MAX_CHARS = 3000
EXCERPT_LINES = 20
EXCERPT_CHARS = 200
COLLAPSE_RATIO = 5
# OpenRouter author prefix per bundle provider (catalog.py knows xai and gemini).
OPENROUTER_AUTHORS = {
    "xai": "x-ai",
    "gemini": "google",
    "moonshot": "moonshotai",
    "mistral": "mistralai",
    "zai": "z-ai",
}
BOT_WALL_MARKERS = (
    "just a moment",
    "enable javascript",
    "verify you are human",
    "captcha",
    "access denied",
    "attention required",
)
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "header", "footer", "main",
}  # fmt: skip
_SKIPPED_TAGS = {"script", "style", "noscript", "template", "svg"}
GEMINI_DOCS_PREFIX = "https://aistudio.google.com/docs/"
_DATED_SUFFIX = re.compile(r"-\d{8}$")


class FetchError(Exception):
    """A source could not be read; the message is safe to report."""


def fetch(url: str) -> bytes:
    """GET a public URL with a size cap; raise FetchError with a short reason."""
    if not url.startswith("https://"):
        raise FetchError("not an https URL")
    request = urllib.request.Request(
        url, headers={"User-Agent": "llm-preflight-source-watch"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310
            body = response.read(MAX_BYTES + 1)
    except Exception as error:
        status = getattr(error, "code", None)
        raise FetchError(
            f"HTTP {status}" if status else type(error).__name__
        ) from error
    if len(body) > MAX_BYTES:
        raise FetchError("response too large")
    return body


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def normalise_html(html: str) -> list[str]:
    """Reduce a page to its non-empty, whitespace-collapsed text lines."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
        extractor.close()
    except (AssertionError, ValueError) as error:  # older html.parser versions
        raise FetchError("unparseable HTML") from error
    lines = (" ".join(line.split()) for line in "".join(extractor.parts).splitlines())
    return [line for line in lines if line]


def unreadable_reason(
    lines: list[str], before: dict[str, Any] | None = None
) -> str | None:
    """Why normalised text is clearly not the content, or None.

    A page that shrank to a fifth of its previous line count is a JS shell or
    a stripped page, not an edit.
    """
    text = "\n".join(lines)
    if len(text) < MIN_TEXT_CHARS:
        return "near-empty text"
    if before and len(lines) * COLLAPSE_RATIO < len(before["lines"]):
        return "content collapsed against previous snapshot"
    if len(text) < BOT_WALL_MAX_CHARS and any(
        m in text.casefold() for m in BOT_WALL_MARKERS
    ):
        return "bot wall"
    return None


def watched_url(url: str) -> str:
    """The URL the watch reads: Google's client-rendered docs serve text as `.md`."""
    if url.startswith(GEMINI_DOCS_PREFIX) and not url.endswith(".md"):
        return url + ".md"
    return url


def normalise_markdown(text: str) -> list[str]:
    """Whitespace-collapsed non-empty lines of a markdown page; never parsed as HTML."""
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        raise FetchError("not markdown")
    lines = (" ".join(line.split()) for line in text.splitlines())
    return [line for line in lines if line]


def page_lines(url: str, body: str) -> list[str]:
    if url.startswith(GEMINI_DOCS_PREFIX) and url.endswith(".md"):
        return normalise_markdown(body)
    return normalise_html(body)


def text_hash(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def cited_urls() -> dict[str, list[str]]:
    """Every official URL the bundle cites, with the rows that cite it."""
    cites: dict[str, list[str]] = {}
    for (provider, model), url in PUBLIC_PRICING_SOURCES.items():
        cites.setdefault(watched_url(url), []).append(f"pricing {provider}/{model}")
    for (provider, model), row in PUBLIC_RETIREMENTS.items():
        cites.setdefault(watched_url(row["source_url"]), []).append(
            f"retirement {provider}/{model}"
        )
    for name, url in DEPRECATION_URLS.items():
        cites.setdefault(watched_url(url), []).append(f"retirements constant {name}")
    return {url: sorted(rows) for url, rows in sorted(cites.items())}


def _comparable_id(model_id: str) -> str:
    return _normalized_model_id(_DATED_SUFFIX.sub("", model_id))


def _per_million(value: Any) -> float | None:
    try:
        price = float(value) * 1_000_000
    except (TypeError, ValueError):
        return None
    return round(price, 6) if price >= 0 else None


def openrouter_findings(payload: Any) -> list[dict[str, Any]]:
    """`new-model` and `price-signal` findings for covered providers only."""
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise FetchError("unexpected JSON shape")
    bundled: dict[tuple[str, str], tuple[str, tuple[float, float, str]]] = {}
    for (provider, model), row in PUBLIC_PRICING.items():
        bundled[(provider, _comparable_id(model))] = (model, row)
    authors = {OPENROUTER_AUTHORS.get(p, p): p for p, _ in PUBLIC_PRICING}
    findings = []
    for item in items:
        model_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(model_id, str) or "/" not in model_id or ":" in model_id:
            continue
        author, name = model_id.split("/", 1)
        provider = authors.get(author)
        if provider is None:
            continue
        match = bundled.get((provider, _comparable_id(name)))
        if match is None:
            findings.append(
                {"key": f"new-model:{provider}:{name}", "type": "new-model",
                 "provider": provider, "model": name, "openrouter_id": model_id}
            )  # fmt: skip
            continue
        model, (bundled_in, bundled_out, _) = match
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        seen_in, seen_out = (
            _per_million(pricing.get("prompt")),
            _per_million(pricing.get("completion")),
        )
        if seen_in is None or seen_out is None:
            continue
        if (seen_in, seen_out) != (bundled_in, bundled_out):
            findings.append(
                {"key": f"price-signal:{provider}:{model}", "type": "price-signal",
                 "provider": provider, "model": model,
                 "bundled_per_million": {"input": bundled_in, "output": bundled_out},
                 "openrouter_per_million": {"input": seen_in, "output": seen_out}}
            )  # fmt: skip
    return findings


def changed_excerpt(old: list[str], new: list[str]) -> list[str]:
    """Bounded `-`/`+` lines between two page versions."""
    body = list(difflib.unified_diff(old, new, lineterm="", n=0))[2:]
    diff = [
        f"{line[0]} {line[1 : EXCERPT_CHARS + 1]}" for line in body if line[0] in "+-"
    ]
    return diff[:EXCERPT_LINES]


def watch_pages(
    previous: dict[str, Any] | None, read: Any = fetch
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch every cited page; return findings and the next `pages` snapshot."""
    old_pages = (previous or {}).get("pages", {})
    pages: dict[str, Any] = {}
    findings = []
    for url, rows in cited_urls().items():
        try:
            lines = page_lines(url, read(url).decode("utf-8", errors="replace"))
            reason = unreadable_reason(lines, old_pages.get(url))
            if reason:
                raise FetchError(reason)
        except FetchError as error:
            findings.append(
                {"key": f"fetch-failed:{url}", "type": "fetch-failed", "url": url, "reason": str(error)}
            )  # fmt: skip
            if url in old_pages:
                pages[url] = old_pages[url]
            continue
        digest = text_hash(lines)
        pages[url] = {"hash": digest, "lines": lines}
        before = old_pages.get(url)
        if previous is not None and before and before["hash"] != digest:
            findings.append(
                {"key": f"page-changed:{url}:{digest}", "type": "page-changed", "url": url,
                 "changed_lines": changed_excerpt(before["lines"], lines), "cited_by": rows}
            )  # fmt: skip
    return findings, pages


def run(
    previous: dict[str, Any] | None, read: Any = fetch
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """All findings plus the snapshot to write."""
    findings: list[dict[str, Any]] = []
    try:
        findings += openrouter_findings(json.loads(read(OPENROUTER_URL)))
    except (FetchError, ValueError) as error:
        reason = str(error) if isinstance(error, FetchError) else "invalid JSON"
        findings.append(
            {"key": f"fetch-failed:{OPENROUTER_URL}", "type": "fetch-failed", "url": OPENROUTER_URL, "reason": reason}
        )  # fmt: skip
    page_findings, pages = watch_pages(previous, read)
    return findings + page_findings, {"version": SNAPSHOT_VERSION, "pages": pages}


def load_snapshot(path: Path) -> dict[str, Any] | None:
    """The previous snapshot, or None when the file does not exist yet."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = data.get("pages") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("version") != SNAPSHOT_VERSION
        or not isinstance(pages, dict)
        or not all(_valid_page(entry) for entry in pages.values())
    ):
        raise ValueError(
            f"{path}: not a version {SNAPSHOT_VERSION} source-watch snapshot"
        )
    return data


def _valid_page(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("hash"), str)
        and isinstance(entry.get("lines"), list)
        and all(isinstance(line, str) for line in entry["lines"])
    )


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    """Write through a temp file so a killed run never leaves a torn snapshot."""
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(
            json.dumps(snapshot, indent=1, sort_keys=True), encoding="utf-8"
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def render_text(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "source watch: no findings"
    return "\n".join(f"{item['type']}: {item['key']}" for item in findings)


def main(argv: list[str] | None = None, read: Any = fetch) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--previous", type=Path, help="snapshot from the last run")
    parser.add_argument("--write", type=Path, help="write the new snapshot here")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    args = parser.parse_args(argv)
    try:
        previous = load_snapshot(args.previous) if args.previous else None
    except (OSError, ValueError) as error:
        print(f"source watch: cannot read previous snapshot: {error}", file=sys.stderr)
        return 2
    findings, snapshot = run(previous, read)
    print(
        json.dumps({"findings": findings}, indent=2)
        if args.json
        else render_text(findings)
    )
    if args.write:
        try:
            write_snapshot(args.write, snapshot)
        except OSError as error:
            print(f"source watch: cannot write snapshot: {error}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
