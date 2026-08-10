"""Write docs/api/routes.json from the framework's own route table.

This is a dev-time step whose output is committed, exactly like a generated
OpenAPI spec. It cannot run in CI, which has no application dependencies
installed — and it must not, because CI's job is to diff the reference against
the committed manifest, not to re-derive it.

Static analysis is not an option for Flask: a route's path is relative to its
blueprint, blueprints nest, and the real path is composed at registration
across modules. Only the live app object knows the answer.
"""

import json
import sys
from pathlib import Path

from . import VERSION
from .gitio import repo_root

TARGET = "docs/api/routes.json"


def from_flask(app):
    out = []
    for rule in app.url_map.iter_rules():
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            out.append({"method": method, "path": str(rule.rule)})
    return out


def from_fastapi(app):
    out = []
    for route in app.routes:
        for method in sorted(getattr(route, "methods", []) or []):
            if method in ("HEAD", "OPTIONS"):
                continue
            out.append({"method": method, "path": route.path})
    return out


def extract(app):
    if hasattr(app, "url_map"):
        return from_flask(app)
    if hasattr(app, "routes"):
        return from_fastapi(app)
    raise TypeError("object is neither a Flask nor a FastAPI application")


def load_app(spec, repo):
    """`module:attr` or `module:factory()` — imported with repo on sys.path."""
    sys.path.insert(0, str(Path(repo).resolve()))
    module_name, _, attr = spec.partition(":")
    if not attr:
        raise ValueError("expected module:attr, e.g. app:create_app")
    module = __import__(module_name, fromlist=["*"])
    target = getattr(module, attr.rstrip("()"))
    return target() if callable(target) and attr.endswith("()") else (
        target() if callable(target) and not hasattr(target, "url_map")
        and not hasattr(target, "routes") else target)


def render(routes):
    unique = sorted({(r["method"].upper(), r["path"]) for r in routes})
    return json.dumps(
        {"generated_by": f"project-standard {VERSION}",
         "routes": [{"method": m, "path": p} for m, p in unique]},
        indent=2, sort_keys=True) + "\n"


def main(args):
    if not args.app:
        print("--app is required, e.g. --app app:create_app", file=sys.stderr)
        print("The manifest cannot be derived statically: a Flask route's path "
              "is composed at blueprint registration.", file=sys.stderr)
        return 2
    # The manifest belongs at the repository root, where the coverage check
    # reads it — not wherever the caller happened to be standing.
    repo = repo_root(Path(args.repo))
    try:
        app = load_app(args.app, repo)
        routes = extract(app)
    except Exception as exc:
        print(f"could not load {args.app}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    target = repo / TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(routes))
    print(f"wrote {target} ({len(routes)} routes)")
    return 0
