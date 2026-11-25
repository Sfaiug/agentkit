"""A model with one effort has no bar on `c`, so its effort word sits beside its mark where a
barred model's first cell stands, in all three role columns, and a click or Space on that word
still steps it (the owner, 25 Nov 2026).  Black-box: `AK_BIN` as the popup over akseat.py seats
in an akterm.py terminal, its harness fakeadapter.py's; it fails against `/bin/false`."""

import json
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

MODELS = {"opus": {},
          "haiku": {"harness": "claude", "model": "claude-haiku-4-5", "effort": "none"}}
OPUS_EFFORTS = {"effort": "low", "exec_effort": "high", "review_effort": "medium"}


def model_row(screen, label):
    """`label`'s line on `c`, and its row on the terminal from 1."""
    return next((line, row) for row, line in enumerate(screen.split("\n"), 1)
                if line.lstrip("› ").startswith(label))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WordWithNoBar(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, MODELS, orchestrator="opus", workers=["opus", "haiku"],
                       reviewers=["opus", "haiku"])
        fakeadapter.install(self.home, claude="pass")

    def open_c(self, seat, record, size=(100, 30)):
        Seat(self.home, seat, record=record)
        term = Terminal(self.home, "attach", "--overlay", size=size,
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": seat})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane,
                        "sleep 86400", server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        opened = term.wait(lambda screen: "esc back" in screen and "Haiku 4.5" in screen)
        return term, opened

    def record_waits(self, seat, expected):
        path = self.home.path / f".agentkit/state/session-{seat}.json"
        deadline = time.monotonic() + 30
        while json.loads(path.read_text()).get("efforts", {}).get("haiku") != expected:
            self.assertLess(time.monotonic(), deadline, path.read_text())
            time.sleep(0.05)

    def test_a_one_effort_word_sits_where_a_bars_first_cell_starts_in_all_three_roles(self):
        haiku_efforts = {"effort": "none", "exec_effort": "xhigh", "review_effort": "none"}
        term, opened = self.open_c("acme-fix", {
            "orchestrator": "opus", "workers": ["opus", "haiku"], "reviewers": ["opus", "haiku"],
            "efforts": {"opus": OPUS_EFFORTS, "haiku": haiku_efforts}})
        opus_line, _ = model_row(opened, "Opus 5.5")
        haiku_line, haiku_row = model_row(opened, "Haiku 4.5")
        bars = [bar.start() for bar in re.finditer("[━─]+", opus_line)]
        self.assertEqual(len(bars), 3, opus_line)
        # a barred model keeps its words after its bars
        self.assertEqual(opus_line.split()[3:], [
            "[●]", "━────", "low", "■", "━━━──", "high", "■", "━━───", "medium"])
        # a cell-less model's words start where the barred model's first cells start
        self.assertEqual(haiku_line.index("xhigh"), bars[1], f"\n{opus_line}\n{haiku_line}")
        self.assertEqual(haiku_line.index("none"), bars[2], f"\n{opus_line}\n{haiku_line}")
        # the blank space where the word used to stand is on nothing; a click on the word steps it
        old_column = opus_line.index("high") + 1
        term.type(f"\x1b[<35;{old_column};{haiku_row}M")
        term.wait(lambda screen: not any(line.startswith("›") for line in screen.split("\n")))
        column = bars[1] + 1
        term.type(f"\x1b[<0;{column};{haiku_row}M\x1b[<0;{column};{haiku_row}m")
        stepped = term.wait(lambda screen: "xhigh" not in model_row(screen, "Haiku 4.5")[0])
        self.assertEqual([word.start() for word in re.finditer(
            "none", model_row(stepped, "Haiku 4.5")[0])], bars[1:])
        term.keys("Escape")
        self.record_waits("acme-fix", {"effort": "none", "review_effort": "none"})

        # in the orchestrator column too, and Space on a cell-less word steps it
        orch_efforts = {"effort": "none", "exec_effort": "none", "review_effort": "xhigh"}
        term2, opened2 = self.open_c("acme-orch", {
            "orchestrator": "haiku", "workers": ["opus", "haiku"], "reviewers": ["opus", "haiku"],
            "efforts": {"opus": OPUS_EFFORTS, "haiku": orch_efforts}})
        opus_line2, _ = model_row(opened2, "Opus 5.5")
        haiku_line2, _ = model_row(opened2, "Haiku 4.5")
        bars2 = [bar.start() for bar in re.finditer("[━─]+", opus_line2)]
        self.assertEqual(len(bars2), 2, opus_line2)
        self.assertEqual(
            [word.start() for word in re.finditer(r"none|xhigh", haiku_line2)],
            [bars[0], *bars2], f"\n{opus_line2}\n{haiku_line2}")
        self.assertLessEqual(bars2[0], bars[1])         # role columns are no wider than today
        self.assertEqual(bars2[1] - bars2[0], bars[2] - bars[1])
        term2.keys("Down", "Right", "Right", "Right", "Right", "Right", "Space")
        term2.wait(lambda screen: "xhigh" not in model_row(screen, "Haiku 4.5")[0])
        term2.keys("Escape")
        self.record_waits("acme-orch", {"effort": "none", "exec_effort": "none"})

        # at 60 columns, bars still give way when the orchestrator has none
        _, narrow = self.open_c("acme-narrow", {
            "orchestrator": "haiku", "workers": ["opus", "haiku"], "reviewers": ["opus", "haiku"],
            "efforts": {"opus": OPUS_EFFORTS, "haiku": orch_efforts}}, size=(60, 30))
        narrow_opus, _ = model_row(narrow, "Opus 5.5")
        self.assertIsNone(re.search("[━─]", narrow_opus), narrow_opus)


if __name__ == "__main__":
    unittest.main()
