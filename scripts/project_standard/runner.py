"""Wire the checkers together, and decide what runs where.

Not every check is answerable in CI. A CI runner has no developer hooks directory, and
GitHub Actions clones with `fetch-depth: 1` and no tags, so history-dependent
checks and the hook check are *skipped* there — reported as skipped, never
silently passed. A check that did not run must never read as one that did.
"""

from dataclasses import dataclass, field
from pathlib import Path

from . import api, artifacts, baselines, contract as contract_mod, detect
from . import docmap, docs
from . import findings as F
from . import hygiene, release, vendored
from .gitio import Git, repo_root

DEV, CI = "dev", "ci"

# Checks that need a hooks directory only a developer's machine has.
HOOK_CHECKS = ("11", "11b")
# Checks that need real history and tags.
# Checks that genuinely need history or tags. `5b` (version sources disagree)
# reads only files and must stay live on a shallow clone.
HISTORY_CHECKS = ("5", "8a", "8b", "8c", "8d", "8e", "10c", "13", "14", "15",
                  "29", "38", "42")


@dataclass
class Ctx:
    repo: Path
    git: Git
    tracked: list
    contract: object
    resolved: object
    version: str = None
    profile: str = DEV
    skipped: set = field(default_factory=set)
    workspaces: list = field(default_factory=list)


def build_ctx(repo, profile=DEV):
    # Anchor on the repository root before reading anything. Called with a
    # subdirectory — which is what an omitted `--repo` produces — every path
    # below would be resolved against the wrong base.
    repo = repo_root(repo)
    git = Git(repo)
    tracked = git.ls_files()
    c = contract_mod.load(repo, tracked)
    detected = detect.detect(repo, tracked)
    resolved = detect.resolve(detected, c)
    version = release.version_source(repo, git.tags(), tracked)[1]
    return Ctx(repo=repo, git=git, tracked=tracked, contract=c,
               resolved=resolved, version=version, profile=profile)




def _workspaces(ctx):
    """Check 16 — a bounded scope that announces itself.

    Every common monorepo declaration, not just npm's: a pnpm or Cargo tree
    that produced no announcement would pass silently, which is the exact
    failure this check exists to prevent.
    """
    import json
    import re

    found = []
    tracked = set(ctx.tracked)

    pkg = ctx.repo / "package.json"
    if "package.json" in tracked and pkg.is_file():
        try:
            data = json.loads(pkg.read_text(errors="ignore"))
            ws = data.get("workspaces")
            if isinstance(ws, dict):
                ws = ws.get("packages")
            if isinstance(ws, list):
                found += [str(w) for w in ws]
        except ValueError:
            pass

    pnpm = ctx.repo / "pnpm-workspace.yaml"
    if "pnpm-workspace.yaml" in tracked and pnpm.is_file():
        # Only the `packages:` block — a pnpm workspace file also carries
        # unrelated list keys, and counting those invents workspaces.
        block = re.search(r"^packages:\s*$(.*?)(?=^\S|\Z)",
                          pnpm.read_text(errors="ignore"), re.M | re.S)
        if block:
            found += re.findall(r"^\s+-\s*['\"]?([^'\"\n]+)",
                                block.group(1), re.M)

    cargo = ctx.repo / "Cargo.toml"
    if "Cargo.toml" in tracked and cargo.is_file():
        text = cargo.read_text(errors="ignore")
        section = re.search(r"^\[workspace\]\s*$(.*?)(?=^\[|\Z)",
                            text, re.M | re.S)
        m = re.search(r"members\s*=\s*\[([^\]]*)\]",
                      section.group(1)) if section else None
        if m:
            found += [p.strip().strip('"\'') for p in m.group(1).split(",")
                      if p.strip()]

    gowork = ctx.repo / "go.work"
    if "go.work" in tracked and gowork.is_file():
        found += re.findall(r"^\s*\./(\S+)", gowork.read_text(errors="ignore"),
                            re.M)

    return [w for w in dict.fromkeys(found) if w]


def workspace_check(ctx):
    if not ctx.workspaces:
        return []
    return [F.warn(
        "16", f"{len(ctx.workspaces)} workspace(s) detected "
              f"({', '.join(str(w) for w in ctx.workspaces[:3])}) — validating "
              f"the repository root only; per-workspace validation is not "
              f"implemented")]


MODULES = (
    ("artifacts", artifacts.check),
    ("detect", detect.check),
    ("docs", docs.check),
    ("docmap", docmap.check),
    ("release", release.check),
    ("hygiene", hygiene.check),
    ("api", api.check),
    ("baselines", baselines.check),
    ("vendored", vendored.check),
    ("workspaces", workspace_check),
)


def skipped_checks(ctx):
    """Which checks cannot be answered in this environment, and why."""
    out = {}
    if ctx.profile == CI:
        for cid in HOOK_CHECKS:
            out[cid] = ("a CI runner has no developer hooks directory; "
                        "this asks about a workstation")
        if not ctx.git.has_history():
            for cid in HISTORY_CHECKS:
                out[cid] = ("shallow clone with no tags — set `fetch-depth: 0` "
                            "to answer this")
    return out


def run(repo, profile=DEV, only=None):
    report = F.Report()
    repo = Path(repo)
    git = Git(repo)

    if not git.is_repo():
        report.findings.append(F.error(
            "0", f"`{repo}` is not a git repository — every git-derived check "
                 f"is inapplicable. Run `git init` first; reporting a repo as "
                 f"conformant on checks that never ran would be a lie."))
        return report
    if not git.has_commits():
        report.findings.append(F.error(
            "0", "repository has no commits yet"))
        return report

    ctx = build_ctx(repo, profile=profile)
    report.summary = summary(ctx)   # built once; the scan is not cheap
    skips = skipped_checks(ctx)
    ctx.skipped = set(skips)

    ctx.workspaces = _workspaces(ctx)
    for _, fn in MODULES:
        try:
            for finding in fn(ctx):
                if finding.check in skips:
                    continue
                report.findings.append(finding)
        except Exception as exc:
            # A broken checker must not hide the others — and must not pass
            # for one either. Demoting this to a warn turns CI green on a
            # module that never ran.
            report.findings.append(F.error(
                "internal", f"{fn.__module__} raised {type(exc).__name__}: {exc}"))

    for cid, why in sorted(skips.items()):
        report.findings.append(F.skipped(cid, why))

    if only:
        needles = [n.lower() for n in only]
        report.findings = [
            f for f in report.findings
            if any(n in f.message.lower() or n == f.check.lower()
                   or n in (f.path or "").lower() for n in needles)
        ]
    return report


def summary(ctx):
    """One line describing what the repo was resolved as."""
    r = ctx.resolved
    return (f"{r.profile} · http-api={'yes' if r.http_api else 'no'} · "
            f"channels={'+'.join(r.channels)} · "
            f"contract={ctx.contract.path or '—'} · "
            f"version={ctx.version or '—'}")
