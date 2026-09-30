#!/usr/bin/env python3
"""The rest of the `tests:` suite: every tests/test_*.py a plain smoke.sh run does not run.

AGENTS.md runs this after smoke.sh, so a file no task happened to list cannot go red on main
unseen.  It is no part of smoke.sh and never touches its lock: it holds no smoke target and
waits for none.  Each file runs once, in a process of its own from the checkout's root with
no stdin, and without the caller's AGENTKIT_*/AK_* variables: a file started from inside a run
must not pass for part of it (AGENTKIT_RUN, AK_RUN_DEPTH, AK_PARENT_RUN ...).  As many run at
once as the host's live headroom fits, read the way the loop reads it for heavy suites.  A
failing file fails the whole and is named with its last lines.

    python3 tests/every_file.py [checkout]
"""

import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run

FILE_CPUS = 1.0     # one test file's measured cost: one Python process busy on one core,
FILE_MEM_MB = 410   # and its peak memory with what it starts
TAIL = 30           # a failing file's last lines: unittest ends on the traceback and tally


def smoke_runs(smoke):
    """The test modules a plain `bash tests/smoke.sh` runs: every one it names outside a
    comment and outside its AGENTKIT_SMOKE_OFFLINE block, which that run never enters."""
    names, offline = set(), False
    for line in smoke.splitlines():
        if line.startswith("if ") and "AGENTKIT_SMOKE_OFFLINE" in line:
            offline = True
        elif line == "fi":
            offline = False
        elif not offline and not line.lstrip().startswith("#"):
            names.update(re.findall(r"\btest_\w+", line))
    return names


def run_file(root, path, env):
    began = time.monotonic()
    proc = subprocess.run([sys.executable, str(path.relative_to(root))], cwd=root, env=env,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode(errors="replace"), time.monotonic() - began


def main(root):
    tests = root / "tests"
    skip = smoke_runs((tests / "smoke.sh").read_text())
    todo = sorted(path for path in tests.glob("test_*.py") if path.stem not in skip)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
    jobs = run.derived_heavy_limit(job_cpus=FILE_CPUS, job_mem_mb=FILE_MEM_MB)
    began, failed = time.monotonic(), 0
    with ThreadPoolExecutor(jobs) as pool:
        running = {pool.submit(run_file, root, path, env): path for path in todo}
        for done in as_completed(running):
            name = running[done].relative_to(root)
            code, out, took = done.result()
            if code == 0:
                print(f"PASS  {name} ({took:.0f}s)", flush=True)
                continue
            failed += 1
            print(f"FAIL  {name}: exit {code} after {took:.0f}s, its last lines:")
            print("\n".join(f"      {line}" for line in out.splitlines()[-TAIL:]), flush=True)
    print(f"test files: {len(todo) - failed} passed, {failed} failed, {jobs} at once, "
          f"{time.monotonic() - began:.0f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO))
