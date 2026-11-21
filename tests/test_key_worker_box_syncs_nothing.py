"""Inside an `ak worker` turn's box a sync to disk returns at once, the kernel never asked.

Nothing a box writes has to survive a crash of the machine, and every sync asked there makes the
host's filesystem commit its journal, holding up every writer on the host.  PROBE syncs FD by
`os.fsync` and `os.fdatasync`.  The test runs ak under REFUSED, a filter that answers those two
calls on FD with EINVAL.  Of filters answering a call by errno, the newest one's answer counts,
so PROBE exits 0 only where a filter ak loads answered both: one of a box the test itself runs
in is older.  ak answers those calls on the machines of fixtures/kernel.py alone;
elsewhere the class skips.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, with a scripted harness from fakeadapter.py whose `sh` step runs PROBE
inside the turn; the class skips where bubblewrap cannot box one.
"""

import errno
import os
import shlex
import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home, boxable
from fixtures.kernel import SYNCS

# Standard input: no descriptor limit takes it away, and a filter answers before the kernel
# reads it, so PROBE need not open it.  Where it is a pipe, a terminal or /dev/null, as a
# process's own stdin is, the kernel refuses to sync it as REFUSED does.
FD = 0
PROBE = f"import os; os.fsync({FD}); os.fdatasync({FD})"
MACHINE = os.uname().machine


def refused(arch, calls):
    """Classic BPF over seccomp_data, as bwrap's `--seccomp` takes it: the call number is at 0,
    the architecture at 4, and the descriptor in the low word of the first argument, at 16 or,
    on a big-endian machine, 20.  fsync and fdatasync of FD get EINVAL; every other call passes."""
    load, equal, ret = 0x20, 0x15, 0x06     # BPF_LD|BPF_W|BPF_ABS, BPF_JMP|BPF_JEQ|BPF_K, BPF_RET
    steps = [(load, 0, 0, 4), (equal, 0, 6, arch), (load, 0, 0, 0), (equal, 1, 0, calls[0]),
             (equal, 0, 3, calls[1]), (load, 0, 0, 16 + 4 * (sys.byteorder == "big")),
             (equal, 0, 1, FD), (ret, 0, 0, 0x00050000 | errno.EINVAL), (ret, 0, 0, 0x7FFF0000)]
    return b"".join(struct.pack("=HBBI", *step) for step in steps)


REFUSED = refused(*SYNCS[MACHINE]) if MACHINE in SYNCS else None


@unittest.skipUnless(REFUSED, f"ak answers syncs inside a box on none of {MACHINE}")
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
        read, write = os.pipe()
        self.addCleanup(os.close, read)
        with open(write, "wb") as pipe:
            pipe.write(REFUSED)
        done = home.run("bwrap", "--dev-bind", "/", "/", "--seccomp", str(read), "--",
                        home.program, "worker", "beta",
                        str(home.write("fix-api.md", "Fix the parser.\n")),
                        "--workspace", str(ws), "--out", str(home.path / "out"), keep=(read,))
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual((status.read_text(), said.read_text()), ("0\n", ""))


if __name__ == "__main__":
    unittest.main()
