"""Resolve what a repo *is* from its code, not from what it claims.

A declared profile is a hand-maintained assertion, and hand-maintained
assertions are exactly what this tool distrusts. Detection is the default; the
contract may override, but an override owes a written reason and a mismatch is
reported rather than silently obeyed.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import defaults, findings as F

# One definition, shared with enumeration in api.py — see defaults.
NEXT_ROUTE = defaults.NEXT_ROUTE
NEXT_PAGES_API = defaults.NEXT_PAGES_API

PRODUCT, LIBRARY, DOCS = "product", "library", "docs"

SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".rb")
FLASK_APP = re.compile(r"\bFlask\(|\bBlueprint\(")
FASTAPI_APP = re.compile(r"\bFastAPI\(")
DJANGO_URLS = re.compile(r"\burlpatterns\s*=")
EXPRESS_LISTEN = re.compile(r"\b(?:app|server)\.listen\(")


@dataclass
class Detected:
    profile: str = PRODUCT
    http_api: bool = False
    channels: list = field(default_factory=lambda: ["web"])
    evidence: dict = field(default_factory=dict)


@dataclass
class Resolved:
    profile: str
    http_api: bool
    channels: list
    detected: Detected
    overridden: list = field(default_factory=list)


def detect(repo, tracked):
    repo = Path(repo)
    d = Detected()
    d.profile = _profile(repo, tracked)
    d.http_api, d.evidence = _http_api(repo, tracked)
    d.channels = _channels(repo, tracked)
    return d


def resolve(detected, contract):
    """Apply contract overrides, recording which ones fired."""
    profile = contract.profile or detected.profile
    http_api = detected.http_api
    if contract.http_api is not None:
        http_api = bool(contract.http_api)
    channels = contract.channels or detected.channels

    overridden = []
    if contract.profile and contract.profile != detected.profile:
        overridden.append(("profile", detected.profile, contract.profile))
    if contract.http_api is not None and bool(contract.http_api) != detected.http_api:
        overridden.append(("http-api", detected.http_api, bool(contract.http_api)))
    if contract.channels and sorted(contract.channels) != sorted(detected.channels):
        overridden.append(("channels", detected.channels, contract.channels))

    return Resolved(profile, http_api, channels, detected, overridden)


def check(ctx):
    """Check 6 — a declaration contradicting detection, and overrides with no
    reason. An escape hatch that costs nothing becomes the default."""
    out = []
    for key, was, now in ctx.resolved.overridden:
        reason = ctx.contract.reasons.get(key)
        if not reason:
            out.append(F.error(
                "6", f"`{key}` declared {now!r} but detection found {was!r}, "
                     f"with no reason given", path=ctx.contract.path))
        else:
            out.append(F.warn(
                "6", f"`{key}` overrides detection ({was!r} -> {now!r}): {reason}",
                path=ctx.contract.path))
    return out


# -- detection internals ---------------------------------------------------

def _read(repo, rel, limit=200_000):
    p = repo / rel
    try:
        if p.is_file() and p.stat().st_size <= limit:
            return p.read_text(errors="ignore")
    except OSError:
        pass
    return ""


def _json(repo, rel):
    try:
        return json.loads(_read(repo, rel) or "{}")
    except ValueError:
        return {}


def manifests(repo, tracked):
    """Package manifests at the repository root, tracked ones only.

    Presence is answered from git, never from the working tree. This decides
    the profile, and the profile decides which documents the repo owes — so a
    gitignored `package.json` reading as a product turned one commit into two
    different verdicts depending on whose disk it was checked out on.
    """
    tracked = set(tracked)
    present = []
    for name in defaults.PACKAGE_MANIFESTS:
        if name.startswith("*"):
            if any(f.endswith(name[1:]) and "/" not in f for f in tracked):
                present.append(name)
        elif name in tracked:
            present.append(name)
    return present


def _profile(repo, tracked):
    """product | library | docs, from packaging convention.

    The discriminator is a package manifest or a conventional source root —
    not the absence of code files and not a markdown ratio. An infrastructure
    repo holds shell scripts, and a documentation-heavy product can be 41%
    markdown; both break the naive tests.
    """
    found = manifests(repo, tracked)

    for name in found:
        signals = defaults.LIBRARY_SIGNALS.get(name)
        if not signals:
            continue
        if name == "package.json":
            pkg = _json(repo, name)
            if any(k in pkg for k in signals) and not pkg.get("private"):
                return LIBRARY
        else:
            text = _read(repo, name)
            if any(s in text for s in signals):
                return LIBRARY

    if found:
        return PRODUCT

    has_entrypoint = any(
        f.split("/", 1)[0] in defaults.ENTRYPOINT_DIRS
        and f.endswith(SOURCE_SUFFIXES)
        for f in tracked
    )
    return PRODUCT if has_entrypoint else DOCS


def _http_api(repo, tracked):
    evidence = {}
    routes = [f for f in tracked
              if NEXT_ROUTE.match(f) or NEXT_PAGES_API.match(f)]
    if routes:
        evidence["next"] = len(routes)

    for f in tracked:
        if not f.endswith((".py", ".ts", ".js", ".mjs")):
            continue
        if "node_modules" in f or "/test" in f:
            continue
        # A dev utility that calls listen() is not the product's API surface.
        if f.startswith(("scripts/", "tools/", "bin/", "examples/")):
            continue
        text = _read(repo, f, limit=400_000)
        if not text:
            continue
        if FLASK_APP.search(text):
            evidence.setdefault("flask", f)
        elif FASTAPI_APP.search(text):
            evidence.setdefault("fastapi", f)
        elif DJANGO_URLS.search(text):
            evidence.setdefault("django", f)
        elif EXPRESS_LISTEN.search(text):
            evidence.setdefault("express", f)

    return bool(evidence), evidence


def _channels(repo, tracked):
    channels = []

    for f in tracked:
        if f.endswith("manifest.json") and "node_modules" not in f:
            if "manifest_version" in _read(repo, f, limit=100_000):
                channels.append("extension")
                break

    for channel in ("mobile", "desktop"):
        signs = defaults.CHANNEL_SIGNS[channel]
        if any(f.startswith(s) or s in f for f in tracked for s in signs):
            channels.append(channel)

    # `extension` is exclusive: an extension's source tree looks exactly like a
    # web app's, and a phantom `web` channel arms a release gate that can never
    # pass.
    if "extension" in channels:
        return ["extension"]

    return ["web"] + channels
