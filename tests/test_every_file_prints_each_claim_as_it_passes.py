"""tests/every_file.py prints the line of each claim of the Go keys check as the claim passes,
while the rest of its run goes on, and each once, with its own seconds, as the gate keeps them: a
run of many claims is silent only while one runs.

Offline: the real every_file.py runs a checkout of two stand-in keys measured short enough to
share one run, with a stand-in `go`; the second waits on a FIFO the test writes to only once it
has read the first one's line.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]
import every_file
from agentkit import suite_times
from test_go_keys import SWITCHED

CHECK, CLAIMS = "tests/test_go_keys.py", ("test_key_acme", "test_key_widget")
IDS = [f"{CHECK}::{key}" for key in CLAIMS]
# The second claim waits to read a byte from the FIFO ACME_GATE names.
KEY = '''import os, unittest
class Acme(unittest.TestCase):
    def test_it(self):
        if os.path.basename(__file__) == "test_key_widget.py":
            open(os.environ["ACME_GATE"]).read(1)
unittest.main()
'''
# test_go_keys.py builds in test_go.py's environment; the stand-in `go` writes where `-o` says.
TEST_GO = "import os\nENV = dict(os.environ)\n"
GO = '#!/bin/sh\nmkdir -p "$(dirname "$3")" && echo built >"$3"\n'
# Only bounds a run that never prints the first line, as every_file.py did before: it then fails.
DEADLINE = 300


class EveryFilePrintsEachClaimAsItPasses(unittest.TestCase):
    def test_the_first_claims_line_prints_while_the_second_runs(self):
        sandbox = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-each-claim-", dir=REPO)))
        root = sandbox / "acme"
        (root / "tests").mkdir(parents=True)
        # what the copy switched as each claim's is takes from go/
        for part in SWITCHED:
            shutil.copytree(REPO / "go" / part, root / "go" / part, symlinks=True)
        shutil.copy(REPO / "go/install.sh", root / "go")
        shutil.copy(REPO / CHECK, root / "tests")
        for name in ("suite_shares.py", "test_go_builds.py"):
            shutil.copy(REPO / "tests" / name, root / "tests")
        (root / "tests/test_go.py").write_text(TEST_GO)
        (root / "go/keys.txt").write_text("".join(f"{key} Acme\n" for key in CLAIMS))
        for key in CLAIMS:
            (root / "tests" / f"{key}.py").write_text(KEY)
        (sandbox / "go").write_text(GO)
        (sandbox / "go").chmod(0o755)
        (sandbox / "only").write_text(f"{CHECK}\n")
        (sandbox / "times").write_text(json.dumps(dict.fromkeys(IDS, 1)))
        os.mkfifo(sandbox / "gate")
        # Held open for reading and writing, the FIFO keeps what the test writes until the second
        # claim reads it, whenever that claim opens it: it goes by that, never by timing.
        gate = os.open(sandbox / "gate", os.O_RDWR)
        self.addCleanup(os.close, gate)
        kept = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        proc = self.enterContext(subprocess.Popen(
            [sys.executable, REPO / "tests/every_file.py", root],
            env=dict(kept, PATH=f"{sandbox}{os.pathsep}{os.environ['PATH']}",
                     ACME_GATE=str(sandbox / "gate"), AK_ONLY=str(sandbox / "only"),
                     AK_TIMES=str(sandbox / "times"), AK_CGROUP_FILE=str(sandbox / "no-cgroup"),
                     AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}'),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
        lines, first = [], threading.Event()

        def read():
            for line in proc.stdout:
                lines.append(line)
                if (found := suite_times.PASSED.match(line)) and found[1] == IDS[0]:
                    first.set()

        reader = threading.Thread(target=read)
        reader.start()
        printed = first.wait(DEADLINE)
        os.write(gate, b"\n")
        reader.join()
        out = "".join(lines)
        self.assertEqual(proc.wait(), 0, out)
        self.assertTrue(printed, f"the first claim's line waited for the second claim:\n{out}")
        # In one run: in two, the first's line would print as its own run ended.
        self.assertIn(f"{every_file.pass_line(CHECK, CLAIMS, 0)}\n", lines)
        self.assertEqual([found[1] for line in lines if (found := suite_times.PASSED.match(line))],
                         IDS)
        (sandbox / "out").write_text(out)
        self.assertEqual(suite_times.measured(sandbox / "out").keys(), set(IDS))


if __name__ == "__main__":
    unittest.main()
