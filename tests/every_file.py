#!/usr/bin/env python3
"""The rest of the `tests:` suite: every tests/test_*.py the smoke.sh run before it did not.

AGENTS.md runs this after smoke.sh, so a file no task happened to list cannot go red on main
unseen.  It is no part of smoke.sh and never touches its lock: it holds no smoke target and
waits for none.  Each file runs once, in a process of its own from the checkout's root with
no stdin, and without the caller's AGENTKIT_*/AK_* variables: a file started from inside a run
must not pass for part of it (AGENTKIT_RUN, AK_RUN_DEPTH, AK_PARENT_RUN ...).  As many run at
once as the host's idle cores and free memory fit, read as the loop reads them for heavy suites;
in a run holding its merge turn, at least the cores its raised CPU weight entitles it to.
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
import time
import tokenize
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gate, host, orch

FILE_CPUS = 1.0     # one test file's cost: one Python process, one core busy at most,
FILE_MEM_MB = 230   # and the largest file's measured peak with what it starts, 229 MB
TAIL = 30           # a failing file's last lines: unittest ends on the traceback and tally


def import_errors(root):
    local = set()
    for path in root.rglob("*.py"):
        local.add(path.stem)
        local.update(path.relative_to(root).parts[:-1])
    allowed = sys.stdlib_module_names | local
    errors = []
    for folder in ("agentkit", "tools", "bin", "tests"):
        for path in sorted((root / folder).rglob("*")):
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
    proc = subprocess.run([sys.executable, str(path.relative_to(root))], cwd=root, env=env,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode(errors="replace"), time.monotonic() - began


def main(root):
    errors = import_errors(root)
    if errors:
        for error in errors:
            print(f"FAIL  {error}", flush=True)
        return 1
    tests = root / "tests"
    # smoke.sh ran in the mode this caller's environment gave it
    skip = smoke_runs((tests / "smoke.sh").read_text(),
                      os.environ.get("AGENTKIT_SMOKE_OFFLINE", "0") == "1",
                      os.environ.get("AGENTKIT_SMOKE_LIVE", "0") == "1")
    todo = sorted(path for path in tests.glob("test_*.py") if path.stem not in skip)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
    # The host's idle cores -- the slice's CPU quota where it sets one, less the minute's load
    # average -- and its free memory.  Not a tenth of a second's CPU reading, which would hold
    # a sweep of minutes to that moment; and no more than are idle, since a timing test on an
    # oversubscribed host fails by chance.  The heavy suites running already, this one among
    # them, are in that load: none is a file to add on top.
    readings = host.host_readings(slice_dir=orch.slice_cgroup)
    cores = readings.get("slice_cpu_quota") or readings.get("cpus")
    readings = dict(readings, slice_cpu_quota=None, cpus=cores)
    # A run holding its merge turn weighs its scope above every other run's: the kernel owes
    # this suite that share of the cores however busy the others keep them, so it counts no
    # fewer idle.  Its share, not more: the others' weights, another repository's holder's
    # among them, still claim the rest.
    own = host.process_cgroup()
    weights = host.cpu_weights(host.cgroup_path(own)) if own else None
    load = host._reading(readings, "load", "load1", "load_1m")
    if weights and weights[1] and weights[0] > min(weights[1]) and cores and load is not None:
        entitled = cores * weights[0] / (weights[0] + sum(weights[1]))
        readings["load"] = min(load, cores - entitled)
    jobs = gate.derived_heavy_limit(readings, running=0, job_cpus=FILE_CPUS,
                                   job_mem_mb=FILE_MEM_MB)
    began, failed = time.monotonic(), 0
    with ThreadPoolExecutor(jobs) as pool:
        running = {pool.submit(run_file, root, path, env): path for path in todo}
        for done in as_completed(running):
            name = running[done].relative_to(root)
            code, out, took = done.result()
            if code == 0 and cases_run(out) > 0:
                print(f"PASS  {name} ({took:.0f}s)", flush=True)
                continue
            failed += 1
            reason = f"exit {code}" if code else "no tests ran"
            print(f"FAIL  {name}: {reason} after {took:.0f}s, its last lines:")
            print("\n".join(f"      {line}" for line in out.splitlines()[-TAIL:]), flush=True)
    print(f"test files: {len(todo) - failed} passed, {failed} failed, {jobs} at once, "
          f"{time.monotonic() - began:.0f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO))
