#!/usr/bin/env python3
"""The rest of the `tests:` suite: every tests/test_*.py smoke.sh does not run.

AGENTS.md runs this beside smoke.sh, so a file no task happened to list cannot go red on main
unseen.  It is no part of smoke.sh and never touches its lock: it holds no smoke target and
waits for none.  Each file runs once, in a process of its own from the checkout's root with
no stdin, and without the caller's AGENTKIT_*/AK_* variables: a file started from inside a run
must not pass for part of it (AGENTKIT_RUN, AK_RUN_DEPTH, AK_PARENT_RUN ...).  As many run at
once as live memory fits; waiting files can outnumber cores. Before each start it samples
CPU pressure, waiting while it is high, and rereads host and cgroup headroom.
Unknown files start first, then longest first by their last measured time on this host,
kept under ~/.cache/agentkit/test-times/<hostname>/ outside the checkout.
A failing file, or one reporting no executed cases, fails the whole and is named with its
last lines. Unittest's tally reports the count; other scripts print TESTS_RUN=<count> after
their checks. Python imports under agentkit/, tools/, bin/ and tests/ must be from the
standard library or this repository, including files smoke.sh already ran.

    python3 tests/every_file.py [checkout]
"""

import ast
import os
import re
import subprocess
import sys
import tempfile
import time
import tokenize
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # another piece may be compiling the checkout
sys.path.insert(0, str(REPO))
from agentkit import host, orch
from suite_shares import shard, shares

FILE_MEM_MB = 230   # reservation floor: the measured peak was 229 MB with children;
                    # bigger hosts fit more files, busier or smaller hosts fit fewer
CPU_PRESSURE_MAX = 20  # stall ceiling: background scheduling makes PSI positive even with
                       # idle cores; bigger hosts can still fill memory, busier ones wait
POLL = 0.1          # ceiling on polling waits: contention pauses starts at the next sample,
                    # while an idle host keeps admitting files even beyond its core count
TAIL = 30           # a failing file's last lines: unittest ends on the traceback and tally


def source_files(root):
    # Never descend into another piece's partially written fixtures or Git metadata.
    for directory, folders, names in os.walk(root):
        folders[:] = [name for name in folders
                      if name != ".git" and not name.startswith(".ak-test-")]
        for name in names:
            yield Path(directory) / name


def import_errors(root):
    local = set()
    for path in source_files(root):
        if path.suffix != ".py":
            continue
        local.add(path.stem)
        local.update(path.relative_to(root).parts[:-1])
    allowed = sys.stdlib_module_names | local
    errors = []
    for folder in ("agentkit", "tools", "bin", "tests"):
        for path in sorted(source_files(root / folder)):
            if not path.is_file():
                continue
            if path.suffix != ".py":
                first = path.read_bytes().split(b"\n", 1)[0]
                if not first.startswith(b"#!") or b"python" not in first:
                    continue
            try:
                with tokenize.open(path) as fh:
                    tree = ast.parse(fh.read(), filename=str(path))
            except (SyntaxError, UnicodeError) as exc:
                errors.append(f"{path.relative_to(root)}: invalid Python: {exc}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] not in allowed:
                        errors.append(f"{path.relative_to(root)}:{node.lineno}: import {name} "
                                      "is outside the standard library and repository")
    return errors


def cases_run(output):
    return sum(int(tally or explicit) for tally, explicit in re.findall(
        r"^Ran (\d+) tests? in [^\n]+$|^TESTS_RUN=(\d+)$", output, re.MULTILINE))


LIVE = 'if [ "${AGENTKIT_SMOKE_LIVE:-0}" = 1 ]; then'


def live_blocks(smoke):
    """The line numbers of smoke.sh's live blocks: each from its LIVE guard to the `fi` bash
    closes it with, the first unindented one after which what lies between parses whole."""
    lines, inside = smoke.splitlines(), set()
    for start, line in enumerate(lines):
        if line != LIVE:
            continue
        for end in range(start + 1, len(lines)):
            if lines[end] == "fi":
                parsed = subprocess.run(["bash", "-n"], input="\n".join(lines[start + 1:end]),
                                        capture_output=True, text=True)
                if parsed.returncode == 0 and not parsed.stderr:
                    inside.update(range(start, end + 1))
                    break
        else:
            raise ValueError(f"tests/smoke.sh:{start + 1}: a live guard nothing closes")
    return inside


def smoke_runs(smoke, offline, live=False):
    """The test modules `bash tests/smoke.sh` runs in its plain mode or, `offline`, in the one
    AGENTKIT_SMOKE_OFFLINE=1 selects: every one it names outside a comment and outside the
    blocks that mode skips.  Both skip the argument blocks above the offline block; the plain
    mode skips the offline block, and the offline mode exits at its end.  The live blocks run
    only in the `live` mode, AGENTKIT_SMOKE_LIVE=1, which tests/live.sh starts."""
    names, block, below, skipped = set(), None, False, set() if live else live_blocks(smoke)
    for number, line in enumerate(smoke.splitlines()):
        if number in skipped:
            continue
        opens = block is None and not below and line.startswith("if ") and line.endswith("then")
        if opens and "AGENTKIT_SMOKE_OFFLINE" in line:
            block, below = "offline", True
        elif opens and '"${1:-}"' in line:
            block = "argument"
        elif block and line == "fi":
            if block == "offline" and offline:
                break
            block = None
        elif (block is None or block == "offline" and offline) and not line.lstrip().startswith("#"):
            names.update(re.findall(r"\btest_\w+", line))
    return names


def run_file(root, path, env):
    began = time.monotonic()
    # Files can run beside smoke.sh in the same checkout. Their HOME, temp files and
    # explicit py_compile output must not reach another piece's sandbox or bytecode.
    # tmux canonicalizes TMUX_TMPDIR; a long worktree path cannot hold its socket.
    with tempfile.TemporaryDirectory(prefix="ak-test-file-", dir="/tmp") as sandbox:
        child_env = dict(env, HOME=sandbox, TMPDIR=sandbox,
                         PYTHONPYCACHEPREFIX=str(Path(sandbox) / "pycache"))
        proc = subprocess.run([sys.executable, str(path.relative_to(root))], cwd=root,
                              env=child_env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode(errors="replace"), time.monotonic() - began


def pool_limit(readings):
    """A live memory bound, with no new starts while CPU is contended.

    Reserve each active file's whole peak, even before its children allocate.
    One is the progress floor on a small or unreadable host; high pressure overrides
    it, and absent pressure readings keep an otherwise larger pool serial.
    """
    pressure = host._reading(readings, "cpu_pressure", "slice_cpu_pressure")
    quota = host._reading(readings, "slice_cpu_quota")
    used = host._reading(readings, "slice_cpu_used")
    if ((pressure is not None and pressure > CPU_PRESSURE_MAX)
            or (quota is not None and used is not None and used >= quota)):
        return 0
    room = []
    free = host._reading(readings, "free_mb", "mem_available_mb", "mem_available")
    if free is not None:
        room.append(free)
    slice_used = host._reading(readings, "slice_memory_used_mb")
    slice_high = host._reading(readings, "slice_memory_high_mb")
    if slice_used is not None and slice_high is not None:
        room.append(slice_high - slice_used)
    limits = readings.get("unit_limits")
    if isinstance(limits, (tuple, list)):
        for entry in limits:
            unit = host._unit_memory({"unit_limits": [entry]})
            if unit is not None:
                room.append(unit[1] - unit[0])
    unit = host._unit_memory(readings)
    if unit is not None:
        room.append(unit[1] - unit[0])
    return max(1, int(min(room) / FILE_MEM_MB)) if room and pressure is not None else 1


def last_time(path):
    try:
        took = float(path.read_text())
        if 0 <= took < float("inf"):
            return took
    except (OSError, ValueError):
        pass
    return float("inf")


def save_time(path, took):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Pieces write separate files; atomic replacement also lets other suites read them.
        with tempfile.TemporaryDirectory(dir=path.parent) as scratch:
            saved = Path(scratch) / path.name
            saved.write_text(str(took))
            saved.replace(path)
    except OSError:
        pass  # A missing or unwritable cache must not stop the checks.


def main(root):
    try:
        number, total = shard()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    errors = import_errors(root)
    if errors:
        for error in errors:
            print(f"FAIL  {error}", flush=True)
        return 1
    tests = root / "tests"
    # smoke.sh runs in the mode this caller's environment gives it
    skip = smoke_runs((tests / "smoke.sh").read_text(),
                      os.environ.get("AGENTKIT_SMOKE_OFFLINE", "0") == "1",
                      os.environ.get("AGENTKIT_SMOKE_LIVE", "0") == "1")
    todo = sorted(path for path in tests.glob("test_*.py") if path.stem not in skip)
    # Exclude everything smoke runs before dividing the rest, regardless of its piece.
    owners = shares({path: path.stat().st_size for path in todo}, total)
    todo = [path for path in todo if owners[path] == number]
    cache = Path.home() / ".cache/agentkit/test-times" / os.uname().nodename
    todo.sort(key=lambda path: last_time(cache / path.name), reverse=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
    pending = iter(todo)
    path = next(pending, None)
    began, failed, jobs = time.monotonic(), 0, 0
    with ThreadPoolExecutor(max(1, len(todo))) as pool:
        running = {}
        while path is not None or running:
            for done in list(running):
                if not done.done():
                    continue
                name = running.pop(done).relative_to(root)
                code, out, took = done.result()
                save_time(cache / name.name, took)
                if code == 0 and cases_run(out) > 0:
                    print(f"PASS  {name} ({took:.0f}s)", flush=True)
                    continue
                failed += 1
                reason = f"exit {code}" if code else "no tests ran"
                print(f"FAIL  {name}: {reason} after {took:.0f}s, its last lines:")
                print("\n".join(f"      {line}" for line in out.splitlines()[-TAIL:]), flush=True)
            if path is not None:
                readings = host.host_readings(slice_dir=orch.slice_cgroup,
                                              pressure_window=POLL, all_limits=True)
                # One start per sample lets its startup show in the next CPU reading;
                # submitting every file at once would bypass later pressure and memory changes.
                if len(running) < pool_limit(readings):
                    running[pool.submit(run_file, root, path, env)] = path
                    jobs = max(jobs, len(running))
                    path = next(pending, None)
            if running:
                wait(running, timeout=POLL if path is not None else None,
                     return_when=FIRST_COMPLETED)
            elif path is not None:
                time.sleep(POLL)
    print(f"test files: {len(todo) - failed} passed, {failed} failed, {jobs} at once, "
          f"{time.monotonic() - began:.0f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO))
