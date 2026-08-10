"""Shareable defaults, and the seam where a house rule stops being universal.

This tool is meant to be handed to someone else's repositories. Anything tuned
to one person's setup belongs here, marked, and overridable — otherwise the
standard smuggles one team's habits in as if they were best practice.

Three levels:

  UNIVERSAL   true in any repository, by convention
  COMMON      true in most, and safe as a default
  HOUSE       one team's choice; a default, but declarable in the contract
"""

import os
import re
from pathlib import Path

# -- route shapes (UNIVERSAL) ----------------------------------------------

# Detection and enumeration must agree on what a route file is, so the pattern
# lives here rather than in either checker. Two copies drifted: detection
# required a path segment, so a root-level `app/route.ts` never set http-api
# and the coverage check silently never ran for a repo whose whole surface was
# one webhook. Any App Router `route.ts` is an endpoint — webhooks and
# callbacks commonly live outside `app/api/`.
NEXT_ROUTE = re.compile(r"^(?:src/)?app/(?:(?P<path>.+)/)?route\.[tj]sx?$")
NEXT_PAGES_API = re.compile(r"^(?:src/)?pages/(?P<path>api/.+)\.[tj]sx?$")

# -- profile detection (UNIVERSAL) -----------------------------------------

# A package manifest is the strongest signal that a tree is shipped software.
PACKAGE_MANIFESTS = (
    "package.json", "pyproject.toml", "setup.py", "Cargo.toml", "go.mod",
    "composer.json", "Gemfile", "pom.xml", "build.gradle", "build.gradle.kts",
    "mix.exs", "pubspec.yaml", "Package.swift", "*.csproj",
)

# Conventional source roots across ecosystems.
ENTRYPOINT_DIRS = (
    "src", "app", "lib", "cmd", "pages", "internal", "pkg", "server",
)

# Distribution signals — a manifest saying "others consume this".
LIBRARY_SIGNALS = {
    "package.json": ("publishConfig", "bin", "exports", "types"),
    "pyproject.toml": ("[project.scripts]", "build-backend", "[tool.poetry]"),
    "setup.py": ("entry_points", "console_scripts"),
    "Cargo.toml": ("[lib]",),
}

# -- capabilities (UNIVERSAL) ----------------------------------------------

# Path fragments that mark a release channel. `detect._channels` reads these;
# adding an entry here is all it takes to recognise another toolchain.
CHANNEL_SIGNS = {
    "mobile": ("android-native/", "android/", "ios/", "capacitor.config",
               "pubspec.yaml"),
    "desktop": ("src-tauri/", "electron.config", "electron-builder.yml"),
}

# -- local-only paths ------------------------------------------------------

# COMMON — machine-local or tool-generated in most ecosystems.
LOCAL_ONLY_COMMON = (
    "logs/", "test_results/", "test-results/", "coverage/",
    ".ruff_cache/", ".pytest_cache/", ".mypy_cache/",
)

# Assistants this standard knows about. Naming only one would make a
# single-vendor tool: a repository written with a different assistant has the
# same needs, and its markers must be caught by the same rules.
ASSISTANTS = ("claude", "anthropic", "codex", "copilot", "cursor", "aider",
              "gemini", "windsurf")

# Per-assistant scratch that is machine-local wherever it appears.
ASSISTANT_LOCAL = (
    ".claude/settings.local.json", ".claude/worktrees/",
    ".claude/scheduled_tasks.lock",
    ".codex/cache/", ".cursor/cache/", ".aider.chat.history.md",
    ".aider.input.history", ".windsurf/cache/",
)

# HOUSE — agent and editor scratch directories. Widely applicable, but a team
# that deliberately tracks any of these should say so rather than be told it is
# wrong. Extend or replace with `local-only:` in the contract.
LOCAL_ONLY_HOUSE = (
    "docs/exec-summaries/", "session-notes/",
    ".agenthub/", ".playwright-mcp/", ".interface-design/",
) + ASSISTANT_LOCAL

LOCAL_ONLY_PATTERNS = ("*EXEC*SUMMAR*", "*-exec-summary*", "*SESSION-NOTES*")

# Tracked on purpose: project knowledge, and deliberate historical snapshots.
# Shared assistant knowledge — instructions a collaborator benefits from, as
# opposed to one machine's state. Tracked on purpose, for any assistant.
ALWAYS_TRACKED = (
    "docs/superpowers/",
    ".claude/agents/", ".claude/skills/",
    ".codex/", ".agents/", ".cursor/rules/", ".github/copilot-instructions.md",
)

# Dated snapshot directories are deliberate history. A file inside one may look
# like a local-only artifact by name; it is not.
ALWAYS_TRACKED_GLOBS = ("think-day-*/*", "dep-day-*/*", "dev-day-*/*")

# -- secret scanning (COMMON) ----------------------------------------------

# Dedicated tools, recognised by the configuration they leave behind. The
# standard recommends one rather than shipping its own: a half-hearted pattern
# list posing as a gate gives false confidence, which is worse than no gate.
SECRET_SCANNERS = {
    ".gitleaks.toml": "gitleaks",
    "gitleaks.toml": "gitleaks",
    ".secrets.baseline": "detect-secrets",
    ".trufflehog.yaml": "trufflehog",
    ".trufflehog.yml": "trufflehog",
    ".ggshield.yaml": "ggshield",
}
SECRET_SCANNER_HINTS = ("gitleaks", "trufflehog", "detect-secrets",
                        "detect_secrets", "ggshield", "git-secrets")

# The fallback, for repositories with no scanner configured. Deliberately
# narrow: it reads tracked *documentation* only, and reports at warn. It is a
# documentation-hygiene check, never a substitute for the real thing.
# Prefixes are assembled from fragments so this file does not itself contain a
# literal credential prefix. Exempting it from scanning would have been easier
# and would have made a genuine leak here invisible.
_SK = "sk" + "-"
DOC_SECRET_SHAPES = (
    (_SK + r"ant" + r"-[A-Za-z0-9_-]{8,}", "an Anthropic key"),
    (_SK + r"(?:proj-)?[A-Za-z0-9]{20,}", "an OpenAI key"),
    (r"gh[pousr]_[A-Za-z0-9]{16,}", "a GitHub token"),
    (r"xox[bpors]-[A-Za-z0-9-]{10,}", "a Slack token"),
    (r"AKIA[0-9A-Z]{16}", "an AWS access key"),
    (r"AIza[A-Za-z0-9_-]{30,}", "a Google API key"),
    (r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.", "a JWT"),
    ("-----" + "BEGIN" + r" [A-Z ]*" + "PRIVATE" + " KEY-----", "key material"),
)

# Values a redacted mirror is expected to carry instead.
REDACTION_MARKERS = ("REPLACE_ME", "CHANGEME", "your-key-here", "xxx", "...")

# -- attribution (HOUSE) ---------------------------------------------------

# Whether an AI assistant may be recorded as a contributor. `forbid` is the
# default because the tooling appends these markers unless told otherwise, so
# silence produces the marker rather than its absence — but a team that wants
# the attribution can say `ai-attribution: allow` and the checks stand down.
AI_ATTRIBUTION_DEFAULT = "forbid"


def local_only_paths(contract=None):
    """The effective local-only set for a repo."""
    base = list(LOCAL_ONLY_COMMON) + list(LOCAL_ONLY_HOUSE)
    if contract is not None:
        declared = contract.raw.get("local-only")
        if isinstance(declared, list) and declared:
            if str(declared[0]).strip() == "replace":
                return [str(p) for p in declared[1:]]
            base = base + [str(p) for p in declared]
        tracked_anyway = contract.raw.get("track-anyway")
        if isinstance(tracked_anyway, list):
            keep = {str(p).rstrip("/") for p in tracked_anyway}
            base = [p for p in base if p.rstrip("/") not in keep]
    return base


def attribution_policy(contract=None):
    if contract is not None:
        declared = contract.raw.get("ai-attribution")
        if declared in ("allow", "forbid"):
            return declared
    return AI_ATTRIBUTION_DEFAULT


def fleet_root():
    """Where `--fleet` looks.

    Configurable, because a hardcoded path is the fastest way to make a tool
    useless to anyone else. Falls back to the parent of the current repo, which
    is the common "all my projects live side by side" layout.
    """
    env = os.environ.get("PROJECT_STANDARD_FLEET")
    if env:
        return Path(env).expanduser()
    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        if (parent / ".git").exists():
            return parent.parent
    return cwd
