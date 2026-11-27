"""Choose the declared suite's checks for its mode and the change and divide them, and name those
that failed, without changing a check or keeping shared timing state."""

import ast
import functools
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def shard(value=None):
    value = os.environ.get("AK_SHARD", "") if value is None else value
    if not value:
        return 1, 1
    if re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", value):
        number, total = map(int, value.split("/"))
        if number <= total:
            return number, total
    raise ValueError("AK_SHARD must be k/N with 1 <= k <= N")


def listed():
    """The test IDs, checkout-relative paths, in the file AK_ONLY names, one per line: the only
    tests to run, whatever the share. None when AK_ONLY is unset: every test runs."""
    path = os.environ.get("AK_ONLY", "")
    return {line.strip() for line in Path(path).read_text().splitlines()} - {""} if path else None


def name_failed(tests, file="AK_FAILED"):
    """Append the failed tests' IDs to the file AK_FAILED names, one per line, if it names one;
    with `file` "AK_RAN", the IDs of the tests it runs, every_file.py's whole run each as it starts
    it: a run of AK_ONLY's tests counts for none it does not name, as an ID it does not know runs
    nothing; with "AK_FLAKY", those that failed, then passed on a re-run; with "FAILED_PARTS", a
    test file's own failing parts, and with "NOT_THERE" the parts it was asked for and does not
    hold, as every_file.py asks of each file it runs, which names those in "AK_NOT_THERE"."""
    if os.environ.get(file):
        with open(os.environ[file], "a") as fh:
            fh.writelines(f"{test}\n" for test in tests)


def name_timed(times):
    """Write a test file's passing parts' seconds, `times`, to the file PART_TIMES names, if it
    names one, as every_file.py asks of each file it runs."""
    if os.environ.get("PART_TIMES"):
        Path(os.environ["PART_TIMES"]).write_text(json.dumps(times))


def claims(root):
    """go/keys.txt's claims at `root`, one a key: a key file's name, then the parts Go passes,
    none where any of its lines claims it whole.  Two milestones claiming one key each keep their
    line (go/keys.txt merges as a union), and a key run once costs a landing its time once; a
    test its class's claim covers would run twice."""
    merged = {}
    for name, *parts in (line.split() for line in (Path(root) / "go/keys.txt").read_text().splitlines()):
        had = merged.get(name)
        parts = [] if had == [] or not parts else list(dict.fromkeys([*(had or []), *parts]))
        merged[name] = [part for part in parts if not any(part.startswith(f"{other}.") for other in parts)]
    return [[name, *parts] for name, parts in merged.items()]


def parts_of(root, name):
    """The parts the test file `name` is cut into: the Go keys check's claims, any other none."""
    return ([claim[0] for claim in claims(root)]
            if name == "tests/test_go_keys.py" else [])


GO = ("tests/test_go.py", "tests/test_go_builds.py", "tests/test_go_keys.py")


def left_main(root):
    """The commit where the change `root` checks out left its default branch, origin/HEAD, as ak
    names it (gitcall.default_base): None where that cannot be read, as a stand-in folder inside a
    checkout is no checkout, and git would answer for that one."""
    if not Path(root, ".git").exists():
        return None
    return subprocess.run(["git", "-C", str(root), "merge-base", "HEAD", "origin/HEAD"],
                          capture_output=True, text=True).stdout.strip() or None


def change(root):
    """Every path differing between where the change `root` checks out left its default branch
    and HEAD, a rename both: None or none where the suite cannot name it."""
    base = left_main(root)
    # -z ends each path with a NUL; a diff that failed names none
    return base and subprocess.run(["git", "-C", str(root), "diff", "--name-only", "-z",
                                    "--no-renames", base, "HEAD"],
                                   capture_output=True, text=True).stdout.split("\0")[:-1]


def statements(nodes):
    """Each statement of `nodes` and of the blocks they hold: an import is one, and walking every
    expression too costs several times as long."""
    for node in nodes:
        yield node
        for block in ("body", "orelse", "finalbody", "handlers", "cases"):
            yield from statements(getattr(node, block, None) or ())


def imports(root, path):
    """The files of tests/, as paths from `root`, an import in its Python file `path` could load,
    there or not: none where `path` is not there or not Python."""
    try:
        tree = ast.parse(Path(root, path).read_bytes())
    except (OSError, SyntaxError, ValueError):
        return []
    found = []
    for node in statements(tree.body):
        # an absolute import starts in tests/, a test file's own folder, or at the checkout's root
        # where a test puts that on its path (`tests.fixtures.acme`)
        if isinstance(node, ast.Import):
            bases, names = ("tests", ""), [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # a relative import starts in its file's package, one up for each further dot; what it
            # imports from a module may be a module of its own
            bases = (os.path.normpath(os.path.join(path, *[os.pardir] * node.level)),) \
                if node.level else ("tests", "")
            names = [".".join(filter(None, [node.module, name]))
                     for name in [None, *(alias.name for alias in node.names)]]
        else:
            continue
        # each prefix of a dotted name is loaded before the rest, as a package or a plain module
        # whose child may be missing
        for parts in (name.split(".") for name in names if name):
            for end in range(1, len(parts) + 1):
                for module in (os.path.join(base, *parts[:end]) for base in bases):
                    found += [os.path.join(module, "__init__.py"), f"{module}.py"]
    return [file for file in found if file.startswith("tests/")]


def reached(edges, path):
    """`path` and each file it imports, directly or through others, as `edges` gives a file's
    own (imports)."""
    seen, todo = set(), [path]
    while todo:
        if (path := todo.pop()) not in seen:
            seen.add(path)
            todo += edges(path)
    return seen


# How a test names Go's tree: `go` a word of its own, a path part ("go/keys.txt", `REPO / "go"`),
# the go tool and its commands (`["go", "build"]`, "go env GOCACHE") or a Go file ("acme.go"),
# or the claims' file.  Broad on purpose: a test it wrongly takes for Go's only runs, where one
# it missed would hide a red until a change beside Go's ran it.
GO_TREE = re.compile(r"(?<![\w-])go(?![\w-])|keys\.txt")


def names_go(root, path):
    """Whether a string in the code of the Python file `path`, from `root`, names Go's tree
    (GO_TREE): one standing alone, as a docstring, is prose, as a comment is.  False where `path`
    is not there or not Python."""
    try:
        source = Path(root, path).read_bytes().decode(errors="replace")
        # most files never say it: parsing only those that might keeps a scan of all of them short
        if not GO_TREE.search(source):
            return False
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return False
    prose = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr)}
    return any(isinstance(node, ast.Constant) and isinstance(node.value, str)
               and id(node) not in prose and GO_TREE.search(node.value) for node in ast.walk(tree))


def go_left_out(root):
    """The IDs of Go's tests (GO, a claim's `tests/test_go_keys.py::<key>`) a run of every test
    leaves out, as the change `root` checks out (`change`) cannot alter their verdict.  The owner,
    15 Nov 2026: "tests of code that is not shipped run only for changes that touch that code",
    and "its suite runs every test file" (5 Oct) is retracted.  A claim runs in a copy without
    agentkit/ (test_go_keys.LEFT_OUT), so none reads it; a test file but GO, only a claim whose
    key file is or imports it, directly or through other files of tests/.  Any other path, or a
    change the suite cannot name, leaves none out, as on main, where every test still runs."""
    changed = change(root)
    if not changed:
        return set()
    touched = set()
    for path in changed:
        if re.fullmatch(r"tests/test_[^/]*\.py", path) and path not in GO:
            touched.add(path)
        elif not path.startswith("agentkit/"):
            return set()
    keys = [key for key, *_ in claims(root)]
    # Each file is parsed once, and none for a change to agentkit/ alone: every key file and the
    # fixtures most import cost seconds.
    edges = functools.cache(lambda path: imports(root, path))
    run = {key for key in keys if touched & reached(edges, f"tests/{key}.py")} if touched else set()
    return ({f"tests/test_go_keys.py::{key}" for key in keys if key not in run}
            | {"tests/test_go.py"} | (set() if run else {"tests/test_go_builds.py"}))


def python_left_out(root):
    """The IDs of the tests of tests/*.py and smoke.sh's blocks a run of every test leaves out
    where the change `root` checks out (`change`) is Go's alone, every path under go/ or one of
    GO: those it cannot alter, as each runs this checkout's Python bin/ak or imports agentkit/,
    and nothing under go/ reaches either; go_left_out's other half, by the owner's same rule.  A
    test runs where its file's code, or that of a file of tests/ it imports, directly or through
    others, names Go's tree (names_go), and a block of smoke.sh where its code or a file of
    tests/ it names does, with its group (DEPENDENCIES); Go's tests and the static checks
    (STATIC_CHECKS), which read every source file, always.  Any other change, or one the suite
    cannot name, leaves none out."""
    changed = change(root)
    if not changed or not all(path.startswith("go/") or path in GO for path in changed):
        return set()
    names = functools.cache(lambda path: names_go(root, path))
    edges = functools.cache(lambda path: imports(root, path))
    reads = functools.cache(lambda path: any(map(names, reached(edges, path))))
    left = {test for test in (f"tests/{path.name}" for path in Path(root, "tests").glob("*.py"))
            if test not in GO and Path(test).stem not in STATIC_CHECKS and not reads(test)}
    blocks = [(name, re.sub(r"(?m)^\s*#.*", "", body))    # a comment is prose
              for name, body in smoke_blocks(Path(root, SMOKE).read_text()) if name]
    kept = {name for name, code in blocks if GO_TREE.search(code) or any(
        reads(test if test.startswith("tests/") else f"tests/{test}.py")
        for test in re.findall(r"\btests/[\w/.-]+\.py|\btest_\w+", code))}
    kept.update(*(group for group in DEPENDENCIES if kept & set(group)))
    return left | {f"{SMOKE}#{name}" for name, _ in blocks if name not in kept}


def shares(costs, total):
    """Longest first keeps an expensive check or file from lining up with the others."""
    loads, owners = [0] * min(total, len(costs)), {}
    for name in sorted(costs, key=lambda name: (-costs[name], name)):
        piece = min(range(len(loads)), key=lambda piece: (loads[piece], piece))
        owners[name] = piece + 1
        loads[piece] += costs[name]
    return owners


SMOKE = "tests/smoke.sh"
SETUP = "# --- shared setup ----------------------------------------------------------\n"
HEADERS = re.compile(r"^# --- (?:(\w+):)?[^\n]*\n", re.MULTILINE)
# These blocks read fixtures, shell variables or functions made by an earlier block.
DEPENDENCIES = (
    ("retry_start", "9"),
    ("1", "2", "3", "3a", "4", "4b", "4c", "4d", "5", "6", "6b", "6d", "31d"),
    ("6f", "6g"), ("7", "7b"), ("12", "12b"), ("16", "33"),
    ("20", "20b", "20c", "20d", "20e", "20f", "20g", "35"),
    ("21", "22"), ("23", "23b"), ("25", "25b"),
)
# The checks that need the outside world: real models, GitHub, Discord, live meters, the shared
# browser, user systemd and docker.  The live mode (tests/live.sh) runs them and nothing else,
# before a host takes new code and when a harness upgrades; the landing suite runs every other
# check and reaches nothing beyond loopback.  Their offline twins run at landing: 19 the delivery
# path, 41 and 8a-8f the meters, 20e and 20f the seats, 31b and 31c the MCP wiring.
LIVE_CHECKS = {"1", "2", "3", "3a", "4", "4b", "4c", "4d", "5", "6", "6b", "6d", "6f", "6g",
               "31a", "31d", "52"}
# The live checks that may start a model turn, or read the run one made (4b, 4c, 4d): a harness
# call, an `ak run`, or an `ak usage` (1) or a seat's pick (6, 6b, 6d), which reads meters some
# harnesses read with a turn, as Muse's is once its reading has run out.  Asked with
# AK_LIVE_NO_MODEL_CALLS=1, a run leaves them out, so a host checks new code without its logins
# paying turns for it.
MODEL_CALLS = {"1", "3", "3a", "4", "4b", "4c", "4d", "6", "6b", "6d", "31d"}
# The checks that read the checkout alone and take seconds: tests/landing.py runs them first in
# every share and stops there when one fails; every_file.py leaves them to it.
STATIC_CHECKS = ("test_dead_code", "test_boundaries", "test_modules_say_what_they_are", "test_docs",
                 "test_keys_run_ak_from_outside", "test_go_builds")


def smoke_blocks(source):
    source = source[source.index(SETUP):]
    headers = list(HEADERS.finditer(source))
    # Check 0 must stop every piece before any unsafe tmux command can run.
    return [(None if header[1] == "0" else header[1],
             source[header.start():headers[i + 1].start()
                    if i + 1 < len(headers) else len(source)])
            for i, header in enumerate(headers)]


def smoke_owners(blocks, root, total, live=False, offline=False, left=()):
    """Each block's share, of those its mode runs and the run does not leave out (`left`, their
    IDs): the shares are cut from what runs."""
    groups = {name: group[0] for group in DEPENDENCIES for name in group}
    costs = {}
    mine = [(name, body) for name, body in blocks if name is not None
            and (name in LIVE_CHECKS) == live and f"{SMOKE}#{name}" not in left]
    for name, body in mine:
        # Source size estimates the work for new checks too; named test files contribute
        # their size, rather than counting a ten-case file like a hundred-case file.
        # Integer units keep independent processes identical even at equal loads.
        cost = len(body.splitlines()) * 20
        for test in set(re.findall(r"\btest_\w+", body)):
            path = root / "tests" / (test + ".py")
            if path.is_file():
                cost += len(path.read_text().splitlines()) * 3
        if name.startswith("offline_") != offline:
            cost = 0
        group = groups.get(name, name)
        costs[group] = costs.get(group, 0) + cost
    owners = shares(costs, total)
    return {name: owners[groups.get(name, name)] for name, _ in mine}


def smoke_source(source, root, piece, live=False, offline=False, left=()):
    blocks = smoke_blocks(source)
    number, total = piece
    owners = smoke_owners(blocks, root, total, live, offline, left)
    only = listed()
    ran = ""
    if only is not None and SMOKE not in only:
        # AK_ONLY's blocks run whatever the share, each with its group (DEPENDENCIES).
        chosen = {test.removeprefix(f"{SMOKE}#") for test in only}
        chosen.update(*(group for group in DEPENDENCIES if chosen & set(group)))
        owners = {name: number for name in owners if name in chosen}
        # Each is named as run as it starts.
        ran = 'echo "$SMOKE_BLOCK" >>"${AK_RAN:-/dev/null}"\n'
    # Each block starts by setting its ID, a shared one none: acceptance.sh's `no` names the block
    # a check fails in.  A colon leaves an enclosing offline guard valid when this piece owns none
    # of it.
    return "".join(f"SMOKE_BLOCK=\n{body}" if name is None
                   else f"SMOKE_BLOCK='{SMOKE}#{name}'\n{ran}{body}" if owners.get(name) == number
                   else ":\n" for name, body in blocks)


def smoke_mode():
    """smoke_owners' `live` and `offline`, as AGENTKIT_SMOKE_LIVE and AGENTKIT_SMOKE_OFFLINE set."""
    return (os.environ.get("AGENTKIT_SMOKE_LIVE", "0") == "1",
            os.environ.get("AGENTKIT_SMOKE_OFFLINE", "0") == "1")


def smoke_share(path, left=()):
    """The IDs of the blocks of the smoke.sh at `path` that this run's share (AK_SHARD) owns, in
    its mode, of those it does not leave out (`left`): listed in AK_ONLY, they run that share
    again, and nothing else."""
    number, total = shard()
    owners = smoke_owners(smoke_blocks(path.read_text()), path.resolve().parents[1], total,
                          *smoke_mode(), left)
    return [f"{SMOKE}#{name}" for name, owner in owners.items() if owner == number]


def docker_answers():
    """Whether `timeout -k 5 20 docker info` exits 0: check 52 installs this commit in docker."""
    try:
        return subprocess.run(["timeout", "-k", "5", "20", "docker", "info"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except OSError:     # no `timeout` to run
        return False


def main():
    try:
        piece = shard()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    root = path.resolve().parents[1]
    live, offline = smoke_mode()
    # A whole run leaves out the blocks a change to Go alone cannot alter; AK_ONLY's run whatever
    # the change, and so does a live run, which certifies the host and its harnesses, not the
    # change.  AK_LIVE_NO_MODEL_CALLS=1 leaves MODEL_CALLS out of any, and a live run where docker
    # does not answer leaves out 52, so a host without docker still takes new code.
    left = python_left_out(root) if listed() is None and not live else set()
    if os.environ.get("AK_LIVE_NO_MODEL_CALLS") == "1":
        left |= {f"{SMOKE}#{name}" for name in MODEL_CALLS}
    if live and not docker_answers():
        left.add(f"{SMOKE}#52")
    print(smoke_source(path.read_text(), root, piece, live, offline, left), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
