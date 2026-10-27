"""A sharded suite waiting for this host's turns goes to the suite helper once it has room.

Black-box through tests/fixtures/akbin.py: one task runs to the end against gitrig.py's origin,
fakegh.py's GitHub and fakeadapter.py's harnesses, and its repository's suite runs as it lands.
The host's free memory fits no piece beside the turn the test holds (AK_HOST_READINGS), so the
suite waits for that turn.  The Mac is a fake ssh that answers `no room` until the test gives
it room; a piece it runs passes there, and one run here sends the test its share.
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
SSH = """import os, shlex, sys
words = shlex.split(" ".join(sys.argv[1:]))
verb = words[words.index("mac.sh") + 1]
with open({calls!r}, "a") as calls:
    calls.write(verb + "\\n")
if verb == "probe":
    print("cpus 4\\nload 0\\nroom_mb 65536" if os.path.exists({room!r}) else
          "cpus 4\\nload 4\\nroom_mb 0")
elif verb == "prepare":
    sys.stdin.buffer.read()
"""


def land(case, room_later):
    """(the shares run here, the Mac's verbs) once the task landed; this host's one turn is
    held until the Mac was probed twice, then the Mac gets room or the turn frees."""
    home = Home()
    case.addCleanup(home.close)
    calls, room = home.root / "calls", home.root / "room"
    here = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    case.addCleanup(here.close)
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
    akconfig.write(home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
    fakeadapter.install(home, claude="work", codex="pass")["claude"].behave(
        {"write": {"retry.txt": "hello\n"}, "commit": "add retry.txt", "hand_in": [["done"]]})
    (runs := home.path / ".agentkit" / "runs").mkdir(parents=True)
    with (runs / ".heavy-0.lock").open("a") as turn:
        fcntl.flock(turn, fcntl.LOCK_EX)
        run = home.spawn("run", str(taskfile.write(home, rig.path, "Add retry file")))
        deadline = time.monotonic() + 300
        while (calls.read_text().split() if calls.exists() else []).count("probe") < 2:
            case.assertIsNone(run.poll(), home.log("spawn-1.err").read_text())
            case.assertLess(time.monotonic(), deadline, "the waiting suite never asked again")
            time.sleep(0.2)
        if room_later:
            room.touch()
            case.assertEqual(run.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
    if not room_later:
        case.assertEqual(run.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
    here.setblocking(False)
    shares = []
    while True:
        try:
            shares.append(here.recv(64).decode())
        except BlockingIOError:
            return shares, calls.read_text().split()


class WaitingSuiteGoesToTheMac(unittest.TestCase):
    def test_a_suite_waiting_here_runs_on_the_mac_once_it_has_room(self):
        shares, verbs = land(self, room_later=True)
        self.assertEqual(shares, [])
        self.assertIn("run", verbs)

    def test_a_suite_the_mac_has_no_room_for_runs_here_once_a_turn_frees(self):
        shares, verbs = land(self, room_later=False)
        self.assertEqual(shares, ["1/1"])
        self.assertNotIn("run", verbs)


if __name__ == "__main__":
    unittest.main()
