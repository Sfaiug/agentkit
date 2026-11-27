"""A live check started with AK_LIVE_NO_MODEL_CALLS=1 makes no model call.

tests/live.sh so started runs every live check but those tests/suite_shares.py's MODEL_CALLS
names, with the shared setup, and leaves those out: the acceptance line counts none for them, so
the gate passes under AGENTKIT_ACCEPTANCE_REQUIRED=1.  Without the variable it chooses every
live check, as before.  Offline: smoke.sh's blocks are read, and the entry runs on a stand-in
suite with a passing fixture per real check, in a temporary checkout.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import suite_shares as suite

SMOKE = (REPO / "tests/smoke.sh").read_text()
BLOCKS = suite.smoke_blocks(SMOKE)
NAMED = {name for name, _ in BLOCKS if name is not None}
# a shell variable a block assigns (`RUNDIR=`, `local spent=`), or a function it defines
MADE = re.compile(r"(?:^|[\s;(])(\w+)(=|\(\)\s*\{)", re.MULTILINE)


def code(body):
    return re.sub(r"(?m)^\s*#.*", "", body)    # a comment is prose


def made(bodies):
    """The variables and the functions the blocks `bodies` make."""
    found = [MADE.findall(code(body)) for body in bodies]
    return ({name for one in found for name, how in one if how == "="},
            {name for one in found for name, how in one if how != "="})


class LiveCheckWithoutModelCalls(unittest.TestCase):
    def test_every_check_left_out_is_a_live_check(self):
        self.assertLessEqual(suite.MODEL_CALLS, suite.LIVE_CHECKS)

    def test_what_runs_probes_no_provider_meters(self):
        # A usage read queries provider meters, and some harnesses read their meter with a turn,
        # so no check kept under AK_LIVE_NO_MODEL_CALLS=1 may call `ak usage` or probe meters.
        for name, body in BLOCKS:
            if name in suite.LIVE_CHECKS - suite.MODEL_CALLS:
                lines = code(body)
                self.assertNotIn("ak usage", lines, name)
                self.assertNotIn("_probe_gently", lines, name)

    def test_what_runs_reads_nothing_a_check_left_out_makes(self):
        # A group (DEPENDENCIES) may hold a check left out beside those that run: these read no
        # variable or function only one left out makes, which under smoke.sh's `set -u` would end
        # the run or decide a check on nothing.
        theirs = made(body for name, body in BLOCKS if name in suite.MODEL_CALLS)
        ours = made(body for name, body in BLOCKS
                    if name is None or name in suite.LIVE_CHECKS - suite.MODEL_CALLS)
        variables, functions = theirs[0] - ours[0], theirs[1] - ours[1]
        for name, body in BLOCKS:
            if name in suite.LIVE_CHECKS - suite.MODEL_CALLS:
                reads = (set(re.findall(r"\$\{?(\w+)", code(body))) & variables
                         | set(re.findall(r"\w+", code(body))) & functions)
                self.assertEqual(reads, set(), name)

    def test_the_live_entry_leaves_out_the_model_calls_and_passes(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-live-no-calls-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tests").mkdir()
        for name in ("live.sh", "suite_shares.py", "acceptance.sh"):
            (root / "tests" / name).write_text((REPO / "tests" / name).read_text())
        # the real entry and setup with the real accounting, a passing fixture per real check that
        # says it ran, and the real verdict
        stub = SMOKE[:SMOKE.index('export PATH="$REPO/bin:$PATH"')]
        stub += 'WORK="$HOME/work"; mkdir -p "$WORK"; . "$REPO/tests/acceptance.sh"\n'
        stub += "".join(f"# --- {name}: fixture\necho 'ran {name}'; ok '{name} fixture'\n"
                        for name in sorted(NAMED))
        stub += "# --- shared result ---\nfinish\n"
        (root / "tests/smoke.sh").write_text(stub)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AK_", "AGENTKIT_"))}
        # a host where `timeout -k 5 20 docker info` exits 0, whose live run holds check 52
        (root / "timeout").write_text("#!/bin/sh\n")
        (root / "timeout").chmod(0o755)
        env.update(HOME=str(root), PATH=f"{root}:{env['PATH']}", AGENTKIT_ACCEPTANCE_REQUIRED="1")
        ran = {}
        for asked in ({"AK_LIVE_NO_MODEL_CALLS": "1"}, {}):
            proc = subprocess.run(["bash", "tests/live.sh"], cwd=root, env={**env, **asked},
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=60)
            # exit 0 under AGENTKIT_ACCEPTANCE_REQUIRED=1: nothing failed, and no skip counted
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            ran[bool(asked)] = {line.removeprefix("ran ") for line in proc.stdout.splitlines()
                                if line.startswith("ran ")}
        self.assertEqual(ran[True], suite.LIVE_CHECKS - suite.MODEL_CALLS)
        # the usage check reads every provider's meter, and Muse's costs a request to its model
        self.assertNotIn("1", ran[True])
        # each group it runs a part of, it runs whole but for MODEL_CALLS
        for group in suite.DEPENDENCIES:
            if ran[True] & set(group):
                self.assertLessEqual(set(group) - suite.MODEL_CALLS, ran[True], group)
        self.assertEqual(ran[False], suite.LIVE_CHECKS)


if __name__ == "__main__":
    unittest.main()
