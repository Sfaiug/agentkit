"""A sharded suite's pieces go to whichever place frees first: this host's turn or the suite
helper's VM, each taking the next piece waiting as it ends one.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py.  This host fits two pieces (AK_HOST_READINGS) and the test holds one of
its turns, as another suite would, so the suite starts on one turn here and is cut in four, twice
the places it starts with.  A piece here runs until the test releases it.  The helper is a fake
ssh with room for one VM, on battery (exit 251) until a piece has run here and gone (exit 255)
while `gone` exists; a piece it runs passes there, and with `drop` it loses its second.
"""

import fcntl
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akline import Line

READINGS = json.dumps({"cpus": 64, "free_mb": 410, "mem_total_mb": 820})
HELD = 'until [ -e "$(git rev-parse --git-common-dir)/release" ]; do sleep 0.1; done\n'
# The words after the alias are one `bash -c <mac.sh> mac.sh <verb> ...` line.
SSH = f"""#!{sys.executable}
import os, shlex, sys
words = shlex.split(sys.argv[-1])
verb, *args = words[words.index("mac.sh") + 1:]
if os.path.exists({{gone!r}}):
    sys.exit(255)
if verb == "probe" and not os.path.exists({{here!r}}):
    sys.exit(251)
elif verb == "probe":
    print("cpus 2\\nload 0\\nroom_mb 65536")
elif verb == "prepare":
    sys.stdin.buffer.read()
elif verb == "run":
    with open({{sent!r}}, "a") as sent:
        sent.write(args[6] + "\\n")
    if {{drop}} and len(open({{sent!r}}).read().split()) == 2:
        open({{gone!r}}, "w").close()
        sys.exit(255)
"""


class PiecesGoToWhoeverIsFree(unittest.TestCase):
    def land(self, cue, drop=False, gone=False):
        """(the shares run here, those sent to the helper, what the lander said) once the line
        landed, the pieces here released once the helper was sent `cue` of them."""
        line = Line({**{f"t/{name}.sh": HELD for name in "abcd"},
                     "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        self.addCleanup(line.close)
        home, storage = line.home, line.rig.path / ".git"
        akconfig.write(home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        home.env.pop("AK_MAX_RUNS")     # heavy suite turns, which it turns off
        sent = home.root / "sent"
        home.fake("ssh", SSH.format(gone=str(home.root / "gone"), here=str(storage / "suite.log"),
                                    sent=str(sent), drop=drop))
        if gone:
            (home.root / "gone").touch()
        line.member({"api.txt": "x\n"})
        with (home.path / ".agentkit" / "runs" / ".heavy-0.lock").open("a") as turn:
            fcntl.flock(turn, fcntl.LOCK_EX)
            lander = home.spawn("run", "--lander", line.line, env={"AK_HOST_READINGS": READINGS})
            deadline = time.monotonic() + 300
            while len(sent.read_text().split() if sent.exists() else []) < cue:
                self.assertIsNone(lander.poll(), home.log("spawn-1.err").read_text())
                self.assertLess(time.monotonic(), deadline,
                                f"the helper was never sent {cue} pieces")
                time.sleep(0.2)
            (storage / "release").touch()
            self.assertEqual(lander.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
        self.assertIn("land", line.verdict(1))
        said = home.log("spawn-1.out").read_text() + home.log("spawn-1.err").read_text()
        return ([share for _, share, _ in line.runs()],
                sent.read_text().split() if sent.exists() else [], said)

    def test_a_helper_on_power_takes_the_three_pieces_waiting_beside_the_one_held_here(self):
        here, there, said = self.land(3)
        self.assertEqual(len(here), 1)
        self.assertEqual(sorted(here + there), [f"{k}/4" for k in range(1, 5)])
        self.assertIn("suite on acme-mac: 1 pieces, 2 CPUs and 820 MiB each", said)

    def test_what_a_helper_that_drops_left_runs_here(self):
        here, (passed, lost), said = self.land(2, drop=True)
        self.assertEqual(sorted(here + [passed]), [f"{k}/4" for k in range(1, 5)])
        self.assertIn(f"the suite helper acme-mac lost AK_SHARD={lost}; it runs again on the "
                      "first machine with room, this one included", said)

    def test_an_absent_helper_leaves_the_whole_suite_here(self):
        here, there, _ = self.land(0, gone=True)
        self.assertEqual((sorted(here), there), ([f"{k}/4" for k in range(1, 5)], []))


if __name__ == "__main__":
    unittest.main()
