#!/usr/bin/env python3
"""The rest of the `tests:` suite: every tests/test_*.py neither smoke.sh nor landing.py's
static checks (STATIC_CHECKS) run.

AGENTS.md runs this beside smoke.sh, so a file no task happened to list cannot go red on main
unseen.  It is no part of smoke.sh.  Each file runs once, in a process of its own from the
checkout's root with no stdin, and without the caller's AGENTKIT_*/AK_* variables: a file
started from inside a run must not pass for part of it (AGENTKIT_RUN, AK_RUN_DEPTH,
AK_PARENT_RUN ...).  As many run at once as live memory fits; waiting files can outnumber
cores. Before each start it samples CPU pressure, running one file at a time while it is high,
and rereads host and cgroup headroom.
The share is cut, and its files start longest first, by each file's last measured seconds,
the record AK_TIMES holds (agentkit/suite_times.py), or one never measured by its size at the
measured files' seconds per byte.
A failing file, or one reporting no executed cases, runs once more after the pool, alone:
landing.py passes a descriptor that reads end-of-file once its other parts have ended, and
the re-run waits for that too; failing again it fails the whole and is named with its last
lines. Unittest's tally reports the count; other scripts print TESTS_RUN=<count> after their
checks. Python under agentkit/, tools/, bin/ and tests/ must parse with the grammar of Python
3.11, the oldest ak supports, as `ast.parse`'s `feature_version` applies it (f-strings it still
reads by the running interpreter's rules), and import only from the standard library or this
repository, including files smoke.sh already ran. A file failing again is also named in the
file AK_FAILED names, and one passing it in AK_FLAKY's; with AK_ONLY set only the files its
file lists run, whatever the share, smoke.sh's among them, each named in the file AK_RAN names.
The imports are a test of their own, IMPORTS, named as run and as failed like a file, in a
whole run too; AK_ONLY set, they are checked only where it lists them.

    python3 tests/every_file.py [checkout [descriptor]]
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
from agentkit import guard, host, orch, suite_times
from suite_shares import HEADERS, LIVE_CHECKS, STATIC_CHECKS, listed, name_failed, shard, shares

FILE_MEM_MB = 230   # reservation floor: the measured peak was 229 MB with children;
                    # bigger hosts fit more files, busier or smaller hosts fit fewer
CPU_PRESSURE_MAX = 20  # stall ceiling: background scheduling makes PSI positive even with
                       # idle cores; bigger hosts can still fill memory, busier ones run serially
POLL = 0.1          # ceiling on polling waits: contention stops growth at the next sample,
                    # while an idle host keeps admitting files even beyond its core count
TAIL = 30           # a failing file's last lines: unittest ends on the traceback and tally
IMPORTS = "tests/every_file.py"   # the import check's test ID


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
                    tree = ast.parse(fh.read(), filename=str(path), feature_version=(3, 11))
            except (SyntaxError, UnicodeError) as exc:
                errors.append(f"{path.relative_to(root)}: invalid Python 3.11: {exc}")
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


def smoke_runs(smoke, offline):
    """The test modules `bash tests/smoke.sh` runs in its plain mode or, `offline`, in the one
    AGENTKIT_SMOKE_OFFLINE=1 selects: every one it names outside a comment, a live check and
    the blocks that mode skips.  Both skip the argument blocks above the offline block; the
    plain mode skips the offline block, and the offline mode exits at its end.  The live checks
    (LIVE_CHECKS) run only in the live mode, AGENTKIT_SMOKE_LIVE=1, which tests/live.sh starts."""
    names, block, below, live = set(), None, False, False
    for line in smoke.splitlines():
        header = HEADERS.match(line + "\n")
        if header:
            live = header[1] in LIVE_CHECKS
        if live:
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
    # Files can run beside smoke.sh in the same checkout. Their HOME and temp files must
    # not reach another file's sandbox; their bytecode is the piece's own (`env`).
    # tmux canonicalizes TMUX_TMPDIR; a long worktree path cannot hold its socket.
    with tempfile.TemporaryDirectory(prefix="ak-test-file-", dir="/tmp") as sandbox:
        child_env = dict(env, HOME=sandbox, TMPDIR=sandbox)
        proc = subprocess.run([sys.executable, str(path.relative_to(root))], cwd=root,
                              env=child_env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode(errors="replace"), time.monotonic() - began


def pool_limit(readings):
    """A live memory bound, serial while CPU is contended.

    Reserve each active file's whole peak, even before its children allocate.
    One is the progress floor on a small, unreadable or contended host: other work can keep
    the host contended longer than the gate waits for output, and a sweep that waited it out
    would never end. Absent pressure readings keep an otherwise larger pool serial.
    """
    pressure = host._reading(readings, "cpu_pressure", "slice_cpu_pressure")
    quota = host._reading(readings, "slice_cpu_quota")
    used = host._reading(readings, "slice_cpu_used")
    if ((pressure is not None and pressure > CPU_PRESSURE_MAX)
            or (quota is not None and used is not None and used >= quota)):
        return 1
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


def costs(root, paths):
    """Each file's seconds by the record AK_TIMES holds, keyed by checkout-relative path, else
    its size at the measured files' seconds per byte."""
    times = suite_times.read(os.environ.get("AK_TIMES", ""))
    sizes = {path: path.stat().st_size for path in paths}
    measured = [path for path in paths if str(path.relative_to(root)) in times]
    rate = (sum(times[str(path.relative_to(root))] for path in measured)
            / (sum(sizes[path] for path in measured) or 1)) if measured else 1
    return {path: times.get(str(path.relative_to(root)), sizes[path] * rate) for path in paths}


def main(root, others=None):
    try:
        number, total = shard()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    only = listed()
    imports = [IMPORTS] if only is None or IMPORTS in only else []
    name_failed(imports, "AK_RAN")
    errors = import_errors(root) if imports else []
    if errors:
        for error in errors:
            print(f"FAIL  {error}", flush=True)
        name_failed(imports)
        return 1
    tests = root / "tests"
    # smoke.sh runs in the mode this caller's environment gives it; a file AK_ONLY lists runs
    # here even where smoke.sh would run it, as the list can leave smoke.sh out.
    skip = set(STATIC_CHECKS) | (smoke_runs((tests / "smoke.sh").read_text(),
                                            os.environ.get("AGENTKIT_SMOKE_OFFLINE", "0") == "1")
                                 if only is None else set())
    todo = sorted(path for path in tests.glob("test_*.py") if path.stem not in skip
                  and (only is None or str(path.relative_to(root)) in only))
    cost = costs(root, todo)
    if only is None:
        # Exclude everything smoke runs before dividing the rest, regardless of its piece.
        owners = shares(cost, total)
        todo = [path for path in todo if owners[path] == number]
    todo.sort(key=lambda path: -cost[path])
    # One bytecode cache for the piece: each file compiling all of agentkit again cost
    # about three quarters of a short file's CPU. No other piece writes or reads it. It is in
    # the checkout, where the boxes the files start see it: a box has its own /tmp.
    pycache = tempfile.TemporaryDirectory(prefix=".ak-test-pycache-", dir=root)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
    # This checkout's code and shims are under test, never the ones installed on the caller's
    # PATH: a test's own shim takes the first `git` after it for the real one.
    installed = str(guard.shim_dir())
    env["PATH"] = os.pathsep.join(part for part in env.get("PATH", "").split(os.pathsep)
                                  if part != installed)
    env["PYTHONPYCACHEPREFIX"] = pycache.name
    pending = iter(todo)
    path = next(pending, None)
    began, again, failed, flaky, jobs = time.monotonic(), [], [], [], 0
    with pycache, ThreadPoolExecutor(max(1, len(todo))) as pool:
        running = {}
        while path is not None or running:
            for done in list(running):
                if not done.done():
                    continue
                name = running.pop(done).relative_to(root)
                code, out, took = done.result()
                if code == 0 and cases_run(out) > 0:
                    print(suite_times.passed(name, took), flush=True)
                else:
                    again.append((name, out))
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
        # Under load a timing test fails by chance: the gate would run the whole piece again
        # for it, so each failed file first runs once more with no other file beside it.
        if again and others is not None:
            os.read(others, 1)  # end-of-file: what landing.py ran beside the pool has ended
        for name, out in again:
            code, rerun, took = run_file(root, root / name, env)
            if code == 0 and cases_run(rerun) > 0:
                flaky.append(str(name))
                print(suite_times.passed(name, took))
                print(f"flaky: {name} failed, then passed on its re-run")
            else:
                failed.append(name)
                out = rerun
                reason = f"exit {code}" if code else "no tests ran"
                print(f"FAIL  {name}: {reason} after {took:.0f}s, its last lines:")
            print("\n".join(f"      {line}" for line in out.splitlines()[-TAIL:]), flush=True)
    passed = f"{len(todo) - len(failed)} passed" + (f" ({len(flaky)} flaky)" if flaky else "")
    print(f"test files: {passed}, {len(failed)} failed, {jobs} at once, "
          f"{time.monotonic() - began:.0f}s")
    name_failed(failed)
    name_failed(flaky, "AK_FLAKY")
    if only is not None:
        name_failed((str(path.relative_to(root)) for path in todo), "AK_RAN")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO,
                  *map(int, sys.argv[2:3])))
