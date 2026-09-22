"""What changed, at line precision, and whether any of it was code.

Two questions every scoped gate asks, answered once so the answers agree: which
lines moved between two states, and which files changed since the tree was last
known green. Both answer None — never an empty result — when git cannot, for
the reason `gitio.diff_names` gives: an empty result is an all-clear, and an
all-clear nobody computed is how a gate skips the test that would have failed.

The last-green marker lives inside `.git`, so it is never committed and never
travels to another clone, where it would describe a tree that clone never ran.
It records a content manifest of every non-doc file rather than a commit alone:
an uncommitted edit is a change, and a file that was already dirty when the tree
went green — another session's work in progress — is not a change until its
content moves again. Beside it, fingerprints of what git cannot see and a test
still depends on: the interpreter and its installed packages, each package's
installed `node_modules`, and the gitignored directories the contract declares
as `untracked-inputs`.

A gate writes it in two phases. `snapshot` records the tree when the gate
starts; `commit` writes that snapshot as the marker only if the tree still
matches it when the gate ends. Hashing at the end would certify an edit made
while the tests ran — by the author, or by another session in the same tree —
that no test saw.
"""

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import VERSION
from .gitio import Git

DEFAULT_DOC_PATHS = ("docs/**", "**/*.md", "VERSION", "CHANGELOG.md")
MARKER = ("project-standard", "last-green")
# A binary file has no hunks to read; the whole file is the change.
WHOLE_FILE = (1, 10 ** 9)

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")
VENVS = (".venv/bin/python", "venv/bin/python", ".venv/Scripts/python.exe")
# The installed distributions, as `pip freeze` would list them — read through
# importlib.metadata, because a uv-built venv has no pip to ask.
PROBE = ("import sys, importlib.metadata as m\n"
         "print(sys.version.replace('\\n', ' '))\n"
         "for d in sorted(m.distributions(), key=lambda d: str(d.metadata['Name']).lower()):\n"
         "    print(d.metadata['Name'], d.version, d.read_text('direct_url.json') or '')\n")


class Insertion(tuple):
    """A pure insertion after old line N, as `(N, N)`. Equal to the plain
    tuple; the type is what lets a line citation of N+1 — the line the new
    text now sits directly before — read as touched."""


# -- globs --------------------------------------------------------------------

def _glob_regex(pattern):
    """`**` spans directories, `*` and `?` stay inside one path segment."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(path, patterns):
    """gitignore-style: the last matching pattern wins, `!` re-admits."""
    hit = False
    for pattern in patterns:
        negate = pattern.startswith("!")
        if _glob_regex(pattern[1:] if negate else pattern).match(path):
            hit = not negate
    return hit


def doc_paths_for(contract):
    declared = getattr(contract, "doc_paths", None) if contract else None
    return tuple(declared) if declared is not None else DEFAULT_DOC_PATHS


def is_doc(path, doc_paths=DEFAULT_DOC_PATHS):
    return matches(path, doc_paths)


# -- hunks --------------------------------------------------------------------

def parse_hunks(diff_text):
    """-> {path: [(start, end), ...]} in the OLD file's line numbers.

    A pure insertion after old line N (`-N,0`) is recorded as `(N, N)`: it
    touches whatever ends on line N, which is how appending a statement to the
    end of a function reads, and nothing it merely sits beside.
    """
    hunks, path, old_path = {}, None, None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            path = old_path = None
        elif line.startswith("--- "):
            old_path = None if line[4:] == "/dev/null" else line[6:]
        elif line.startswith("+++ "):
            new_path = None if line[4:] == "/dev/null" else line[6:]
            path = new_path or old_path
            hunks.setdefault(path, [])
        elif line.startswith("Binary files ") and line.endswith(" differ"):
            m = re.match(r"Binary files (?:a/(.+)|/dev/null) and (?:b/(.+)|/dev/null) differ",
                         line)
            if m:
                hunks.setdefault(m.group(2) or m.group(1), []).append(WHOLE_FILE)
        elif path is not None:
            m = HUNK.match(line)
            if m:
                start = int(m.group(1))
                count = 1 if m.group(2) is None else int(m.group(2))
                hunks[path].append(Insertion((start, start)) if count == 0
                                   else (start, start + count - 1))
    return hunks


def changed_hunks(repo, base, head=None):
    """Changed line ranges from `base` to `head`, keyed by repo-relative path.

    `head=None` means the working tree — staged and unstaged edits, plus
    untracked files, which no diff shows and which are exactly the new work a
    gate is usually run on. Ranges are in `base`'s coordinates, because that is
    where a document's citation was written. None when git cannot answer.
    """
    git = Git(repo)
    raw = git.diff_zero_context(base, head)
    if raw is None:
        return None
    hunks = parse_hunks(raw)
    if head is None:
        untracked = git.untracked()
        if untracked is None:
            return None
        for path in untracked:
            hunks.setdefault(path, [(0, 0)])
    return hunks


def code_changed(repo, base, doc_paths=DEFAULT_DOC_PATHS):
    """Non-doc paths changed from `base` to the working tree, or None."""
    git = Git(repo)
    names = git.names_changed(base)
    untracked = git.untracked()
    if names is None or untracked is None:
        return None
    names |= set(untracked)
    return {p for p in names if not is_doc(p, doc_paths)}


# -- the last-green marker ----------------------------------------------------

def manifest(repo, doc_paths=DEFAULT_DOC_PATHS):
    """-> {path: blob id} for every tracked or untracked non-doc file, as it
    stands in the working tree. None when git could not hash it."""
    git = Git(repo)
    blobs, unstaged, untracked = git.index_blobs(), git.unstaged(), git.untracked()
    if blobs is None or unstaged is None or untracked is None:
        return None
    dirty = [p for p in unstaged + untracked if not is_doc(p, doc_paths)]
    hashed = git.hash_files(dirty)
    if hashed is None:
        return None
    out = {p: b for p, b in blobs.items() if not is_doc(p, doc_paths)}
    for path in dirty:
        # A tracked file deleted in the working tree has no content to hash;
        # it is absent from the tree, so it is absent from the manifest.
        if path in hashed:
            out[path] = hashed[path]
        else:
            out.pop(path, None)
    return out


def content_hash(files):
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(f"{path}\0{files[path]}\n".encode())
    return h.hexdigest()


def marker_path(repo):
    git_dir = Git(repo).git_dir()
    return git_dir.joinpath(*MARKER) if git_dir else None


# -- what git cannot see --------------------------------------------------------

def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _interpreter(repo):
    """The repository's own venv when it has one, else the running Python."""
    for rel in VENVS:
        if (Path(repo) / rel).is_file():
            return str(Path(repo) / rel)
    return sys.executable


def _python(repo):
    try:
        proc = subprocess.run([_interpreter(repo), "-c", PROBE], capture_output=True,
                              text=True, errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None, None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None, None
    version, _, packages = proc.stdout.partition("\n")
    return version.strip(), _digest(packages.encode())


def _tree_digest(root):
    """Content hash of every file under `root`; "absent" when it does not
    exist, None when it cannot be read."""
    if not root.is_dir():
        return "absent"
    h = hashlib.sha256()
    try:
        for f in sorted(p for p in root.rglob("*") if p.is_file()):
            h.update(f"{f.relative_to(root).as_posix()}\0".encode())
            h.update(_digest(f.read_bytes()).encode())
    except OSError:
        return None
    return h.hexdigest()


def _norm_dir(path):
    return str(path).strip("/") + "/"


def env_path(key):
    """The repo-relative prefix an environment key describes, or None for the
    interpreter, which belongs to no path."""
    kind, _, where = key.partition(":")
    if kind == "node_modules":
        return "node_modules/" if where == "." else f"{where}/node_modules/"
    if kind == "untracked":
        return where
    return None


def environment(repo, untracked_inputs=()):
    """-> {key: fingerprint}. A value is None when it could not be read, and
    None never equals anything — an unread fingerprint is a change."""
    repo = Path(repo)
    version, packages = _python(repo)
    env = {"python-version": version, "python-packages": packages}
    tracked = Git(repo).ls_files()
    for pkg in sorted({str(Path(p).parent) for p in tracked
                       if Path(p).name == "package.json" and "node_modules" not in p}):
        lock = repo / pkg / "node_modules" / ".package-lock.json"
        try:
            env[f"node_modules:{pkg}"] = _digest(lock.read_bytes()) if lock.is_file() else "absent"
        except OSError:
            env[f"node_modules:{pkg}"] = None
    for d in untracked_inputs:
        env[f"untracked:{_norm_dir(d)}"] = _tree_digest(repo / _norm_dir(d))
    return env


def env_drift(marker, now):
    """-> [(key, before, now)] for every fingerprint that moved, or that
    either side could not read. A marker recorded before fingerprints existed
    has moved on every key."""
    before = marker.get("env")
    if not isinstance(before, dict):
        return [(k, None, v) for k, v in sorted(now.items())]
    return [(k, before.get(k), now.get(k)) for k in sorted(set(before) | set(now))
            if before.get(k) is None or now.get(k) is None or before.get(k) != now.get(k)]


# -- the two-phase write ----------------------------------------------------------

def snapshot(repo, doc_paths=DEFAULT_DOC_PATHS, untracked_inputs=()):
    """The tree as it stands, in the marker's shape. None when unhashable."""
    files = manifest(repo, doc_paths)
    head = Git(repo).head()
    if files is None or head is None:
        return None
    return {"head": head, "files": files, "doc_paths": list(doc_paths),
            "untracked_inputs": [_norm_dir(d) for d in untracked_inputs],
            "env": environment(repo, untracked_inputs)}


def drift(snap, now):
    """What differs between two snapshots: paths, then `HEAD`, `doc-paths`
    and environment keys by name."""
    out = sorted(p for p in set(snap["files"]) | set(now["files"])
                 if snap["files"].get(p) != now["files"].get(p))
    for key in ("head", "doc_paths", "untracked_inputs"):
        if snap.get(key) != now.get(key):
            out.append(key)
    out += [k for k, *_ in env_drift(snap, now["env"])]
    return out


def _excluded(path, exclude):
    return any(path == e.rstrip("/") or path.startswith(_norm_dir(e)) for e in exclude)


def commit(repo, snap, exclude=()):
    """Write `snap` as the marker. -> (marker, []) on success, (None, drift)
    when the tree no longer matches it, (None, None) when it cannot be read.

    An `exclude`d prefix is a scope whose leg did not run: it keeps what the
    previous marker recorded for it, so an edit there stays a change until a
    run that tests it. With no previous marker it is left out, which reads
    as changed.
    """
    now = snapshot(repo, snap["doc_paths"], snap.get("untracked_inputs", ()))
    path = marker_path(repo)
    if now is None or path is None:
        return None, None
    moved = drift(snap, now)
    if moved:
        return None, moved
    files, env = dict(snap["files"]), dict(snap["env"])
    if exclude:
        try:
            prev = read_marker(repo)
        except ValueError:
            prev = None
        if prev and prev.get("doc_paths") != snap["doc_paths"]:
            prev = None
        files = {p: b for p, b in files.items() if not _excluded(p, exclude)}
        env = {k: v for k, v in env.items()
               if env_path(k) is None or not _excluded(env_path(k), exclude)}
        if prev:
            files.update({p: b for p, b in prev["files"].items() if _excluded(p, exclude)})
            env.update({k: v for k, v in (prev.get("env") or {}).items()
                        if env_path(k) is not None and _excluded(env_path(k), exclude)})
    marker = dict(snap, files=files, env=env, content_hash=content_hash(files),
                  excluded=sorted(exclude), tool_version=VERSION,
                  marked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marker, sort_keys=True))
    return marker, []


def mark_green(repo, doc_paths=DEFAULT_DOC_PATHS, exclude=(), untracked_inputs=()):
    """Snapshot and commit in one step. -> the marker dict, or None.

    Right only when nothing runs between the two; a gate snapshots when it
    starts and commits when it ends.
    """
    snap = snapshot(repo, doc_paths, untracked_inputs)
    if snap is None:
        return None
    marker, _ = commit(repo, snap, exclude)
    return marker


def read_marker(repo):
    """The marker, or None when absent. A corrupt marker raises ValueError:
    it is not the same thing as no marker, and must not quietly become one."""
    path = marker_path(repo)
    if path is None or not path.is_file():
        return None
    try:
        marker = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable last-green marker at {path}: {exc}") from exc
    if not isinstance(marker, dict) or not isinstance(marker.get("files"), dict):
        raise ValueError(f"last-green marker at {path} has no file manifest")
    return marker


def changed_since_green(repo, marker, doc_paths=DEFAULT_DOC_PATHS):
    """Non-doc paths whose content differs from the green manifest, or None.

    A change to `doc-paths` itself changes what counts as code, so it is
    answered with every file in either manifest rather than a narrower guess.
    """
    now = manifest(repo, doc_paths)
    if now is None:
        return None
    before = marker["files"]
    if list(marker.get("doc_paths") or []) != list(doc_paths):
        return set(before) | set(now)
    return {p for p in set(before) | set(now) if before.get(p) != now.get(p)}


def resolve_base(repo, doc_paths=DEFAULT_DOC_PATHS):
    """-> (kind, base, changed, note). `changed` is None when unknown.

    The last-green marker first. Without one, the merge-base with the default
    branch, then the latest tag — each a point presumed green because it went
    through a gate to get there, and the note says so rather than implying the
    tree was verified.
    """
    git = Git(repo)
    marker = read_marker(repo)
    if marker is not None:
        changed = changed_since_green(repo, marker, doc_paths)
        return ("last-green", marker["head"], changed,
                f"since the last green run ({marker.get('marked_at', '?')}, "
                f"{marker['head'][:12]})")
    head = git.head()
    branch = git.default_branch()
    base = git.merge_base("HEAD", branch) if branch and head else None
    if base and base != head:
        return ("merge-base", base, code_changed(repo, base, doc_paths),
                f"no last-green marker; since the merge-base with {branch} "
                f"({base[:12]}), presumed green, not verified")
    tag = git.describe()
    if tag:
        return ("tag", tag, code_changed(repo, tag, doc_paths),
                f"no last-green marker; since the latest tag {tag}, presumed "
                f"green, not verified")
    return ("none", None, None,
            "no last-green marker, no default branch to diverge from, and no tag")
