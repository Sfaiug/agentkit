"""An open seat's `c` follows its record without a key, keeping the highlighted row and column.

Black-box against AK_BIN, over akseat.py seats with fake harnesses: an answer at another
effort is looked at by a tick while `c` is already open, and another screen's saved roles and
efforts reach it too. A local step survives the next read, and unchanged rows stay still.
"""

import json
from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_effort_followed_from_inside import opus_effort, stamp


def row(screen, name):
    return next((line for line in screen.splitlines()
                 if line.lstrip("› ").startswith(name)), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CFollowsTheSeat(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus", "astra"], workers=["opus"])
        fakeadapter.install(self.home, claude="pass", codex="pass")
        self.now = time.time()
        self.seat = Seat(self.home, "acme-fix", record={
            "launched": self.now - 600, "reviewers": ["astra"],
            "efforts": {"opus": {"effort": "xhigh"}, "astra": {"effort": "xhigh"}}})
        self.path = self.home.path / ".agentkit/state/session-acme-fix.json"
        self.term = Terminal(self.home, "attach", "--overlay", size=(100, 40),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": "acme-fix"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "esc back" in screen and opus_effort(screen) == "xhigh")

    @unittest.skipUnless(boxable(), "no tick sandbox")
    def test_an_answer_at_low_reaches_c_while_it_is_open(self):
        project = "".join(c if c.isascii() and c.isalnum() else "-" for c in str(self.seat.cwd))
        self.home.write(f".claude/projects/{project}/{self.seat.record['conversation']}.jsonl",
                        json.dumps({"type": "assistant", "timestamp": stamp(self.now - 60),
                                    "effort": "low", "message": {"model": "claude-opus-5-5"}})
                        + "\n")
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(self.path.read_text())["efforts"]["opus"]["effort"], "low")
        self.term.wait(lambda screen: opus_effort(screen) == "low", bound=5)

    def test_every_role_and_effort_follows_without_moving_the_highlight_or_undoing_a_step(self):
        self.term.keys("Right", "Right", "Right")   # Opus's build effort
        self.term.wait("␣ step")
        changed = json.loads(self.path.read_text())
        changed.update(orchestrator="astra", workers=["opus", "astra"], reviewers=["opus"],
                       efforts={"opus": {"effort": "xhigh", "exec_effort": "low",
                                         "review_effort": "high"},
                                "astra": {"effort": "max", "exec_effort": "high"}})
        self.home.write(".agentkit/state/replacement.json", changed).replace(self.path)

        def followed(screen):
            opus = row(screen, "Opus 5.5")
            astra = row(screen, "GPT-6-Astra")
            return (opus.startswith("›") and opus.split()[3:] == [
                "○", "■", "━────", "low", "■", "━━━──", "high"]
                and astra.split()[1:] == ["●", "━━━━━─", "max", "■", "━━━───", "high", "□"]
                and "␣ step" in screen)
        self.term.wait(followed, bound=5)
        self.term.keys("Space")                       # still Opus's build effort
        self.term.wait(lambda screen: "medium" in row(screen, "Opus 5.5"))
        self.assertEqual(json.loads(self.path.read_text())["efforts"]["opus"]["exec_effort"],
                         "medium")

        # A later record change proves another read landed after the local save.
        changed = json.loads(self.path.read_text())
        changed["efforts"]["astra"]["exec_effort"] = "low"
        self.home.write(".agentkit/state/replacement.json", changed).replace(self.path)
        screen = self.term.wait(lambda screen: "low" in row(screen, "GPT-6-Astra"), bound=5)
        self.assertIn("medium", row(screen, "Opus 5.5"))
        self.assertEqual(json.loads(self.path.read_text())["efforts"]["opus"]["exec_effort"],
                         "medium")

    def test_unchanged_rows_stay_still(self):
        # `c` opens on no reading; the menu's probe landing then redraws the meters, rightly
        self.term.wait(lambda screen: "no reading yet" not in screen)
        raw = self.home.root / "c-output"
        raw.touch()
        done = self.home.tmux("pipe-pane", "-t", self.term.pane, f"cat >{raw}", server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        time.sleep(2.2)    # leave the screen alone through more than one record read
        self.home.tmux("pipe-pane", "-t", self.term.pane, server=SERVER)
        # The minute on the header may change; none of the body's rows does.
        written = raw.read_bytes()
        self.assertNotIn(b"\x1b[H", written)
        self.assertFalse(re.search(rb"\x1b\[(?:[2-9]|[1-9]\d+);1H[^\x1b]", written))


if __name__ == "__main__":
    unittest.main()
