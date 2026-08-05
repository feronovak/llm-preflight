"""Endpoint coverage: what the code exposes versus what the reference documents.

Two hard-won rules:

  - The document format rule accepts what good documentation already looks
    like. A table with the method and path in separate cells is a common and
    perfectly good form; an earlier rule demanding a literal adjacent
    `GET /path` rejected it and would have demanded a rewrite into a worse
    format to satisfy a parser.
  - Enumeration comes from the framework, not from scraping decorators. A
    Flask route's path is relative to its blueprint, blueprints nest, and the
    real path is composed at registration across modules. Regex over
    decorators produces phantom routes by the dozen against a document that
    is in fact correct. Where enumeration cannot be resolved, we warn — a checker
    that cannot enumerate says so rather than inventing findings.
"""

import json
import re
from pathlib import Path

from . import findings as F

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
_M = "|".join(METHODS)

DOC_INLINE = re.compile(rf"\b((?:{_M})(?:\s*[·/,|]\s*(?:{_M}))*)\s+(/[^\s`\"'|)\],]*)")
DOC_ROW = re.compile(
    rf"^\s*\|\s*\**((?:{_M})(?:\s*[·/,]\s*(?:{_M}))*)\**\s*\|\s*\**`?([^`|*]+?)`?\**\s*\|",
    re.M)

# Any App Router `route.ts` is an endpoint — webhooks and callbacks commonly
# live outside `app/api/`, and missing them undercounts coverage while turning
# a documented route into a phantom.
NEXT_ROUTE = re.compile(r"^(?:src/)?app/(?:(?P<path>.+)/)?route\.[tj]sx?$")
# Next.js route groups are organisational and never appear in a URL.
ROUTE_GROUP = re.compile(r"/?\([^)]*\)")
NEXT_PAGES_API = re.compile(r"^(?:src/)?pages/(?P<path>api/.+)\.[tj]sx?$")
EXPORTED = r"export\s+(?:async\s+)?(?:function|const)\s+{m}\b"
# `export const {{ GET, POST }} = handlers` (Auth.js v5) and `export {{ GET }} from`
EXPORT_BRACE = re.compile(r"export\s+(?:const\s+)?\{([^}]*)\}")

DJANGO_SIGNS = re.compile(r"\burlpatterns\s*=")
FLASK_SIGNS = re.compile(r"\bBlueprint\(|@\w+\.route\(")
FASTAPI_SIGNS = re.compile(r"\bFastAPI\(|@\w+\.(?:get|post|put|patch|delete)\(")
EXPRESS_SIGNS = re.compile(r"\b(?:app|server|router)\.(?:get|post|put|patch|delete)\(|"
                           r"\b(?:app|server)\.listen\(")

MANIFEST = "docs/api/routes.json"
REFERENCE = "docs/API_REFERENCE.md"


def normalise(path):
    """Collapse parameter syntax so <int:id>, [id] and :id compare equal."""
    p = ROUTE_GROUP.sub("", path or "")
    p = re.sub(r"<[^>]*>|\[[^\]]*\]|\{[^}]*\}|:\w+", "{}", p)
    p = re.sub(r"/+", "/", p).rstrip("/")
    return p or "/"


def parse_doc_endpoints(text):
    out = set()
    pairs = list(DOC_ROW.findall(text or "")) + list(DOC_INLINE.findall(text or ""))
    for methods, path in pairs:
        path = path.strip()
        if not path.startswith("/"):
            continue
        for m in re.findall(_M, methods):
            out.add((m.upper(), normalise(path)))
    return out


def doc_endpoints(repo, tracked):
    if REFERENCE not in set(tracked):
        return None
    text = (Path(repo) / REFERENCE).read_text(errors="ignore")
    return parse_doc_endpoints(text)


def code_endpoints(repo, tracked):
    """-> (endpoints, unresolved_frameworks)"""
    repo = Path(repo)
    eps, unresolved = set(), []

    manifest = repo / MANIFEST
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(errors="ignore"))
            for r in data.get("routes", []):
                eps.add((str(r["method"]).upper(), normalise(r["path"])))
            return eps, unresolved
        except (ValueError, KeyError, TypeError):
            unresolved.append("routes.json (unreadable)")

    for rel in tracked:
        m = NEXT_ROUTE.match(rel)
        if m:
            src = _read(repo, rel)
            exported = set()
            for meth in METHODS:
                if re.search(EXPORTED.format(m=meth), src):
                    exported.add(meth)
            for brace in EXPORT_BRACE.findall(src):
                for name in re.split(r"[,\s]+", brace):
                    name = name.split(" as ")[-1].strip().upper()
                    if name in METHODS:
                        exported.add(name)
            for meth in sorted(exported):
                eps.add((meth, normalise("/" + (m.group("path") or ""))))
            continue
        m = NEXT_PAGES_API.match(rel)
        if m:
            path = re.sub(r"/index$", "", "/" + m.group("path"))
            eps.add(("ANY", normalise(path)))

    frameworks = set()
    for rel in tracked:
        if "/test" in rel or rel.startswith(("scripts/", "tools/", "examples/")):
            continue
        if rel.endswith(".py"):
            src = _read(repo, rel)
            if FASTAPI_SIGNS.search(src):
                frameworks.add("fastapi")
            elif FLASK_SIGNS.search(src):
                frameworks.add("flask")
            elif DJANGO_SIGNS.search(src):
                frameworks.add("django")
        elif rel.endswith((".ts", ".js", ".mjs")) and "node_modules" not in rel:
            # Express routes are literals, but mounting composes prefixes the
            # same way blueprints do — reporting it unresolved is honest, and
            # far better than flagging every documented route as a phantom.
            if EXPRESS_SIGNS.search(_read(repo, rel)):
                frameworks.add("express")
    for fw in sorted(frameworks):
        unresolved.append(fw)

    return eps, unresolved


def check(ctx):
    out = []
    if not ctx.resolved.http_api:
        return out

    tracked = set(ctx.tracked)
    docs = doc_endpoints(ctx.repo, tracked)
    code, unresolved = code_endpoints(ctx.repo, tracked)

    if not code and not unresolved:
        # Detection says this repo serves HTTP, but nothing here can enumerate
        # its routes — a framework we do not read, or a declared override.
        # Reporting "0 routes documented" would be nonsense, and diffing an
        # empty set turns every documented route into a phantom.
        out.append(F.warn(
            "10d", "this repository serves HTTP, but no supported route table "
                   "could be read. Write `docs/api/routes.json` (see "
                   "`project-standard routes`) so coverage can be checked."))
        return out

    if unresolved:
        automatable = {"flask", "fastapi"}
        how = (f"run `project-standard routes` to write {MANIFEST}"
               if set(unresolved) & automatable
               else f"write {MANIFEST} by hand — `project-standard routes` "
                    f"only loads Flask and FastAPI applications")
        out.append(F.warn(
            "10d", "route enumeration needs the framework's own route table for "
                   + ", ".join(unresolved) + f"; {how}. "
                   + (f"The reference documents {len(docs)} endpoint(s), "
                      f"not diffed." if docs else
                      "No API reference to compare against.")))
        return out

    if docs is None:
        out.append(F.error(
            "10a", f"{len(code)} route(s) in code and no `{REFERENCE}` — "
                   f"0/{len(code)} documented"))
        return out

    undocumented = sorted(code - docs)
    phantom = sorted(docs - code)

    baseline = _baseline(ctx)
    covered = len(code) - len(undocumented)
    out.append(F.warn("10", f"endpoint coverage: {covered}/{len(code)} documented"))

    if undocumented:
        shown = ", ".join(f"{m} {p}" for m, p in undocumented[:5])
        severity = F.ERROR
        note = ""
        if baseline is not None and covered >= baseline:
            severity = F.WARN
            note = (f" — at or above the declared api-coverage baseline "
                    f"({baseline}), so this is debt, not a regression")
        out.append(F.Finding(
            "10a", severity,
            f"{len(undocumented)} undocumented route(s): {shown}"
            + (" …" if len(undocumented) > 5 else "") + note))

    if phantom:
        shown = ", ".join(f"{m} {p}" for m, p in phantom[:5])
        out.append(F.error(
            "10b", f"{len(phantom)} documented route(s) no longer exist in code: "
                   f"{shown}" + (" …" if len(phantom) > 5 else ""),
            path=REFERENCE))

    out += _freshness(ctx, tracked)
    return out


def _baseline(ctx):
    raw = ctx.contract.raw.get("api-coverage")
    if raw is None:
        return None
    try:
        return int(str(raw).split("/")[0])
    except (ValueError, TypeError):
        return None


def _freshness(ctx, tracked):
    """Check 10c — compared by last-commit time, never mtime.

    Git does not store mtimes; a fresh clone stamps every file with the
    checkout time, so an mtime comparison in CI passes or fails at random.
    """
    out = []
    spec = next((p for p in (MANIFEST, "docs/api/openapi.yaml") if p in tracked),
                None)
    if not spec:
        return out
    spec_commit = ctx.git.last_commit_for(spec)
    if not spec_commit:
        return out
    for rel in sorted(tracked):
        if not (NEXT_ROUTE.match(rel) or NEXT_PAGES_API.match(rel)):
            continue
        route_commit = ctx.git.last_commit_for(rel)
        if not route_commit or route_commit == spec_commit:
            continue
        # Commit timestamps are second-resolution, so two commits made in quick
        # succession compare equal and the check silently never fires.
        # Ancestry is exact: the spec is stale when its commit is an ancestor
        # of the route's.
        if ctx.git.is_ancestor(spec_commit, route_commit):
            out.append(F.error(
                "10c", f"`{spec}` was last committed before the routes it "
                       f"documents (e.g. `{rel}`)", path=spec))
            break
    return out


def _read(repo, rel, limit=400_000):
    p = Path(repo) / rel
    try:
        if p.is_file() and p.stat().st_size <= limit:
            return p.read_text(errors="ignore")
    except OSError:
        pass
    return ""
