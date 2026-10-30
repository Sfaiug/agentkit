"""A piece the suite helper turns away for room at its start waits for the suite's next place.

Black-box through tests/fixtures/akbin.py, as test_key_waiting_suite_goes_to_the_mac.py: one task
runs to the end and its repository's sharded suite runs as it lands.  The test holds this host's
one turn throughout, so the suite goes to the Mac, a fake ssh with room for two VMs.  The second
VM to start is turned away for room (exit 252) while the first still runs; a piece the Mac runs
passes there, and one run here sends the test its share.
"""

import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
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
SSH = """import fcntl, os, shlex, sys, time
words = shlex.split(" ".join(sys.argv[1:]))
verb, *args = words[words.index("mac.sh") + 1:]
with open({calls!r}, "a+") as calls:
    fcntl.flock(calls, fcntl.LOCK_EX)
    calls.seek(0)
    started = sum(line.startswith("run ") and line != "run 1/1\\n" for line in calls)
    calls.write(verb + (" " + args[6] if verb == "run" else "") + "\\n")
if verb == "probe":
    print("cpus 4\\nload 0\\nroom_mb 65536")
elif verb == "prepare":
    sys.stdin.buffer.read()
elif verb == "run" and args[6] == "1/1":    # a round's own checks, where they go there: not the suite
    pass
elif verb == "run" and started == 0:    # runs until the next VM is turned away
    deadline = time.monotonic() + 120
    while not os.path.exists({turned!r}) and time.monotonic() < deadline:
        time.sleep(0.1)
elif verb == "run" and started == 1:    # another suite took the room since the probe
    open({turned!r}, "w").close()
    sys.exit(252)
"""


class TurnedAwayForRoom(unittest.TestCase):
    def test_a_piece_turned_away_for_room_runs_on_the_mac_and_none_here(self):
        home = Home()
        self.addCleanup(home.close)
        calls, turned = home.root / "calls", home.root / "turned"
        here = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.addCleanup(here.close)
        here.bind(address := f"\0ak-shares-{os.getpid()}")
        # runs start below ak's free-memory floor, as only the suite's room is under test
        home.env.update(AK_HOST_READINGS=json.dumps(READINGS), AK_MIN_FREE_MB="0")
        # heavy suite turns, which `AK_MAX_RUNS=0` turns off
        home.env.pop("AK_MAX_RUNS")
        home.fake("ssh", f"#!{sys.executable}\n" + SSH.format(calls=str(calls),
                                                                turned=str(turned)))
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
            try:
                run.wait(timeout=300)
            except subprocess.TimeoutExpired:
                pass    # a piece waits for this turn: it runs here once the turn frees
        self.assertEqual(run.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
        here.setblocking(False)
        shares = []
        while True:
            try:
                shares.append(here.recv(64).decode())
            except BlockingIOError:
                break
        self.assertEqual(shares, [])
        ran = [line.split()[1] for line in calls.read_text().splitlines()
               if line.startswith("run ") and line != "run 1/1"]
        count = int(ran[0].split("/")[1])
        # every piece once on the Mac, and the one turned away a second time there
        self.assertEqual(sorted(ran), sorted([*(f"{k}/{count}" for k in range(1, count + 1)),
                                              ran[1]]))


if __name__ == "__main__":
    unittest.main()
