"""The static import graph of a repository's own Python, read with `ast`.

Nothing is imported or executed: a module is a node, every import statement
anywhere in it — module level, inside a function, inside `try` — is an edge,
and so is every string constant that names a repo module (`mock.patch`
targets, `importlib.import_module("x.y")`, `pytest_plugins`) or a repo `.py`
file (a script run in a subprocess, a module loaded from its path). Edges only
ever widen what a change reaches.

Imports resolve against the repository root first. A name with no match there
is tried as a suffix of every repo module (`import docmap` after a
`sys.path.insert(0, "scripts")`), and every match counts. A name that resolves
nowhere is taken to be third-party.

conftest.py is modelled at fixture grain, because a test does not import its
conftest — pytest injects fixtures by NAME. A test depends on each ancestor
conftest's module-level imports and hooks, on its autouse fixtures, and on the
fixtures it names (any parameter or string in the file), transitively through
the fixtures those fixtures request. Without that grain, one `app` fixture
importing the application factory would put every test behind every module.

Two closures, because two things differ in what they execute. A test and the
fixtures it names EXERCISE what they import, so they reach through every
import, lazy ones inside functions included — a test calling `vet()` runs the
modules `vet()` imports on demand. An autouse fixture or a conftest's module
level only IMPORTS for every test; it resets state, it does not drive the code.
Those reach what they import directly, then only what runs at import time.
Measured on a 558-test suite, the first rule alone put every test behind every
module, through one autouse fixture resetting a config singleton.

What it cannot see, and the caller must say so: a non-constant dynamic import,
a file read as text, a subprocess, a fixture fetched by a computed name.
"""

import ast
import re
import sys
from pathlib import PurePosixPath

DOTTED = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")
STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()))
DYNAMIC_CALLS = {"import_module", "__import__", "run_module", "run_path"}


def module_name(path):
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def is_test_file(path):
    name = PurePosixPath(path).name
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


class Graph:
    """Nodes are repo-relative paths; conftest fixtures are `path#fixture`."""

    def __init__(self, sources):
        # sources: {path: text or None}; None = known to exist but unreadable.
        self.sources = sources
        self.by_module, self.by_last, self.tops = {}, {}, set()
        self.by_name = {}
        for path in sources:
            self.by_name.setdefault(PurePosixPath(path).name, set()).add(path)
            mod = module_name(path)
            self.tops.add(mod.split(".", 1)[0])
            self.by_module.setdefault(mod, set()).add(path)
            self.by_last.setdefault(mod.rsplit(".", 1)[-1], set()).add(path)
        self.edges, self.eager = {}, {}
        self.unparseable, self.dynamic = set(), set()
        self.fixtures = {}        # conftest -> {name: node}
        self.autouse = {}         # conftest -> [node]
        self.fixture_deps = {}    # node -> set of fixture names it requests
        self.names_used = {}      # test path -> fixture names it may request
        for path, text in sources.items():
            self._read(path, text)

    # -- resolution ---------------------------------------------------------

    def resolve(self, dotted, frm=None, level=0):
        """-> set of paths a dotted import may load, including its packages."""
        if level:
            base = PurePosixPath(frm).parent.parts
            base = base[:len(base) - (level - 1)] if level > 1 else base
            dotted = ".".join([*base, dotted] if dotted else base)
        hits, parts = set(), dotted.split(".") if dotted else []
        anchored = bool(parts) and parts[0] in self.tops
        for i in range(1, len(parts) + 1):
            hits |= self.by_module.get(".".join(parts[:i]), set())
        if not hits and not anchored and parts and parts[0] not in STDLIB:
            for i in range(len(parts), 0, -1):
                tail = ".".join(parts[:i])
                found = {p for p in self.by_last.get(parts[i - 1], ())
                         if module_name(p) == tail or module_name(p).endswith("." + tail)}
                if found:
                    hits |= found
                    break
        return hits

    def _files_named(self, text):
        """Repo files a path string may mean: itself, or any file it is the
        tail of (`"docmap.py"`, `"scripts/x.py"`, an absolute path)."""
        tail = text.lstrip("./")
        return {p for p in self.by_name.get(PurePosixPath(tail).name, ())
                if p == tail or p.endswith("/" + tail) or tail.endswith("/" + p)}

    # -- reading ------------------------------------------------------------

    def _read(self, path, text):
        try:
            tree = ast.parse(text) if text is not None else None
        except (SyntaxError, ValueError):
            tree = None
        if tree is None:
            self.unparseable.add(path)
            self.edges[path] = set()
            return
        is_conftest = PurePosixPath(path).name == "conftest.py"
        if is_conftest:
            self._read_conftest(path, tree)
        else:
            self.edges[path] = self._imports(path, tree)
            self.eager[path] = self._imports(path, tree, eager=True)
        if is_test_file(path) or is_conftest:
            self.names_used[path] = _names_in(tree)

    def _imports(self, path, node, eager=False):
        """Import targets under `node`. `eager` stops at function bodies and
        ignores strings: what runs when the module is imported, and no more."""
        out = set()
        for n in _walk(node, eager):
            if isinstance(n, ast.Import):
                for a in n.names:
                    out |= self.resolve(a.name)
            elif isinstance(n, ast.ImportFrom):
                mod = n.module or ""
                out |= self.resolve(mod, path, n.level)
                for a in n.names:
                    out |= self.resolve(f"{mod}.{a.name}" if mod else a.name, path, n.level)
            elif eager:
                continue
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) \
                    and DOTTED.match(n.value) and n.value.split(".")[0] in self.tops:
                out |= self.resolve(n.value)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) \
                    and n.value.endswith(".py") and " " not in n.value:
                out |= self._files_named(n.value)
            elif isinstance(n, ast.Call) and _call_name(n) in DYNAMIC_CALLS:
                if not (n.args and isinstance(n.args[0], ast.Constant)):
                    self.dynamic.add(path)
        out.discard(path)
        return out

    def _read_conftest(self, path, tree):
        funcs = {n.name: n for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        fixtures = {name: n for name, n in funcs.items() if _fixture_kind(n)}
        helpers = {name: n for name, n in funcs.items() if name not in fixtures}
        claimed = set()
        self.fixtures[path], self.autouse[path] = {}, []
        for name, fn in fixtures.items():
            node = f"{path}#{name}"
            body, seen = set(), {name}
            stack = [fn]
            while stack:
                cur = stack.pop()
                body |= self._imports(path, cur)
                for called in _called_names(cur):
                    if called in helpers and called not in seen:
                        seen.add(called)
                        claimed.add(called)
                        stack.append(helpers[called])
            self.edges[node] = body
            self.fixtures[path][name] = node
            self.fixture_deps[node] = {a.arg for a in fn.args.args}
            if _fixture_kind(fn) == "autouse":
                self.autouse[path].append(node)
        # Module level, hooks, and any helper no fixture calls: runs for all.
        module = set()
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if n.name in fixtures or n.name in claimed:
                    continue
            module |= self._imports(path, n)
        self.edges[path] = module

    # -- the question -------------------------------------------------------

    def test_roots(self, test):
        """-> (exercised, imported-only) nodes a test depends on besides its
        own imports: the fixtures it names, and its conftests' module level
        plus their autouse fixtures."""
        ancestors = [c for c in self.fixtures
                     if PurePosixPath(test).parent.is_relative_to(PurePosixPath(c).parent)]
        imported, roots = set(ancestors), set()
        wanted, seen = set(self.names_used.get(test, ())), set()
        for c in ancestors:
            imported.update(self.autouse[c])
            for node in self.autouse[c]:
                wanted |= self.fixture_deps[node]
        while wanted:
            name = wanted.pop()
            if name in seen:
                continue
            seen.add(name)
            for c in ancestors:
                node = self.fixtures[c].get(name)
                if node:
                    roots.add(node)
                    wanted |= self.fixture_deps[node]
        return roots, imported - roots

    def reach(self, start, imported=()):
        """Everything `start` exercises, plus what `imported` loads at import
        time — its direct imports, then eager edges only."""
        seen, stack = set(), list(start)
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self.edges.get(node, ()))
        stack = [m for node in imported for m in self.edges.get(node, ())]
        seen |= set(imported)
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self.eager.get(node, ()))
        return seen

    def tests_reaching(self, changed, tests):
        """-> {test: [changed paths it reaches]} for the given test files."""
        changed = set(changed)
        out = {}
        for test in tests:
            named, imported = self.test_roots(test)
            hit = self.reach({test} | named, imported) & changed
            if hit:
                out[test] = sorted(hit)
        return out


def _walk(node, eager):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        for child in ast.iter_child_nodes(n):
            if eager and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            stack.append(child)


def _call_name(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def _called_names(fn):
    return {n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def _fixture_kind(fn):
    """None, "fixture" or "autouse" for a function's pytest.fixture decorator."""
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name != "fixture":
            continue
        if isinstance(d, ast.Call):
            for kw in d.keywords:
                if kw.arg == "autouse" and isinstance(kw.value, ast.Constant) and kw.value.value:
                    return "autouse"
        return "fixture"
    return None


def _names_in(tree):
    """Every name a file could request as a fixture: parameters and strings."""
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = n.args
            names |= {a.arg for a in args.args + args.kwonlyargs + args.posonlyargs}
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 80:
            names |= set(re.findall(r"[A-Za-z_]\w*", n.value))
    return names
