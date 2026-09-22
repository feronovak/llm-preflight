"""`affected` — which tests a change can reach, and nothing it cannot prove.

The one failure this must not have is an empty target list when code changed:
that is a gate reporting green over tests it never ran. So every changed file
is placed somewhere — a test that reaches it, a package whose own test runner
takes it, or the full suite for its stack with the reason written out — and a
file that cannot be placed is a reason to run everything, never a file to drop.

Python targets come from `pyimports`, plus two widenings no graph provides:
files whose source names the changed file as text, and the contract's
`tests-always-run`. A data file's readers are every file naming it or any
directory above it, because a test that walks a directory never names the
file it reads. JS/TS packages get their changed files, for `vitest related`,
because vite's own module graph answers that question better than a regex
could — plus any test in them that names a changed file or its directory.

What git cannot see is compared too: an interpreter, installed packages,
`node_modules` or an `untracked-inputs` directory that moved since the last
green run runs that stack's full suite.

Exit codes: 0 — run the listed targets. 3 — no code changed since the base, so
there is nothing to run. 2 — the question could not be answered.
"""

import json
import re
import sys
from pathlib import Path, PurePosixPath

from . import changes, contract as contract_mod
from .gitio import Git, repo_root
from .pyimports import Graph, is_test_file

NOTHING = 3

FULL_PY = ("**/conftest.py", "**/pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini",
           "setup.py", ".coveragerc", "**/requirements*.txt", "requirements/**",
           "**/constraints*.txt", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock")
JS_CONFIG = ("package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
             "pnpm-lock.yaml", "pnpm-workspace.yaml", "vite.config.*", "vitest.config.*",
             "vitest.workspace.*", "vitest.setup.*", "tsconfig*.json", ".babelrc*",
             "babel.config.*", "jest.config.*", ".npmrc", ".nvmrc")
JS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue",
               ".svelte", ".css", ".scss", ".sass", ".less", ".json", ".html", ".svg")
TS_SUFFIXES = (".ts", ".tsx", ".mts", ".cts")
ROOT_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
SETUP_FILES = re.compile(r"setupFiles\s*:\s*\[([^\]]*)\]|setupFiles\s*:\s*['\"]([^'\"]+)")
# A helper this many tests import is cheaper to answer with everything — and a
# shared helper is the one place a fixture reaches tests by name, not import.
HELPER_FANOUT = 0.10


def packages(tracked):
    """Directories holding a package.json, deepest first and the root "."
    last — a nested package owns its files before any ancestor can."""
    dirs = {str(PurePosixPath(p).parent) for p in tracked
            if PurePosixPath(p).name == "package.json" and "node_modules" not in p}
    return sorted(dirs, key=lambda d: (d == ".", -d.count("/"), d))


def owning_package(path, pkgs):
    """The package a file belongs to. The root package claims only JS/TS
    source and its own top-level config: in a mixed repo, a JSON fixture under
    `tests/` is a Python concern, not the root package's."""
    for d in pkgs:
        if d == ".":
            if path.endswith(ROOT_SUFFIXES) or (
                    "/" not in path and changes.matches(path, JS_CONFIG)):
                return d
        elif path.startswith(d + "/"):
            return d
    return None


def _setup_files(repo, pkg):
    out = set()
    for cfg in Path(repo, pkg).glob("vite*.config.*"):
        for a, b in SETUP_FILES.findall(cfg.read_text(errors="ignore")):
            for item in re.findall(r"['\"]([^'\"]+)['\"]", a) + ([b] if b else []):
                out.add(str(PurePosixPath(pkg, item.lstrip("./"))) if pkg != "." else item.lstrip("./"))
    return out


class Plan:
    def __init__(self, base_kind, base, note, changed):
        self.base_kind, self.base, self.note = base_kind, base, note
        self.changed = sorted(changed)
        self.py = {"full": False, "reasons": [], "tests": set(), "always": set(),
                   "outside": []}
        self.pkgs = {}
        self.notes = []
        self.explained = set()   # changed paths a note accounts for
        self.in_scope = []       # every test file under the selected roots

    def pkg(self, d):
        return self.pkgs.setdefault(d, {"dir": d, "full": False, "reasons": [],
                                        "files": set(), "typescript": False,
                                        "always": set()})

    def py_full(self, reason):
        self.py["full"] = True
        self.py["reasons"].append(reason)

    @property
    def exit_code(self):
        forced = self.py["full"] or any(p["full"] for p in self.pkgs.values())
        return NOTHING if not self.changed and not forced else 0

    def as_dict(self):
        chosen = self.py["tests"] | self.py["always"]
        # The in-scope tests NOT selected: collecting the roots and deselecting
        # these runs the selection in the full run's order and import context.
        deselect = [] if self.py["full"] or not chosen else \
            sorted(t for t in self.in_scope if t not in chosen)
        py = dict(self.py, tests=sorted(self.py["tests"]), always=sorted(self.py["always"]),
                  deselect=deselect)
        pk = [dict(p, files=sorted(p["files"]), always=sorted(p["always"]))
              for p in sorted(self.pkgs.values(), key=lambda p: p["dir"])]
        return {"base": {"kind": self.base_kind, "ref": self.base, "note": self.note},
                "changed": self.changed, "python": py, "packages": pk,
                "notes": self.notes, "exit": self.exit_code}


def plan(repo, test_roots=(), base=None):
    repo = repo_root(Path(repo))
    git = Git(repo)
    tracked = git.ls_files()
    contract = contract_mod.load(repo, tracked)
    if contract.path and contract.errors:
        # A contract that does not parse has lost `tests-always-run` and
        # `doc-paths` with it; a plan without them skips what they protect.
        raise ValueError(f"the contract in {contract.path} does not parse: "
                         + "; ".join(contract.errors))
    doc_paths = changes.doc_paths_for(contract)

    if base:
        changed = changes.code_changed(repo, base, doc_paths)
        kind, note = "explicit", f"since {base}, as given"
    else:
        kind, base, changed, note = changes.resolve_base(repo, doc_paths)
    if changed is None:
        raise ValueError(f"cannot tell what changed ({note}); run the full suite")
    p = Plan(kind, base, note, changed)
    pkgs = packages(tracked)
    if kind == "last-green":
        _environment(p, repo, contract, pkgs)
    if not changed:
        return p

    untracked = git.untracked()
    if untracked is None:
        raise ValueError("git could not list untracked files")
    universe_all = sorted({*tracked, *untracked})
    py_files = [f for f in universe_all if f.endswith(".py") and (repo / f).is_file()]
    sources = {f: (repo / f).read_text(errors="ignore") for f in py_files}
    js = {f: (repo / f).read_text(errors="ignore") for f in universe_all
          if f.endswith(ROOT_SUFFIXES) and owning_package(f, pkgs) is not None
          and (repo / f).is_file()}
    for f in changed:
        if f.endswith(".py") and f not in sources:
            sources[f] = ""   # deleted: still a node, so its importers are found
    graph = Graph(sources)
    roots = [r.rstrip("/") for r in test_roots]
    tests = [f for f in sources if is_test_file(f) and (repo / f).is_file()
             and (not roots or any(f == r or f.startswith(r + "/") for r in roots))]
    test_set = set(tests)
    all_tests = [f for f in sources if is_test_file(f)]
    p.in_scope = tests

    _place_changes(p, repo, graph, sources, tests, test_set, all_tests, pkgs, js)
    _always(p, contract, universe_all, pkgs)
    if not p.py["full"] and len(p.py["tests"]) >= len(tests) > 0:
        p.py_full("every test in scope reaches the change")
    placed = (p.py["full"] or p.py["tests"] or p.py["always"]
              or any(pk["full"] or pk["files"] for pk in p.pkgs.values()))
    if not placed and not set(p.changed) <= p.explained:
        # The invariant, stated as code: code changed, so something runs.
        p.py_full("code changed and no target could be placed for it")
    return p


def _environment(p, repo, contract, pkgs):
    """Full suites for whatever moved outside git since the last green run."""
    marker = changes.read_marker(repo)
    now = changes.environment(repo, contract.untracked_inputs)
    for key, before, after in changes.env_drift(marker, now):
        why = ("the last-green marker predates environment fingerprints"
               if not isinstance(marker.get("env"), dict)
               else "it could not be read" if before is None or after is None
               else "it changed")
        where = changes.env_path(key)
        if where is None:
            p.py_full(f"the Python environment moved since the last green run "
                      f"(`{key}`: {why})")
        elif key.startswith("node_modules:"):
            d = key.partition(":")[2]
            # Root dependencies are hoisted, as for the root lockfile.
            for q in (p.pkg(x) for x in (pkgs if d == "." else [d])):
                q["full"] = q["typescript"] = True
                q["reasons"].append(f"`{where}` moved since the last green run ({why})")
        else:
            pkg = next((d for d in pkgs if d != "." and where.startswith(d + "/")), None)
            if pkg is not None:
                q = p.pkg(pkg)
                q["full"] = q["typescript"] = True
                q["reasons"].append(f"untracked input `{where}` moved since the last "
                                    f"green run ({why})")
            p.py_full(f"untracked input `{where}` moved since the last green run ({why})")


def _place_changes(p, repo, graph, sources, tests, test_set, all_tests, pkgs, js):
    setup = {f for d in pkgs for f in _setup_files(repo, d)}
    js_tests = [f for f in js if is_js_test(f)]
    py_changed = []
    for path in p.changed:
        name = PurePosixPath(path).name
        if changes.matches(path, FULL_PY):
            p.py_full(f"`{path}` configures how every test runs")
            continue
        pkg = owning_package(path, pkgs)
        if pkg is not None and not path.endswith(".py"):
            entry = p.pkg(pkg)
            if changes.matches(name, JS_CONFIG) or path in setup:
                # Root dependencies are hoisted: every package resolves its
                # runner and libraries through the root's node_modules.
                for d in (pkgs if pkg == "." else [pkg]):
                    q = p.pkg(d)
                    q["full"] = True
                    q["reasons"].append(f"`{path}` configures the package's build or tests")
                    q["typescript"] = True
            elif not (repo / path).exists():
                # vitest traces dependents through the file; a deleted one is
                # no longer in its graph, so the tests that imported it are
                # exactly the ones `related` cannot find.
                entry["full"] = True
                entry["typescript"] = True
                entry["reasons"].append(f"`{path}` was deleted; its importers cannot be traced")
            else:
                entry["files"].add(path)
                entry["typescript"] |= path.endswith(TS_SUFFIXES)
            # A test that reads this file as text is a reader no module graph
            # finds — a Python test, or a JS test reading source by path. For
            # a data file, naming its directory counts too; for source it
            # would be every file importing a sibling.
            data = not path.endswith(ROOT_SUFFIXES)
            for t in _text_readers(path, sources, tests, dirs=data):
                p.py["tests"].add(t)
            _js_readers(p, path, js, js_tests, pkgs, dirs=data)
            continue
        if path.endswith(".py"):
            py_changed.append(path)
            continue
        readers = _text_readers(path, sources, list(sources), dirs=True)
        js_found = _js_readers(p, path, js, list(js), pkgs, dirs=True)
        if not readers and not js_found:
            p.py_full(f"`{path}` is not code any graph reads, and nothing names it "
                      f"or its directory")
            continue
        via = set(readers) & test_set
        mods = [r for r in readers if r not in test_set]
        if mods:
            via |= set(graph.tests_reaching(mods, tests))
        if readers and not via:
            p.py_full(f"`{path}` is read by {', '.join(sorted(readers)[:3])}, which no "
                      f"test in scope reaches")
        p.py["tests"] |= via

    if not py_changed:
        return
    reached = graph.tests_reaching(py_changed, tests)
    by_path = {}
    for test, hits in reached.items():
        for h in hits:
            by_path.setdefault(h, set()).add(test)
    for path in py_changed:
        if path in test_set:
            p.py["tests"].add(path)
            continue
        if is_test_file(path):
            if not (repo / path).exists():
                p.explained.add(path)
                p.notes.append(f"`{path}` was deleted; there is nothing of it left to run")
                continue
            p.py["outside"].append(path)
            p.explained.add(path)
            p.notes.append(f"`{path}` is a test outside the selected roots; --full runs it")
            continue
        hits = by_path.get(path, set()) | set(_text_readers(path, sources, tests))
        if not hits:
            if path in graph.unparseable or path in graph.dynamic:
                p.py_full(f"`{path}` " + ("does not parse" if path in graph.unparseable
                                          else "imports by computed name")
                          + "; what reaches it cannot be resolved")
                continue
            # Resolved, not unresolvable: the graph answered, and the answer
            # is that no test in scope covers this file. Said, never dropped.
            outside = bool(graph.tests_reaching([path], all_tests))
            p.explained.add(path)
            p.notes.append(f"`{path}`: " + (
                "only tests outside the selected roots reach it; --full runs them"
                if outside else "no test reaches it — it has no coverage to run"))
            continue
        if _in_test_tree(path) and len(hits) > max(20, HELPER_FANOUT * len(tests)):
            p.py_full(f"`{path}` is a test helper {len(hits)} tests import")
            continue
        p.py["tests"] |= hits
    # A test whose imports are computed, or which cannot be parsed, reaches an
    # unknown set of modules; it runs whenever any Python changed.
    for test in sorted((graph.dynamic | graph.unparseable) & test_set):
        p.py["tests"].add(test)


def _always(p, contract, universe_all, pkgs):
    globs = contract.tests_always_run if contract else []
    if not globs:
        return
    for path in universe_all:
        if not changes.matches(path, globs):
            continue
        pkg = owning_package(path, pkgs)
        if pkg is not None and not path.endswith(".py"):
            p.pkg(pkg)["always"].add(path)
        else:
            p.py["always"].add(path)
    unmatched = [g for g in globs if not any(changes.matches(f, [g]) for f in universe_all)]
    for g in unmatched:
        p.notes.append(f"tests-always-run `{g}` matches no file")


def _in_test_tree(path):
    return any(part in ("tests", "test", "testing") for part in PurePosixPath(path).parts[:-1])


def is_js_test(path):
    parts = PurePosixPath(path).parts
    return "__tests__" in parts or bool(re.search(r"\.(test|spec)\.", parts[-1]))


def _js_readers(p, path, js, candidates, pkgs, dirs):
    """Add each JS/TS file naming `path` (or, with `dirs`, its directory) to
    its own package's changed files — `vitest related` runs a test named to
    it, and the tests importing a source file named to it. -> the readers."""
    found = _text_readers(path, js, candidates, dirs=dirs)
    for f in found:
        pkg = owning_package(f, pkgs)
        entry = p.pkg(pkg)
        entry["files"].add(f)
        entry["typescript"] |= f.endswith(TS_SUFFIXES)
    return found


# A directory is named as a path: a quoted literal, or a fragment of one,
# bounded by a quote or a slash on each side. `'fixtures'`, `"a/fixtures/x"`
# and `` `${root}/fixtures` `` name it; `from tests import x` and the word in
# prose do not.
EDGE = "[\"'`/]"


def directory_fragments(path):
    """Every run of consecutive components of each directory above `path`:
    for `a/b/c.json`, `a/b`, `a`, `b`."""
    parts = PurePosixPath(path).parts[:-1]
    return {"/".join(parts[i:j]) for i in range(len(parts)) for j in range(i + 1, len(parts) + 1)}


def names_directory(text, fragment):
    return re.search(f"(?<={EDGE}){re.escape(fragment)}(?={EDGE})", text) is not None


def _text_readers(path, sources, candidates, dirs=False):
    """Files in `candidates` whose text names `path` — by repo-relative path,
    or by file name for anything whose name is not a bare module import.

    `dirs` adds every file naming a directory above `path`, by name or by a
    path fragment. A reader that walks a directory never names the file it
    reads, so for a data file, naming the file is not the whole reader set.
    """
    name = PurePosixPath(path).name
    needles = {path, name} if "." in name else {path}
    frags = directory_fragments(path) if dirs else ()
    return [c for c in candidates if c != path and (
        any(n in sources.get(c, "") for n in needles)
        or any(names_directory(sources.get(c, ""), f) for f in frags))]


# -- CLI --------------------------------------------------------------------

def main(args):
    try:
        result = plan(args.repo, test_roots=args.tests, base=args.base)
    except ValueError as exc:
        print(f"affected: {exc}", file=sys.stderr)
        return 2
    d = result.as_dict()
    if args.json:
        print(json.dumps(d, indent=2, sort_keys=True))
    elif args.format in ("pytest-args", "pytest-deselect"):
        py = d["python"]
        roots = args.tests or ["."]
        chosen = sorted(set(py["tests"]) | set(py["always"]))
        if py["full"]:
            print(" ".join(roots))
        elif chosen and args.format == "pytest-args":
            print(" ".join(chosen))
        elif chosen:
            # Outside every root, a file must be named; inside, deselection
            # keeps pytest's own order and every module it would import.
            outside = [t for t in chosen if not any(
                t == r or t.startswith(r.rstrip("/") + "/") or r == "." for r in roots)]
            print(" ".join(roots + outside + [f"--deselect={t}" for t in py["deselect"]]))
    else:
        _print(d)
    return result.exit_code


def _print(d):
    b = d["base"]
    print(f"base: {b['kind']} — {b['note']}")
    if d["exit"] == NOTHING:
        print("no code changed; nothing to run (exit 3)")
        return
    print(f"{len(d['changed'])} changed non-doc file(s)")
    py = d["python"]
    if py["full"]:
        print("python: FULL suite —")
        for r in py["reasons"]:
            print(f"  {r}")
    else:
        print(f"python: {len(py['tests'])} test file(s) + {len(py['always'])} always-run")
        for t in sorted(set(py["tests"]) | set(py["always"])):
            print(f"  {t}")
    for pk in d["packages"]:
        head = "FULL" if pk["full"] else f"{len(pk['files'])} changed file(s)"
        print(f"package {pk['dir']}: {head}" + (" · tsc" if pk["typescript"] else ""))
        for r in pk["reasons"]:
            print(f"  {r}")
    for n in d["notes"]:
        print(f"note: {n}")
