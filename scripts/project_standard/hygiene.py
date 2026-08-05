"""Local-only paths, attribution, and hook reachability.

Attribution has four markers, not one. The harness appends several
independently, so guarding the trailer alone leaves the rule half-enforced —
a message stripped of `Co-Authored-By` but keeping a session URL still names
Claude, and that is the one that was actually getting through.

The pull-request body is a fifth marker with no git-side guard at all. Git
hooks never see PR bodies. That is stated, not papered over.
"""

import re
from fnmatch import fnmatch
from pathlib import Path

from . import defaults, findings as F

# Kept as a module attribute for callers and tests; the effective set for a
# given repo comes from defaults.local_only_paths(contract), which lets a repo
# extend or replace it. A standard that hardcodes one team's tooling
# directories smuggles that team's habits in as best practice.
LOCAL_ONLY = tuple(defaults.LOCAL_ONLY_COMMON) + tuple(defaults.LOCAL_ONLY_HOUSE)

# Exact paths catch the convention; a summary written outside it needs a
# pattern, and a filename is a hint rather than proof.
LOCAL_ONLY_PATTERNS = defaults.LOCAL_ONLY_PATTERNS

_A = "|".join(defaults.ASSISTANTS)

ATTRIBUTION = (
    ("8a", re.compile(rf"^\s*co-authored-by:.*({_A})", re.I | re.M),
     "a Co-Authored-By trailer naming an AI assistant"),
    ("8b", re.compile(rf"^\s*({_A})-session:|"
                      r"(?:claude\.ai|chatgpt\.com|cursor\.com)/\S*session",
                      re.I | re.M),
     "an assistant session reference"),
    ("8c", re.compile(rf"^\s*signed-off-by:.*({_A})", re.I | re.M),
     "a Signed-off-by naming an AI assistant"),
    ("8e", re.compile(rf"generated (?:with|by) \[?({_A})|🤖 generated with", re.I),
     "an assistant generation notice"),
)

IDENTITY = re.compile(rf"({_A})", re.I)

MARKER_LINE = "# project-standard: local-only"


def opted_in(ctx):
    """The local-only rule binds only repos that joined.

    Blocking logs/ everywhere would stop a legitimate commit in employer work,
    and a guard that does that gets disabled wholesale — taking the attribution
    rule with it.
    """
    repo = Path(ctx.repo)
    # Both spellings: the importable package directory the README tells people
    # to vendor (underscore) and the hyphenated form. A repo that adopted via
    # the documented path must not silently miss enforcement.
    for name in ("project_standard", "project-standard"):
        if (repo / "scripts" / name).is_dir():
            return True
    gi = repo / ".gitignore"
    if gi.is_file() and MARKER_LINE in gi.read_text(errors="ignore"):
        return True
    return False


def check(ctx):
    out = []
    out += _secrets(ctx)
    out += _tracked_local_only(ctx)
    out += _gitignore(ctx)
    out += _attribution(ctx)
    out += _hooks(ctx)
    return out


def _secrets(ctx):
    """Checks 40 and 41.

    40 asks whether a real secret scanner is configured, and recommends one if
    not. 41 is the fallback for repositories without one — and it is a
    documentation-hygiene check, not a scanner. It reads tracked documentation
    only, and never claims a repository is clean.

    The standard does not ship its own scanner on purpose. A partial pattern
    list presented as a gate gives false confidence, and secret scanning has
    mature dedicated tools that do it properly.
    """
    out = []
    repo = Path(ctx.repo)
    tracked = set(ctx.tracked)

    configured = next((tool for name, tool in defaults.SECRET_SCANNERS.items()
                       if name in tracked or (repo / name).is_file()), None)
    if not configured:
        for rel in tracked:
            if rel.startswith(".github/") or rel.endswith((".yaml", ".yml")):
                text = _read(repo, rel)
                if any(h in text for h in defaults.SECRET_SCANNER_HINTS):
                    configured = "a scanner in CI"
                    break

    if not configured:
        out.append(F.warn(
            "40", "no secret scanner is configured. This standard does not "
                  "provide one — use a dedicated tool (gitleaks, detect-secrets, "
                  "trufflehog) and commit its config. The check below is "
                  "documentation hygiene only and is not a substitute."))

    # 41 — secret-shaped strings in tracked documentation.
    docs_and_contract = [r for r in tracked
                         if r.endswith((".md", ".mdx"))
                         or r in ("CLAUDE.md", "AGENTS.md")]
    for rel in sorted(docs_and_contract):
        text = _read(repo, rel)
        if not text:
            continue
        for pattern, label in defaults.DOC_SECRET_SHAPES:
            m = re.search(pattern, text)
            if not m:
                continue
            window = text[max(0, m.start() - 60):m.start()]
            if any(k.lower() in window.lower()
                   for k in defaults.REDACTION_MARKERS):
                continue
            line = text[:m.start()].count("\n") + 1
            out.append(F.warn(
                "41", f"a tracked document contains something shaped like "
                      f"{label}. Secret values never belong in documentation or "
                      f"in the agent contract — keep the real file gitignored "
                      f"and commit a redacted mirror whose values read "
                      f"`REPLACE_ME`.", path=rel, line=line))
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


def _tracked_local_only(ctx):
    """Errors only for repos that opted in.

    Some repositories track `logs/` on purpose. Telling a stranger their repo
    is broken for a convention they never adopted is how a checker gets
    switched off — so outside an opted-in repo this reports warns, not errors.
    """
    out = []
    severity = F.ERROR if opted_in(ctx) else F.WARN
    local_only = defaults.local_only_paths(ctx.contract)
    for rel in ctx.tracked:
        if any(rel.startswith(keep) for keep in defaults.ALWAYS_TRACKED):
            continue
        if any(fnmatch(rel, g) or fnmatch(rel, "*/" + g)
               for g in defaults.ALWAYS_TRACKED_GLOBS):
            continue
        for path in local_only:
            bare = path.rstrip("/")
            if rel == bare or rel.startswith(path):
                out.append(F.Finding(
                    "7", severity,
                    "local-only path is tracked — un-track it "
                    "(history is not rewritten)"
                    + ("" if severity == F.ERROR else
                       "; this repo has not opted into the local-only rule"),
                    path=rel))
                break
        else:
            name = Path(rel).name
            if any(fnmatch(name.upper(), pat.upper())
                   for pat in LOCAL_ONLY_PATTERNS):
                out.append(F.warn(
                    "7", "looks like a local-only artifact but matches no exact "
                         "path — move it under docs/exec-summaries/ or confirm "
                         "it belongs in git", path=rel))
    return out


def _gitignore(ctx):
    out = []
    if not opted_in(ctx):
        return out
    gi = Path(ctx.repo) / ".gitignore"
    text = gi.read_text(errors="ignore") if gi.is_file() else ""
    local_only = defaults.local_only_paths(ctx.contract)
    missing = [p for p in local_only if p.rstrip("/") not in text]
    if missing:
        out.append(F.error(
            "9", f"gitignore is missing {len(missing)} of {len(local_only)} "
                 f"local-only entries: " + ", ".join(missing[:4])
                 + (" …" if len(missing) > 4 else ""), path=".gitignore"))
    return out


def _attribution(ctx):
    out = []
    if defaults.attribution_policy(ctx.contract) == "allow":
        return out  # the repo has declared it wants the attribution
    adopted = ctx.contract.adopted
    adopted_ok = bool(adopted) and ctx.git.commit_exists(adopted)

    after = ctx.git.commits(since=adopted) if adopted_ok else []
    before = ctx.git.commits() if not adopted_ok else \
        [c for c in ctx.git.commits() if c not in after]

    for check_id, pattern, label in ATTRIBUTION:
        hits = [c for c in after if pattern.search(c["body"] or "")]
        if hits:
            out.append(F.error(
                check_id, f"{len(hits)} commit(s) after the adoption baseline "
                          f"carry a {label} — newest {hits[0]['hash'][:8]}"))
        old = [c for c in before if pattern.search(c["body"] or "")]
        if old:
            out.append(F.warn(
                "14", f"{len(old)} commit(s) before the baseline carry a "
                      f"{label}; history is not rewritten for tidiness"))

    bad_ident = [c for c in after
                 if IDENTITY.search(c["author"] + c["author_email"]
                                    + c["committer"] + c["committer_email"])]
    if bad_ident:
        out.append(F.error(
            "8d", f"{len(bad_ident)} commit(s) after the baseline are authored "
                  f"or committed as Claude — newest {bad_ident[0]['hash'][:8]}"))

    if not adopted_ok:
        out.append(F.warn(
            "14", "no usable `adopted` baseline, so every attribution marker in "
                  "history is reported as pre-existing rather than as a breach"))
    return out


def _hooks(ctx):
    """Checks 11 / 11b — the guards are reachable.

    A hook placed in a repo's own .git/hooks never fires when core.hooksPath is
    set elsewhere, so the question is whether the *resolved* directory holds
    the guards.

    Severity is advisory unless the repo opted in. Erroring by default would
    fail a stranger's first run on a fully conformant repository, against a
    check about their workstation that their repository cannot satisfy.
    """
    out = []
    if defaults.attribution_policy(ctx.contract) == "allow":
        return out  # the repo does not want the guards

    severity = F.ERROR if opted_in(ctx) else F.WARN
    resolved = ctx.git.config("core.hooksPath")
    local = ctx.git.config("core.hooksPath", local_only=True)

    if not resolved:
        out.append(F.Finding(
            "11", severity,
            "core.hooksPath is unset, so no hooks directory is wired up — "
            "install the authorship guards with `install-hooks`"))
        return out

    hooks_dir = Path(resolved).expanduser()
    if not hooks_dir.is_absolute():
        hooks_dir = Path(ctx.repo) / hooks_dir

    # Filenames only: this asks whether a hooks directory is wired up, not
    # whether those particular hooks enforce anything. The history checks
    # (8a-8e) are what actually verify the rule held.
    missing = [n for n in ("pre-commit", "commit-msg")
               if not (hooks_dir / n).is_file()]
    if missing:
        # A local override pointing somewhere without the guards silently
        # disables every hook, which is worth an error even before opt-in.
        finding = F.Finding(
            "11b" if local else "11",
            F.ERROR if local else severity,
            f"core.hooksPath resolves to `{hooks_dir}`, which is missing "
            + ", ".join(missing)
            + (" — a local override pointing at a directory without the guards "
               "silently disables every hook" if local else ""))
        out.append(finding)
    return out
