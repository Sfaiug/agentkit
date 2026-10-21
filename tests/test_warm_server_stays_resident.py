"""A warm server keeps its memory in RAM (`agentkit/warm.py`, `_resident`).

A server idle for hours is what a busy host swaps out first, and a menu forked from it read that
memory back page by page before its first frame, most of a second.  Here a server pushes memory of
its own out to swap before it serves (`MADV_PAGEOUT`, which takes no privilege) and has it back
within a few of its wakes.  A HOME of its own, a tmux with no server up and an invented socket, as
`test_warm_menu.py` has them; the server is stopped by taking its socket away.
"""

import subprocess
import sys
import time
import unittest

from test_warm_menu import REPO, Home

SIZE = 8 << 20
SERVER = f"""
import fcntl, mmap, os, sys
sys.path[0] = {str(REPO)!r}
from agentkit import warm
held = mmap.mmap(-1, {SIZE}, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
held.write(os.urandom({SIZE}))
held.madvise(21)                  # MADV_PAGEOUT: out to swap, as a busy host does an idle server
print(next(line.split()[1] for line in open("/proc/self/status") if line.startswith("VmSwap:")),
      flush=True)
state, base = warm.place({str(REPO)!r})
lock = os.open(os.path.join(state, base + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
warm.serve(lock)
"""


def swapped(pid):
    """The process's memory in swap, in kB."""
    with open(f"/proc/{pid}/status") as status:
        return int(next(line.split()[1] for line in status if line.startswith("VmSwap:")))


class StaysResident(unittest.TestCase):
    def test_a_server_has_what_was_swapped_out_back_in_ram(self):
        home = Home(self)
        server = subprocess.Popen([sys.executable, "-c", SERVER], env=home.env,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, start_new_session=True, text=True)
        home.started.append(server)
        out = int(server.stdout.readline() or 0)
        if out < SIZE >> 10:
            self.skipTest(f"this host swapped out {out} kB of {SIZE >> 10}: no swap to test with")
        home.up()
        deadline = time.monotonic() + 60
        while swapped(server.pid) >= SIZE >> 10:
            self.assertLess(time.monotonic(), deadline,
                            f"{swapped(server.pid)} kB of the server still in swap")
            time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
