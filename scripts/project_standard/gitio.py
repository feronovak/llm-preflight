"""Every git read in one place.

No other module shells out to git. That is what makes the whole suite testable
against throwaway fixture repos, and it is the only reason `--profile=ci` can
know which checks are answerable on a shallow clone.
"""

import re
import subprocess
from pathlib import Path

NUL = "\x00"
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SEMVER_TAG = re.compile(r"^(?:(?P<channel>[a-z][a-z0-9_-]*)/)?v"
                        r"(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
                        r"(?:-(?P<pre>.+))?$")


class Git:
    def __init__(self, repo):
        self.repo = Path(repo)

    def _run(self, *args, check=False, stdin=None):
        proc = subprocess.run(
            ["git", "-C", str(self.repo), *args],
            # `replace`: a diff over a non-UTF-8 file must not raise out of a
            # read whose callers are built to handle "unknown", not a traceback.
            capture_output=True, text=True, errors="replace", input=stdin,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.rstrip("\n")

    # -- identity ----------------------------------------------------------

    def is_repo(self) -> bool:
        return self._run("rev-parse", "--git-dir") is not None

    def toplevel(self):
        """The repository root, or None when this is not a repository.

        `git -C <dir> ls-files` scopes to <dir> and yields paths relative to
        it, so a checker handed a subdirectory sees a truncated, wrongly-rooted
        file list and reports every root-level document as missing. Every entry
        point resolves the root first; a validator whose answer depends on the
        caller's shell is not a validator.
        """
        out = self._run("rev-parse", "--show-toplevel")
        return Path(out) if out else None

    def has_commits(self) -> bool:
        return self._run("rev-parse", "HEAD") is not None

    def has_history(self) -> bool:
        """More than a shallow clone's single commit, or any tags at all.

        GitHub Actions defaults to fetch-depth 1 with no tags, which makes
        every history-dependent check unanswerable rather than failing.
        """
        if (self.repo / ".git" / "shallow").exists():
            return False
        count = self._run("rev-list", "--count", "HEAD")
        return bool(count) and int(count) > 1

    # -- files -------------------------------------------------------------

    def ls_files(self):
        out = self._run("ls-files")
        return out.splitlines() if out else []

    def last_commit_for(self, path):
        return self._run("log", "-1", "--format=%H", "--", str(path)) or None

    def is_ancestor(self, older, newer) -> bool:
        """True when `older` is strictly an ancestor of `newer`."""
        if not older or not newer or older == newer:
            return False
        return self._run("merge-base", "--is-ancestor", older, newer) is not None

    def commits_touching(self, path, limit=200):
        """Commits that changed `path`, newest first, across renames."""
        out = self._run("log", f"-{limit}", "--follow", "--format=%H", "--",
                        str(path))
        return out.splitlines() if out else []

    def file_at(self, ref, path):
        """The contents of `path` as of `ref`, or None when absent there."""
        return self._run("show", f"{ref}:{path}")

    def file_committed_at(self, path) -> int:
        out = self._run("log", "-1", "--format=%ct", "--", str(path))
        return int(out) if out else 0

    # -- change windows ----------------------------------------------------

    def diff_names(self, base, head="HEAD"):
        """Repo-relative paths that differ between `base` and `head`.

        Returns None — not an empty set — when git cannot answer, because the
        two are opposite verdicts. An empty set says "nothing changed, the
        stamp still holds"; None says "unknown". A caller that conflates them
        certifies a document against a window it never looked at, which is the
        one outcome a currency check exists to prevent. Every caller must treat
        None as blocking.
        """
        if not self.commit_exists(base):
            return None
        out = self._run("diff", "--name-only", f"{base}..{head}")
        if out is None:
            return None
        return {line for line in out.splitlines() if line}

    def commit_before(self, date):
        """The last commit at or before `date` (YYYY-MM-DD), or None.

        The counterpart to `diff_names` for repositories that carry no tags:
        a trust stamp is a date, and a date resolves to a commit. Without this
        every change-window check is tag-only, and a repo that never tags — an
        infrastructure or docs repo, say — silently gets no currency check at
        all rather than a failing one.
        """
        if not date:
            return None
        return self._run("rev-list", "-1", f"--before={date} 00:00", "HEAD") or None

    def changed_since(self, ref_or_date, head="HEAD"):
        """`diff_names` from a commit-ish OR a YYYY-MM-DD date.

        Dates are tried only when the value is not a resolvable commit-ish, so
        a tag named like a date still resolves as a tag.
        """
        if not ref_or_date:
            return None
        if self.commit_exists(ref_or_date):
            return self.diff_names(ref_or_date, head)
        if DATE.fullmatch(str(ref_or_date).strip()):
            base = self.commit_before(ref_or_date)
            return self.diff_names(base, head) if base else None
        return None

    # -- line-level windows and working-tree content -----------------------

    def diff_zero_context(self, base, head=None):
        """`git diff -U0` from `base` to `head`, or to the working tree when
        `head` is None. None — never "" — when git cannot answer.

        Prefixes, quoting, renames and textconv are pinned rather than left to
        the user's config: `diff.noprefix` or a rename pairing would change the
        text a caller parses, and a parse that silently finds no hunks reads as
        "nothing changed".
        """
        if not self.commit_exists(base) or (head and not self.commit_exists(head)):
            return None
        rng = [base] if head is None else [base, head]
        return self._run("-c", "core.quotepath=off", "diff", "-U0",
                         "--no-renames", "--no-color", "--no-ext-diff",
                         "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/",
                         *rng)

    def names_changed(self, base, head=None):
        """Paths differing from `base` — to `head`, or to the working tree
        (staged and unstaged) when `head` is None. None when unanswerable."""
        if not self.commit_exists(base):
            return None
        rng = [base] if head is None else [base, head]
        out = self._run("diff", "--name-only", "--no-renames", "-z", *rng)
        if out is None:
            return None
        return {p for p in out.split(NUL) if p}

    # The three working-tree reads below answer None when git fails, never an
    # empty list: "no untracked files" and "could not ask" are the same
    # all-clear to a caller that cannot tell them apart.

    def untracked(self):
        """Untracked files git does not ignore — new work that no diff shows."""
        out = self._run("ls-files", "--others", "--exclude-standard", "-z")
        return None if out is None else [p for p in out.split(NUL) if p]

    def index_blobs(self):
        """-> {path: blob id} for every tracked path, as staged."""
        out = self._run("ls-files", "-s", "-z")
        if out is None:
            return None
        blobs = {}
        for entry in out.split(NUL):
            meta, _, path = entry.partition("\t")
            parts = meta.split()
            if path and len(parts) >= 2:
                blobs[path] = parts[1]
        return blobs

    def unstaged(self):
        """Tracked paths whose working-tree content differs from the index."""
        out = self._run("diff", "--name-only", "--no-renames", "-z")
        return None if out is None else [p for p in out.split(NUL) if p]

    def hash_files(self, paths):
        """-> {path: blob id} of the working-tree content, for existing files.

        None when git fails, so a caller never mistakes an unhashed tree for an
        unchanged one.
        """
        paths = [p for p in paths if (self.repo / p).is_file()]
        if not paths:
            return {}
        out = self._run("hash-object", "--stdin-paths", stdin="\n".join(paths) + "\n")
        if out is None:
            return None
        ids = out.splitlines()
        return dict(zip(paths, ids, strict=True)) if len(ids) == len(paths) else None

    def git_dir(self):
        out = self._run("rev-parse", "--absolute-git-dir")
        return Path(out) if out else None

    def head(self):
        return self._run("rev-parse", "HEAD") or None

    def resolve(self, ref):
        """The commit sha `ref` names, or None. A cache keyed on a moving name
        like `HEAD` would serve one commit's answer for another's question."""
        return self._run("rev-parse", "--verify", f"{ref}^{{commit}}") if ref else None

    def default_branch(self):
        """origin's HEAD branch, else a local `main` or `master`, else None."""
        remote = self._run("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        for ref in ([remote] if remote else []) + ["main", "master"]:
            if self.commit_exists(ref):
                return ref
        return None

    def merge_base(self, a, b):
        return self._run("merge-base", a, b) or None

    # -- history -----------------------------------------------------------

    def commits(self, since=None, limit=1000):
        """Yield dicts of hash/author/email/body, newest first.

        `since` is a commit-ish; when given, only commits after it are
        returned. An unknown `since` yields nothing rather than raising —
        a mistyped baseline must not crash the checker.
        """
        rng = f"{since}..HEAD" if since else "HEAD"
        # `%x00` is git's own escape. A literal NUL in the argument would make
        # subprocess raise ValueError("embedded null byte") before git ever ran.
        fmt = "%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x00%x00"
        out = self._run("log", f"-{limit}", f"--format={fmt}", rng)
        if not out:
            return []
        entries = []
        for chunk in out.split(NUL + NUL):
            parts = chunk.strip("\n").split(NUL)
            if len(parts) < 6:
                continue
            entries.append({
                "hash": parts[0].strip(),
                "author": parts[1], "author_email": parts[2],
                "committer": parts[3], "committer_email": parts[4],
                "body": parts[5],
            })
        return entries

    def commit_exists(self, ref) -> bool:
        return bool(ref) and self._run("rev-parse", "--verify",
                                       f"{ref}^{{commit}}") is not None

    # -- tags --------------------------------------------------------------

    def tags(self):
        """Tags in creation order — never sorted by version.

        A project that renumbers downward ends up with high tags older than
        its current line; sorting then reads the wrong tag as latest.
        """
        out = self._run("for-each-ref", "--sort=creatordate",
                        "--format=%(refname:short)", "refs/tags")
        return out.splitlines() if out else []

    def tags_by_history(self):
        """Reachable tags in ancestry order, oldest first.

        `creatordate` is the commit date for a lightweight tag, so two tags a
        second apart sort ambiguously — and release ordering is a question
        about ancestry anyway, not about wall-clock time.
        """
        out = self._run("log", "--reverse", "--format=%H%x00%D", "HEAD")
        if not out:
            return []
        ordered = []
        for line in out.splitlines():
            _, _, refs = line.partition(NUL)
            for ref in refs.split(", "):
                ref = ref.strip()
                if ref.startswith("tag: "):
                    ordered.append(ref[len("tag: "):])
        return ordered

    def describe(self):
        """The nearest tag reachable from HEAD."""
        return self._run("describe", "--tags", "--abbrev=0")

    def tags_at_head(self):
        out = self._run("tag", "--points-at", "HEAD")
        return out.splitlines() if out else []

    # -- config ------------------------------------------------------------

    def config(self, key, local_only=False):
        args = ["config"] + (["--local"] if local_only else ["--get"]) + [key]
        if local_only:
            args = ["config", "--local", "--get", key]
        return self._run(*args)


def repo_root(path):
    """Resolve `path` to the git root containing it.

    Returns `path` unchanged when it is not inside a repository, so the
    not-a-repository finding still names what the caller actually asked for.
    """
    return Git(path).toplevel() or Path(path)


def parse_tag(tag):
    """-> (channel, (major, minor, patch), prerelease) or None."""
    m = SEMVER_TAG.match(tag or "")
    if not m:
        return None
    return (
        m.group("channel") or "web",
        (int(m.group("major")), int(m.group("minor")), int(m.group("patch"))),
        m.group("pre"),
    )
