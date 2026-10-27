"""A run's unit and a lander's may swap a quarter of their memory cap, and admission lets ak's
slice hold that quarter of its own cap in swap before swap takes a run's room.

With swap as large as the cap, a lander and several runs sat at both caps for hours, paging
their test pieces, until the host's load reached 290 (24 Oct 2026); with no swap allowed at
all, idle seats' cold pages kept runs out of a calm slice overnight (25 Oct 2026).  Seats
already swapped a quarter of their cap, and a runaway fills far more than that.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py with fakegh.py's GitHub and scripted harnesses from fakeadapter.py.  A
socket where a user manager listens makes the program place its work with `systemd-run`, which
records each argv and refuses, so the work starts plainly.  Admission reads a fake cgroup tree
(AK_CGROUP_ROOT, AK_CGROUP_FILE); AK_MIN_FREE_MB=0 keeps this machine's own free memory out.
"""

import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

MB = 1024 ** 2
SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
CALM = "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"


def wait(test, what, bound=240):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


def state(run):
    try:
        return json.loads((run / "run.json").read_text())
    except (OSError, ValueError):
        return {}


def launch(home, rig, title, *flags):
    """The run directory of `ak run <task> --bg` for a new task titled `title`."""
    known = set(taskfile.runs(home))
    done = home.ak("run", str(taskfile.write(home, rig.path, title)), "--bg", *flags)
    assert done.code == 0, done.out + done.err
    return (set(taskfile.runs(home)) - known).pop()


class Manager:
    """The control socket a running `systemd --user` listens on, answering nothing."""

    def __init__(self, home):
        path = Path(home.env["XDG_RUNTIME_DIR"]) / "systemd" / "private"
        path.parent.mkdir()
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(str(path))
        self.listener.listen(64)
        self.thread = threading.Thread(target=self.serve)
        self.thread.start()

    def serve(self):
        while True:
            try:
                peer, _ = self.listener.accept()
            except OSError:
                return
            peer.close()

    def close(self):
        self.listener.shutdown(socket.SHUT_RDWR)    # wakes its accept, as a close does not
        self.thread.join()
        self.listener.close()


class Slice:
    """ak's slice in a fake cgroup tree: 4 GB high, 2 GB of RAM held, idle CPU at 8 cores."""

    def __init__(self, home):
        root = home.root / "cgroup"
        self.dir = root / SERVICE / "agentkit.slice" / "agentkit-test.slice"
        runs = self.dir / "agentkit-test-runs.slice"
        runs.mkdir(parents=True)
        membership = home.root / "membership"
        membership.write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
        home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership))
        (runs / "cpu.max").write_text("800000 100000\n")
        for directory in (self.dir, runs):
            (directory / "cpu.pressure").write_text(CALM)
            (directory / "cpu.stat").write_text("usage_usec 0\n")
        (self.dir / "memory.pressure").write_text(CALM)
        (self.dir / "memory.high").write_text(str(4096 * MB))
        (self.dir / "memory.current").write_text(str(2048 * MB))
        (self.dir / "memory.stat").write_text("active_file 0\ninactive_file 0\n")

    def swaps(self, mb):
        (self.dir / "memory.swap.current").write_text(str(mb * MB))


class RunSwapShare(unittest.TestCase):
    def test_a_runs_unit_and_its_landers_swap_a_quarter_of_their_memory_cap(self):
        with Home() as home:
            manager = Manager(home)
            self.addCleanup(manager.close)
            home.fake("busctl", "#!/bin/sh\nexit 1\n")     # nor does the manager move a process
            # a suite to land with: only a lander runs it
            rig = Rig(home, "widgets", files={"AGENTS.md": "---\ntests: true\n---\n# widgets\n"})
            GitHub(home).grant(rig.slug, "WRITE")
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude="work", codex="pass")
            run = launch(home, rig, "Add retry file")
            wait(lambda: state(run).get("merged"), "the run merged")
            limits = {}
            for argv in home.calls("systemd-run"):
                unit = next(word.split("=", 1)[1].split("-")[1] for word in argv
                            if word.startswith("--unit="))
                limits[unit] = {key: int(value.removesuffix("M")) for key, _, value in
                                (word.partition("=") for word in argv)
                                if key in ("MemoryMax", "MemorySwapMax")}
            self.assertEqual(sorted(limits), ["lander", "run"], home.calls("systemd-run"))
            for unit, memory in limits.items():
                with self.subTest(unit):
                    self.assertGreater(memory["MemoryMax"], 0)
                    self.assertEqual(memory["MemorySwapMax"], memory["MemoryMax"] // 4)

    def test_a_slice_admits_a_run_within_a_quarter_of_its_cap_in_swap_and_holds_one_past_it(self):
        with Home() as home:
            del home.env["AK_MAX_RUNS"]
            home.env.update(AK_SLOT_POLL="0.5", AK_MIN_FREE_MB="0")
            slice_ = Slice(home)
            rig = Rig(home, "widgets")
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude="work", codex="pass")
            # 2 of 4 G of RAM held, so 2 G of room: 0.75 G in swap is within the quarter.
            slice_.swaps(768)
            run = launch(home, rig, "Add retry file", "--no-merge", "--anyway")
            wait(lambda: state(run).get("state") not in ("queued", "running"),
                 "the run admitted beside swap within the allowance, and its end")
            self.assertEqual(state(run).get("verdict"), "PASS")
            # 3 G in swap is 2 G past the quarter: that fills the room the RAM left.
            slice_.swaps(3072)
            run = launch(home, rig, "Bump alpha notes", "--no-merge", "--anyway")
            wait(lambda: state(run).get("slot_wait_kind") == "unit memory",
                 "the run queued on memory")
            time.sleep(2)     # four polls: still held
            held = state(run)
            self.assertEqual(held.get("state"), "queued")
            self.assertIn("waiting for the unit's memory", held.get("slot_wait_reason", ""))
            self.assertIn("3 G in swap", held.get("slot_wait_reason", ""))
            slice_.swaps(1024)
            wait(lambda: state(run).get("state") not in ("queued", "running"),
                 "the run admitted once its slice's swap is back within the allowance")
            self.assertEqual(state(run).get("verdict"), "PASS")


if __name__ == "__main__":
    unittest.main()
