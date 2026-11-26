"""The models screen's role columns stay in place whatever is marked and whatever effort each
mark runs at (the owner, 26 Nov 2026).  Black-box: `AK_BIN` as the popup over akseat.py seats
in an akterm.py terminal, its harness fakeadapter.py's; it fails against `/bin/false`."""

import json
from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

MODELS = {"opus": {},
          "haiku": {"harness": "claude", "model": "claude-haiku-4-5", "effort": "none"}}
LOW_OPUS = {"effort": "low", "exec_effort": "low", "review_effort": "low"}
MIXED_OPUS = {"effort": "low", "exec_effort": "high", "review_effort": "medium"}
HAIKU = {"effort": "none", "exec_effort": "none", "review_effort": "none"}


def heads_line(screen):
    return next(line.rstrip() for line in screen.split("\n")
                if line.split() == ["orch", "builds", "reviews"])


def model_line(screen, prefix):
    return next(line.rstrip() for line in screen.split("\n")
                if line.lstrip("› ").startswith(prefix))


def mark_columns(line):
    return [mark.start() for mark in re.finditer("[●○■□]", line)]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ColumnsStayInPlace(unittest.TestCase):
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
        opened = term.wait(lambda screen: "esc back" in screen and "Claude Code" in screen
                           and "reviews" in screen)
        return term, opened

    def record_waits(self, seat, workers, exec_effort):
        path = self.home.path / f".agentkit/state/session-{seat}.json"
        deadline = time.monotonic() + 30
        while True:
            data = json.loads(path.read_text())
            if (data.get("workers") == workers
                    and data.get("efforts", {}).get("opus", {}).get("exec_effort") == exec_effort):
                return
            self.assertLess(time.monotonic(), deadline, path.read_text())
            time.sleep(0.05)

    def test_role_columns_stay_in_place_across_marks_and_efforts_with_and_without_bars(self):
        # 100 columns: one orchestrator on the one-effort model vs every role marked
        term_one, one = self.open_c("acme-one", {
            "orchestrator": "haiku", "workers": [], "reviewers": [],
            "efforts": {"opus": LOW_OPUS, "haiku": HAIKU}})
        term_all, every = self.open_c("acme-all", {
            "orchestrator": "opus", "workers": ["opus", "haiku"], "reviewers": ["opus", "haiku"],
            "efforts": {"opus": MIXED_OPUS, "haiku": HAIKU}})
        heads_one, heads_all = heads_line(one), heads_line(every)
        self.assertEqual(heads_one, heads_all)
        opus_all = model_line(every, "Opus 5.5")
        haiku_one = model_line(one, "Haiku 4.5")
        self.assertEqual(mark_columns(model_line(one, "Opus 5.5")), mark_columns(opus_all))
        self.assertEqual(mark_columns(haiku_one), mark_columns(model_line(every, "Haiku 4.5")))
        bars_all = [bar.start() for bar in re.finditer("[━─]+", opus_all)]
        self.assertEqual(len(bars_all), 3, opus_all)
        self.assertEqual(haiku_one.index("none"), bars_all[0], f"\n{opus_all}\n{haiku_one}")
        term_all.keys("Escape")

        # marking Opus for builds and stepping its effort leaves every head, mark and effort put
        term_one.keys("Right", "Space")
        marked = term_one.wait(lambda screen: "■" in model_line(screen, "Opus 5.5"))
        self.assertEqual(heads_line(marked), heads_all)
        self.assertEqual(mark_columns(model_line(marked, "Opus 5.5")), mark_columns(opus_all))
        self.assertEqual(re.search("[━─]+", model_line(marked, "Opus 5.5")).start(), bars_all[1])
        term_one.keys("Right", "Space")
        stepped = term_one.wait(lambda screen: "medium" in model_line(screen, "Opus 5.5"))
        self.assertEqual(heads_line(stepped), heads_all)
        self.assertEqual(mark_columns(model_line(stepped, "Opus 5.5")), mark_columns(opus_all))
        self.assertEqual(re.search("[━─]+", model_line(stepped, "Opus 5.5")).start(), bars_all[1])
        self.assertEqual(model_line(stepped, "Haiku 4.5").index("none"), bars_all[0])
        term_one.keys("Escape")
        self.record_waits("acme-one", ["opus"], "medium")

        # 50 columns: fixed words fit beside whole names (44 cols) and bars do not (68 cols);
        # every head, mark and effort stays in the same cell across mark & step, names uncut
        term_mid, mid = self.open_c("acme-mid", {
            "orchestrator": "haiku", "workers": [], "reviewers": [],
            "efforts": {"opus": LOW_OPUS, "haiku": HAIKU}}, size=(50, 30))
        mid_heads = heads_line(mid)
        mid_marks = mark_columns(model_line(mid, "Opus 5.5"))
        self.assertEqual(mark_columns(model_line(mid, "Haiku 4.5")), mid_marks)
        haiku_effort = model_line(mid, "Haiku 4.5").index("none")

        term_mid.keys("Right", "Space")
        mid_marked = term_mid.wait(lambda screen: "■" in model_line(screen, "Opus 5.5"))
        self.assertIsNone(re.search("[━─]", model_line(mid_marked, "Opus 5.5")), mid_marked)
        self.assertEqual(heads_line(mid_marked), mid_heads)
        self.assertEqual(mark_columns(model_line(mid_marked, "Opus 5.5")), mid_marks)
        self.assertEqual(mark_columns(model_line(mid_marked, "Haiku 4.5")), mid_marks)
        self.assertEqual(model_line(mid_marked, "Haiku 4.5").index("none"), haiku_effort)
        build_effort = model_line(mid_marked, "Opus 5.5").index("low")

        term_mid.keys("Right", "Space")
        mid_stepped = term_mid.wait(lambda screen: "medium" in model_line(screen, "Opus 5.5"))
        self.assertEqual(heads_line(mid_stepped), mid_heads)
        self.assertEqual(mark_columns(model_line(mid_stepped, "Opus 5.5")), mid_marks)
        self.assertEqual(mark_columns(model_line(mid_stepped, "Haiku 4.5")), mid_marks)
        self.assertEqual(model_line(mid_stepped, "Haiku 4.5").index("none"), haiku_effort)
        self.assertEqual(model_line(mid_stepped, "Opus 5.5").index("medium"), build_effort)
        term_mid.keys("Escape")
        self.record_waits("acme-mid", ["opus"], "medium")


if __name__ == "__main__":
    unittest.main()
