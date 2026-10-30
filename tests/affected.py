"""The tests a change can affect: `selection` lists the suite's test IDs to run for a change
editing `paths`, read as everything between its target and HEAD.

Every static check runs, and of the test files and smoke.sh's blocks (`tests/smoke.sh#<check>`,
live checks aside: the landing suite never runs them) each that
- the change edits, a block's edits counting those to the text every block runs after,
- mentions, in its text or in a word of a test file's name, a name the change edits: an edited
  file's path or file name, a Python file's stem, or a top-level function, class or constant the
  diff of a Python file other than a test file adds, removes or changes, in any spelling of its
  words (`status_bar` names `statusbar`); importing a module names its stem,
- imports a module that imports such a function, class or constant from the edited module or
  its package: it calls through it, as gc.py calls each harness through `harness`,
and each block running a test file chosen.  A change to the suite's own machinery, or one with
no base to read it against, can affect every test.
"""

import ast
import functools
from pathlib import Path
import re
import subprocess

from suite_shares import LIVE_CHECKS, SETUP, SMOKE, STATIC_CHECKS, smoke_blocks

MACHINERY = {"tests/landing.py", "tests/every_file.py", "tests/suite_shares.py",
             "tests/affected.py"}
TEST_FILE = re.compile(r"tests/test_[^/]*\.py")
IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+([\w.]+)[ \t]+)?import[ \t]+(\([^)]*\)|[^\n#;]*)",
                    re.MULTILINE)


def definitions(source):
    """Each top-level function, class and constant `source` defines, by name: their code."""
    try:
        body = ast.parse(source).body
    except SyntaxError:
        return {}
    found = {}
    for node in body:
        names = ([node.name] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                  ast.ClassDef))
                 else [name.id for name in ast.walk(node)
                       if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store)])
        for name in names:
            found.setdefault(name, []).append(ast.dump(node))
    return found


def words(text):
    """Every identifier in `text`, and each run of two or more of its words written as one."""
    found = set()
    for word in set(re.findall(r"\w+", text)):
        found.add(word)
        parts = [part for part in word.split("_") if part]
        found.update("".join(parts[i:j]) for i in range(len(parts))
                     for j in range(i + 2, len(parts) + 1))
    return found


def imports(text):
    """The modules `text` imports, and each package they are in; read, not parsed: it is quicker."""
    names = set()
    for module, listed in IMPORT.findall(text):
        for alias in re.findall(r"([\w.]+)(?:\s+as\s+\w+)?", listed.strip("()")):
            parts = f"{module}.{alias}".split(".") if module else alias.split(".")
            names.update(".".join(parts[:end]) for end in range(1, len(parts) + 1))
    return names


def checks(source):
    """smoke.sh's blocks the landing suite runs, by check, and under None what each runs after."""
    if SETUP not in source:
        return {}
    blocks = smoke_blocks(source)
    return {None: source[:source.index(SETUP)] + "".join(body for name, body in blocks
                                                         if name is None),
            **{name: body for name, body in blocks
               if name is not None and name not in LIVE_CHECKS}}


def selection(root, paths, target):
    """The test IDs to run, static checks first, for a change to the repository at `root` editing
    `paths`, relative to it, between `target` and HEAD; None where every test runs."""
    root, paths = Path(root).resolve(), set(paths)
    base = subprocess.run(["git", "merge-base", target, "HEAD"], cwd=root, capture_output=True,
                          text=True).stdout.strip()
    if not base or paths & MACHINERY:
        return None

    def before(path):
        shown = subprocess.run(["git", "show", f"{base}:{path}"], cwd=root, capture_output=True,
                               text=True)
        return shown.stdout if shown.returncode == 0 else ""

    def now(path):
        return (root / path).read_text() if (root / path).is_file() else ""

    stems, names, through, literals = set(), set(), set(), set()
    for path in paths:
        literals.update({path, Path(path).name})
        if path.endswith(".py"):
            # A package's module is its folder: importing anything in it runs its __init__.py.
            folder, stem = (root / path).parent, Path(path).stem
            stem, package = ((folder.name, folder.parent.name) if stem == "__init__"
                             else (stem, folder.name))
            stems.add(stem)
            # Nothing loads names from a test file: its `REPO` is its own.
            if TEST_FILE.fullmatch(path):
                continue
            old, new = definitions(before(path)), definitions(now(path))
            # In source order: of a name bound twice, the last binding holds.
            edits = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
            names |= edits
            through |= {f"{where}.{name}" for name in edits for where in {stem, package} - {""}}
    literal = re.compile("|".join(rf"(?<![\w.]){re.escape(text)}(?!\w)" for text in literals))

    def mentions(text):
        found = words(text)
        return literal.search(text) or any(
            name in found or "_" in name.strip("_") and name.replace("_", "") in found
            for name in stems | names)

    @functools.cache
    def uses(module):
        path = next(filter(Path.is_file, (folder / f"{module.replace('.', '/')}{end}"
                                          for folder in (root, root / "tests")
                                          for end in (".py", "/__init__.py"))), None)
        return path is not None and any(f".{imported}".endswith(f".{used}") for used in through
                                        for imported in imports(path.read_text()))

    tests = set()
    for path in (root / "tests").glob("test_*.py"):
        text = path.read_text()
        if (f"tests/{path.name}" in paths
                or mentions(f"{text}\n{path.stem} {path.stem.replace('_', ' ')}")
                or any(map(uses, imports(text)))):
            tests.add(f"tests/{path.name}")

    blocks = checks(now(SMOKE))
    old = checks(before(SMOKE)) if SMOKE in paths else blocks
    edited = {name for name in blocks if old.get(name) != blocks[name]}
    ran = {Path(test).stem for test in tests}
    chosen = {f"{SMOKE}#{name}" for name, body in blocks.items() if name is not None and (
        edited & {None, name} or mentions(body) or set(re.findall(r"\btest_\w+", body)) & ran)}
    static = [f"tests/{name}.py" for name in STATIC_CHECKS]
    return list(dict.fromkeys([*static, *sorted(tests), *sorted(chosen)]))
