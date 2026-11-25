"""The line a row of `Subscriptions` opens is one login's, however often its login is asked anew
while the page draws: its warning, email, plan and `→ log in again` are all the login that ends
soon, or all the one that does not, never one beside the other.

Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py), NO_COLOR, its harness the
fake of tests/fixtures/fakeadapter.py, while a process swaps state/logins.json between the two
logins as fast as it can and the keys draw the page again and again.  What the pane is written
is read from tmux's `pipe-pane`, every row of every draw, never a capture taken part way
through one.  Fails against `/bin/false`.
"""

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

# each a whole state/logins.json, written beside it and renamed over it, so a read is one of them
SWAP = """
import os, sys
path, states = sys.argv[1], sys.argv[2:]
while True:
    for state in states:
        with open(path + ".new", "w") as file:
            file.write(state)
        os.replace(path + ".new", path)
"""
# what each login's line says, and what it never does
ENDING = (("login first@acme.test ends", " · pro ", "→ log in again", "− remove"),
          ("second", "max"))
LASTING = ("second@acme.test · max 5x ", "− remove"), ("first", "ends", "pro", "log in again")
# each draw is one synchronized update; the pipe can begin or end part way through one
UPDATE = re.compile(r"\x1b\[\?2026h(.*?)\x1b\[\?2026l", re.S)
ROW = re.compile(r"\x1b\[\d+;\d+H|\x1b\[[JK]|\n")     # where a row of one is written
SGR = re.compile(r"\x1b\[[\d;]*m")
DRAWS = 40


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OneLoginsLine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, {"fable": "claude"},
                       providers={"anthropic": {"mode": "subscription"}})
        now = time.time()
        self.home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "anthropic": {"meters": [{"name": "weekly", "used": 16, "window_secs": 604800}]}}})

        def logins(email, plan, ends=None):
            return {"anthropic": {"default": {"email": email, "plan": plan, "ends": ends,
                                              "checked_at": now}}}
        self.ending = logins("first@acme.test", "pro", now + 2 * 86400)
        self.lasting = logins("second@acme.test", "max 5x")
        self.path = self.home.write(".agentkit/state/logins.json", self.ending)
        self.term = Terminal(self.home, size=(120, 30), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c", "Down", "Down")
        self.term.wait("› Subscriptions")
        self.term.keys("Enter")
        self.term.wait("login first@acme.test ends")
        self.raw = self.home.root / "raw"
        # the path quoted for sh, then for tmux, which reads `%` as strftime and `#` as a format
        named = shlex.quote(str(self.raw)).replace("%", "%%").replace("#", "##")
        piped = self.home.tmux("pipe-pane", "-O", "-t", self.term.pane, f"cat >>{named}",
                               server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)

    def lines(self):
        """Each opened line written since the pipe began, as written, of the updates it holds
        whole."""
        out = SGR.sub("", self.raw.read_bytes().decode("utf-8", "replace")
                      if self.raw.exists() else "")
        return [row for update in UPDATE.findall(out) for row in ROW.split(update)
                if "@acme.test" in row]

    def test_each_line_written_is_one_login_s(self):
        swap = subprocess.Popen([sys.executable, "-c", SWAP, str(self.path),
                                 *(json.dumps(state) for state in (self.ending, self.lasting))])
        self.addCleanup(swap.wait)
        self.addCleanup(swap.kill)
        deadline = time.monotonic() + 60
        while len(self.lines()) < DRAWS:      # a key draws the page again, its logins read anew
            self.assertLess(time.monotonic(), deadline, f"{DRAWS} lines never written; "
                            f"written:\n{self.lines()}")
            self.term.keys("Right", "Left")
            time.sleep(0.05)
        swap.kill()
        whose = [next((said for said, never in (ENDING, LASTING)
                       if all(word in line for word in said)
                       and not any(word in line for word in never)), line)
                 for line in self.lines()]
        self.assertEqual([line for line in whose if isinstance(line, str)], [])
        self.assertEqual({said for said in whose}, {ENDING[0], LASTING[0]})   # both were drawn


if __name__ == "__main__":
    unittest.main()
