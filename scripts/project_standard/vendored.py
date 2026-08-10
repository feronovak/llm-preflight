"""Check 17 — a vendored copy that no longer matches the canonical tool.

Vendoring is what lets CI run this checker with no install step, and it is why
more than one copy exists. The design named the risk and the mitigation in one
breath: copies drift, so compare the vendored copy's version against canonical.

Measured on the fleet, that mitigation would not have worked. The one repo that
had adopted the vendored path carried nine modules differing from canonical and
one missing entirely, while both copies still declared the same `VERSION` — the
string had not moved when the code did. A version comparison alone reports a
stale copy as current, which is worse than no check, because it answers the
question wrongly rather than declining to answer it.

So this compares content as well, and says which of the two failure modes it
found. A copy that differs while claiming the same version is the more serious
one: it means the release discipline this standard exists to enforce was not
applied to the standard's own tool.
"""

import hashlib
from pathlib import Path

from . import VERSION
from . import findings as F

CHECK = "17"
# Both spellings the README has ever told anyone to vendor under.
VENDOR_NAMES = ("project_standard", "project-standard")


def _modules(directory):
    """-> {filename: text} for the package's own source, sorted."""
    out = {}
    for path in sorted(Path(directory).glob("*.py")):
        try:
            out[path.name] = path.read_text(errors="ignore")
        except OSError:
            continue
    return out


def _digest(modules):
    h = hashlib.sha256()
    for name in sorted(modules):
        h.update(name.encode())
        h.update(modules[name].encode())
    return h.hexdigest()


def _declared_version(modules):
    import re
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)',
                  modules.get("__init__.py", ""), re.M)
    return m.group(1) if m else None


def check(ctx):
    canonical_dir = Path(__file__).resolve().parent
    tracked = set(ctx.tracked)

    for name in VENDOR_NAMES:
        prefix = f"scripts/{name}/"
        if not any(t.startswith(prefix) for t in tracked):
            continue
        vendored_dir = Path(ctx.repo) / "scripts" / name
        if not vendored_dir.is_dir():
            continue
        # Running from inside the copy being examined: there is nothing to
        # compare, and reporting a repo against itself would be noise.
        if vendored_dir.resolve() == canonical_dir:
            continue
        return _compare(vendored_dir, canonical_dir, prefix)
    return []


def _compare(vendored_dir, canonical_dir, prefix):
    vendored = _modules(vendored_dir)
    canonical = _modules(canonical_dir)
    if not vendored or not canonical:
        return []

    their_version = _declared_version(vendored)
    missing = sorted(set(canonical) - set(vendored))
    differing = sorted(n for n in set(canonical) & set(vendored)
                       if canonical[n] != vendored[n])

    if not missing and not differing:
        return []

    detail = []
    if missing:
        detail.append(f"{len(missing)} module(s) missing "
                      f"({', '.join(missing[:3])}"
                      + (" …" if len(missing) > 3 else "") + ")")
    if differing:
        detail.append(f"{len(differing)} differing "
                      f"({', '.join(differing[:3])}"
                      + (" …" if len(differing) > 3 else "") + ")")
    what = "; ".join(detail)

    if their_version == VERSION:
        return [F.warn(
            CHECK,
            f"the vendored checker under `{prefix}` differs from the canonical "
            f"tool while reporting the same version {VERSION} — {what}. The "
            f"version was not bumped when the code changed, so nothing here "
            f"can tell a current copy from a stale one. Re-vendor with "
            f"`project-standard vendor`.")]

    theirs = their_version or "an unknown version"
    return [F.warn(
        CHECK,
        f"the vendored checker under `{prefix}` is at {theirs}, canonical is "
        f"at {VERSION} — {what}. CI in this repository is not running the "
        f"checks this report describes. Re-vendor with "
        f"`project-standard vendor`.")]
