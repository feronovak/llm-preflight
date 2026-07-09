from __future__ import annotations

import urllib.parse


def require_http_url(url: str) -> None:
    """Reject local-file and ambiguous URLs before urllib handles them."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"URL must use http or https with a host: {url!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must not contain embedded credentials")
