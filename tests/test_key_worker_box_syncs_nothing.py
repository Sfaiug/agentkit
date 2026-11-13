"""Inside an `ak worker` turn's box a sync to disk returns at once, the kernel never asked.

Nothing a box writes has to survive a crash of the machine, and every sync asked there makes the
host's filesystem commit its journal, holding up every writer on the host.  The kernel refuses
to sync a pipe, so a command syncing one's writing end, by `os.fsync` and `os.fdatasync`, and
then everything by `os.sync()`, exits 0 only where no call reached it.  ak answers those calls
on arm64 and x86-64 alone; elsewhere the class skips.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, with a scripted harness from fakeadapter.py whose
`sh` step runs PROBE inside the turn; the class skips where bubblewrap cannot box one.
"""

import os
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home, boxable

PROBE = "import os; read, write = os.pipe(); os.fsync(write); os.fdatasync(write); os.sync()"
MACHINE = os.uname().machine


@unittest.skipUnless(MACHINE in ("aarch64", "x86_64"),
                     f"ak answers syncs inside a box on arm64 and x86-64, not on {MACHINE}")
@unittest.skipUnless(boxable(), "no bwrap able to box a turn here")
class WorkerBoxSyncsNothing(unittest.TestCase):
    def test_a_sync_the_kernel_would_refuse_returns_inside_the_box(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {"beta": {"harness": "acme", "model": "beta-1", "effort": "low"}})
        fake = fakeadapter.install(home, acme="pass")["acme"]
        ws = home.path / "code" / "widgets"
        ws.mkdir(parents=True)
        said, status = fake.dir / "said", fake.dir / "status"
        fake.behave({**fakeadapter.PASS, "sh": (
            f"{shlex.join([sys.executable, '-I', '-c', PROBE])} 2>{shlex.quote(str(said))}; "
            f"echo $? >{shlex.quote(str(status))}")})
        done = home.ak("worker", "beta", str(home.write("fix-api.md", "Fix the parser.\n")),
                       "--workspace", str(ws), "--out", str(home.path / "out"))
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual((status.read_text(), said.read_text()), ("0\n", ""))


if __name__ == "__main__":
    unittest.main()
