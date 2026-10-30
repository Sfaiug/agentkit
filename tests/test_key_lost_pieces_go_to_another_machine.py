"""Pieces a machine lost go to another machine with room before they wait for a turn here.

Black-box through tests/fixtures/akbin.py, as test_key_waiting_suite_goes_to_the_mac.py: one task
runs to the end, and its repository's suite runs as it lands, while the test holds this host's
one turn throughout.  A fake ssh is two machines: `acme-a` has room until `acme-b` has, then is
taken back, its probe unanswered and every piece it runs lost (`helper.LOST`); `acme-b` runs a
piece and passes it.  A piece run here sends the test its share.
"""

import fcntl
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

READINGS = {"cpus": 64, "free_mb": 400, "slice_cpu_pressure": 0}
SUITE = """import os, socket
socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM).sendto(os.environ["AK_SHARD"].encode(), {here!r})
"""
SSH = """import os, shlex, sys, time
alias, words = sys.argv[-2], shlex.split(sys.argv[-1])
if "mac.sh" not in words:
    sys.exit(255)
verb, *args = words[words.index("mac.sh") + 1:]
room, other = os.path.exists({room!r}), alias == "acme-b"
if verb == "run" and args[6] == "1/1":    # a round's own checks, where they go there: not the suite
    sys.exit()
with open({calls!r}, "a") as calls:
    calls.write(f"{{alias}} {{verb}} {{args[6] if verb == 'run' else '-'}}\\n")
if verb == "probe":
    if room and not other:
        sys.exit(255)
    print("cpus 4\\nload 0\\nroom_mb 65536" if room or not other else "cpus 4\\nload 4\\nroom_mb 0")
elif verb == "prepare":
    sys.stdin.buffer.read()
elif verb == "run" and not other:
    while not os.path.exists({room!r}):
        time.sleep(0.2)
    sys.exit(255)
"""


class LostPiecesGoToAnotherMachine(unittest.TestCase):
    def test_pieces_the_first_machine_lost_run_on_the_second_and_none_here(self):
        home = Home()
        self.addCleanup(home.close)
        calls, room = home.root / "calls", home.root / "room"
        here = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.addCleanup(here.close)
        here.bind(address := f"\0ak-shares-{os.getpid()}-{id(home)}")
        # runs start below ak's free-memory floor, as only the suite's room is under test
        home.env.update(AK_HOST_READINGS=json.dumps(READINGS), AK_MIN_FREE_MB="0")
        # heavy suite turns, which `AK_MAX_RUNS=0` turns off
        home.env.pop("AK_MAX_RUNS")
        home.fake("ssh", f"#!{sys.executable}\n" + SSH.format(calls=str(calls), room=str(room)))
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\ntests: python3 suite.py # AK_SHARD\n---\n# widgets\n",
            "suite.py": SUITE.format(here=address),
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], extra="[machines.acme-a]\n[machines.acme-b]")
        fakeadapter.install(home, claude="work", codex="pass")["claude"].behave(
            {"write": {"retry.txt": "hello\n"}, "commit": "add retry.txt", "hand_in": [["done"]]})
        (runs := home.path / ".agentkit" / "runs").mkdir(parents=True)
        with (runs / ".heavy-0.lock").open("a") as turn:
            fcntl.flock(turn, fcntl.LOCK_EX)
            run = home.spawn("run", str(taskfile.write(home, rig.path, "Add retry file")))
            deadline = time.monotonic() + 300
            while "acme-a run" not in (calls.read_text() if calls.exists() else ""):
                self.assertIsNone(run.poll(), home.log("spawn-1.err").read_text())
                self.assertLess(time.monotonic(), deadline, "acme-a never ran a piece")
                time.sleep(0.2)
            room.touch()
            self.assertEqual(run.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
        here.setblocking(False)
        self.assertRaises(BlockingIOError, here.recv, 64)    # no piece ran here
        lines = [line.split() for line in calls.read_text().splitlines()]
        ran = {alias: sorted(shard for name, verb, shard in lines if (name, verb) == (alias, "run"))
               for alias in ("acme-a", "acme-b")}
        count = int(ran["acme-a"][0].split("/")[1])
        self.assertEqual(ran["acme-b"], sorted(f"{k}/{count}" for k in range(1, count + 1)))


if __name__ == "__main__":
    unittest.main()
