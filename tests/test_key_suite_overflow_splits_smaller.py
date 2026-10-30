"""A suite whose unit ran out of memory is cut into fewer pieces next time.

A split suite's cost per piece is the most memory its run's cgroup held while it ran, swap
included, over the pieces that ran on this host; one whose cgroup ran out of memory meanwhile
(`oom` in its memory.events) costs at least twice what it was planned at.  The next pass is
cut by that cost.

Black-box through tests/fixtures/akbin.py: two tasks run to the end, one after the other,
against gitrig.py's origin, fakegh.py's GitHub and fakeadapter.py's harnesses, and each runs
the repository's suite once, as it lands.  The kernel is the test's.  ak reads its cgroups under AK_CGROUP_ROOT,
its own named by AK_CGROUP_FILE and holding only the run's loop, and the host has 4100 MiB
free (AK_HOST_READINGS), so a suite not yet measured, planned at ak's first 410 MiB a piece,
runs in 10.  Each piece tells the test when it starts and ends, and the test moves that
cgroup's memory as a kernel does: a piece needs 600 MiB, RAM stops at the cap, what is over
it goes to swap up to the swap cap, and past both the cgroup runs out.
"""

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

MB = 1024 ** 2
BASE, NEED, UNCAPPED = 100, 600, 1 << 20    # MiB
READINGS = {"cpus": 64, "free_mb": 4100, "mem_total_mb": 16384, "slice_cpu_pressure": 0}
SUITE = """import socket, time
def say(word):
    with socket.socket(socket.AF_UNIX) as kernel:
        kernel.connect({address!r})
        kernel.sendall(word.encode())
        return kernel.recv(1)
say("start")
time.sleep(4)
while say("wait") == b"n":
    time.sleep(0.1)
say("end")
"""
# The Mac: on battery until a piece runs here, then room for two pieces, which it takes and
# passes without running them here, telling the kernel when it takes a suite's last.
SSH = """import os, shlex, socket, sys
words = shlex.split(" ".join(sys.argv[1:]))
at = words.index("mac.sh")
verb = words[at + 1]
if verb == "probe" and os.path.exists({battery!r}):
    sys.exit(251)
elif verb == "probe":
    print("cpus 4\\nload 0\\nroom_mb 65536")
elif verb == "prepare":
    sys.stdin.buffer.read()
elif verb == "run":
    shard, total = words[at + 8].split("/")
    if shard == total:
        with socket.socket(socket.AF_UNIX) as kernel:
            kernel.connect({address!r})
            kernel.sendall(b"last")
            kernel.recv(1)
"""


class Kernel:
    """One cgroup's memory as its pieces start and end; `passes` holds the pieces of each
    pass that ran on this host. Beside a helper, on `battery` until a piece runs here, a piece
    here ends once the helper took its suite's last piece (`last`), so what waits goes there."""

    def __init__(self, unit, cap, swap_cap, battery=None):
        self.unit, self.cap, self.swap_cap = unit, cap, swap_cap
        self.running, self.oom, self.passes = 0, 0, []
        self.battery, self.taken = battery, 0    # the suites whose last piece the helper took
        self.listener = socket.socket(socket.AF_UNIX)
        self.address = f"\0ak-kernel-{os.getpid()}-{id(self)}"
        self.listener.bind(self.address)
        self.listener.listen(64)
        self.held()
        self.thread = threading.Thread(target=self.serve)
        self.thread.start()

    def close(self):
        self.listener.shutdown(socket.SHUT_RDWR)    # wakes its accept, as a close does not
        self.thread.join()
        self.listener.close()

    def serve(self):
        while True:
            try:
                piece, _ = self.listener.accept()
            except OSError:
                return
            with piece:
                word = piece.recv(16)
                if word == b"start":
                    if not self.running:
                        self.passes.append(0)
                    self.passes[-1] += 1
                    self.running += 1
                    if self.battery:
                        self.battery.unlink(missing_ok=True)
                elif word == b"end":
                    self.running -= 1
                elif word == b"last":
                    self.taken += 1
                self.held()
                piece.sendall(b"n" if word == b"wait" and self.battery and
                              self.taken < len(self.passes) else b".")

    def held(self):
        need = BASE + self.running * NEED
        ram = min(need, self.cap)
        swapped = min(need - ram, self.swap_cap)
        self.oom += need > ram + swapped
        for name, value in (("memory.current", ram * MB), ("memory.swap.current", swapped * MB),
                            ("memory.events", f"max 0\noom {self.oom}\noom_kill {self.oom}"),
                            ("memory.stat", "active_file 0\ninactive_file 0")):
            (self.unit / name).write_text(f"{value}\n")


def passes(case, cap=UNCAPPED, swap_cap=0, helper=False):
    """The pieces each of a task's suite passes ran on this host."""
    home = Home()
    case.addCleanup(home.close)
    unit = home.root / "cgroups" / "acme.slice" / "run.scope"
    unit.mkdir(parents=True)
    battery = home.root / "battery"
    kernel = Kernel(unit, cap, swap_cap, battery if helper else None)
    case.addCleanup(kernel.close)
    (home.root / "cgroup").write_text("0::/acme.slice/run.scope\n")
    home.env.update(AK_CGROUP_ROOT=str(home.root / "cgroups"),
                    AK_CGROUP_FILE=str(home.root / "cgroup"), AK_HOST_READINGS=json.dumps(READINGS))
    rig = Rig(home, "widgets", files={
        "AGENTS.md": "---\ntests: python3 suite.py # AK_SHARD\n---\n# widgets\n",
        "suite.py": SUITE.format(address=kernel.address),
        "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
    GitHub(home).grant(rig.slug, "WRITE")
    if helper:
        home.fake("ssh", f"#!{sys.executable}\n"
                         f"{SSH.format(battery=str(battery), address=kernel.address)}")
        # the suite starts here on heavy suite turns, which `AK_MAX_RUNS=0` turns off
        home.env.pop("AK_MAX_RUNS")
    akconfig.write(home, ["opus", "astra"], settings={"suite_helper": "acme-mac"} if helper else None)
    claude = fakeadapter.install(home, claude="work", codex="pass")["claude"]
    for task, made in enumerate(("retry.txt", "notes.txt"), 1):
        title = f"Add {made}"
        if helper:
            battery.touch()
        # The executor's turn waits while the cgroup comes to hold its run's loop alone.
        claude.behave({"write": {made: "hello\n"}, "commit": f"add {made}", "hand_in": [["done"]],
                       "sh": f"until [ -e {claude.dir / made} ]; do sleep 0.1; done"})
        run = home.spawn("run", str(taskfile.write(home, rig.path, title,
                                                   done_when=(f"test -f {made}",))))
        deadline = time.monotonic() + 300
        while claude.n < task:
            case.assertLess(time.monotonic(), deadline, "the executor's turn never began")
            time.sleep(0.05)
        loop = next(path for path in taskfile.runs(home) if path.name.endswith(taskfile.slug(title)))
        (unit / "cgroup.procs").write_text(f"{json.loads((loop / 'run.json').read_text())['pid']}\n")
        (claude.dir / made).touch()
        case.assertEqual(run.wait(timeout=600), 0, home.log(f"spawn-{task}.err").read_text())
    return kernel.passes


class SuiteOverflowSplitsSmaller(unittest.TestCase):
    def test_a_suite_that_ran_out_of_memory_runs_in_at_most_half_the_pieces_next(self):
        # 10 pieces need 6100 MiB of 2100 RAM and 2000 swap; held, 400 a piece
        first, second = passes(self, cap=2100, swap_cap=2000)
        self.assertEqual(first, 10)
        self.assertLessEqual(second, first // 2)

    def test_swap_counts_in_the_peak(self):
        # 3100 RAM and 3000 swap held: 600 a piece, where RAM alone says 300
        self.assertEqual(passes(self, cap=3100, swap_cap=4000), [10, 6])

    def test_pieces_on_the_helper_do_not_lower_the_cost_measured_here(self):
        # Half of each suite's pieces on the Mac, which joins it once on power: 600 a piece here,
        # 300 over all of them
        self.assertEqual(passes(self, helper=True), [10, 6])

    def test_a_suite_that_fit_costs_what_it_held(self):
        self.assertEqual(passes(self), [10, 6])


if __name__ == "__main__":
    unittest.main()
