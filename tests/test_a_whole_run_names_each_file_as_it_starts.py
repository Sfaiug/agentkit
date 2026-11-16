"""tests/every_file.py's whole run names each test file in the file AK_RAN names as it starts it:
while a file that never ends runs, AK_RAN holds it and each file started before it, and not one
that comes after it, so a piece silence stops is red in just that file (gate.unfinished).

Offline: the real every_file.py runs a checkout of stand-ins as one piece of two, its files
ordered by measured seconds; the one that hangs waits on a FIFO the test writes to only once it
has read what AK_RAN holds.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]
import every_file
from agentkit import gate

ACME, WIDGET, HANGS, BILLING, INVOICE = (f"tests/test_{name}.py" for name in (
    "acme", "widget", "fix_api", "billing", "invoice"))
# Cut longest first: INVOICE alone in piece 1, the others in piece 2, which runs them in this order.
SECONDS = {INVOICE: 100, ACME: 40, WIDGET: 30, HANGS: 20, BILLING: 10}
PASSES = 'print("TESTS_RUN=1")\n'
# Says it started, then waits to read a byte from the FIFO ACME_GATE names.
WAITS = '''import os, pathlib
pathlib.Path(os.environ["ACME_STARTED"]).touch()
open(os.environ["ACME_GATE"]).read(1)
print("TESTS_RUN=1")
'''


class AWholeRunNamesEachFileAsItStarts(unittest.TestCase):
    def test_a_file_that_hangs_is_named_with_those_before_it_and_none_after(self):
        sandbox = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-names-as-it-starts-", dir=REPO)))
        root = sandbox / "acme"
        (root / "tests").mkdir(parents=True)
        (root / "tests/smoke.sh").write_text("")
        for name in SECONDS:
            (root / name).write_text(WAITS if name == HANGS else PASSES)
        (sandbox / "times").write_text(json.dumps(SECONDS))
        ran, out, started = sandbox / "ran", sandbox / "out", sandbox / "started"
        os.mkfifo(sandbox / "gate")
        # Held open for reading and writing, the FIFO keeps what the test writes until the file
        # that hangs reads it.
        release = os.open(sandbox / "gate", os.O_RDWR)
        self.addCleanup(os.close, release)
        kept = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        with out.open("w") as output:
            proc = self.enterContext(subprocess.Popen(
                [sys.executable, REPO / "tests/every_file.py", root],
                env=dict(kept, HOME=str(sandbox), ACME_GATE=str(sandbox / "gate"),
                         ACME_STARTED=str(started), AK_SHARD="2/2", AK_RAN=str(ran),
                         AK_TIMES=str(sandbox / "times")),
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT))
        # The file that hangs ends once the test is done with it, failing or not.
        self.addCleanup(os.write, release, b"\n")
        while not started.exists():
            self.assertIsNone(proc.poll(), out.read_text())
            time.sleep(0.05)
        held = ran.read_text().splitlines() if ran.exists() else []
        self.assertEqual(held, [every_file.IMPORTS, ACME, WIDGET, HANGS], out.read_text())
        self.assertEqual(gate.unfinished(held, out, []), [HANGS], out.read_text())
        os.write(release, b"\n")
        self.assertEqual(proc.wait(), 0, out.read_text())
        self.assertEqual(ran.read_text().splitlines(),
                         [every_file.IMPORTS, ACME, WIDGET, HANGS, BILLING])


if __name__ == "__main__":
    unittest.main()
