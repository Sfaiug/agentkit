"""Grok Build's /model and effort changes reach the seat on its next look, before any answer.

Black-box against AK_BIN: a seat's summary.json as Grok Build 1.0.46 writes it names another
configured model and effort; its record, bar and c follow, using the file's write time.
"""

import json
import os
from pathlib import Path
import re
import sys
import time
import unittest
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelFollowedInsideGrokBuild(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {
            "grok": {}, "fast": {"harness": "grokbuild", "model": "grok-4.7-build-fast"}})
        fakeadapter.install(self.home, grokbuild="pass")
        self.launched = time.time() - 600
        self.seat = Seat(self.home, "acme-fix", model="grok", screen="grok-title-idle-pane.txt",
                         record={"launched": self.launched,
                                 "conversation": "00000000-0000-4000-8000-000000000001"})

    def summary(self, model="grok-4.7-build-fast", effort="low", *, at=None):
        root = Path(self.home.env.get("GROK_HOME", self.home.path / ".grok"))
        path = (root / "sessions" / quote(str(self.seat.cwd), safe="") /
                self.seat.record["conversation"] / "summary.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "info": {"id": self.seat.record["conversation"], "cwd": str(self.seat.cwd)},
            "generated_title": self.seat.name, "title_is_manual": True, "num_messages": 0,
            "current_model_id": model, "reasoning_effort": effort}))
        at = self.launched + 60 if at is None else at
        os.utime(path, (at, at))
        return path

    def look(self):
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads((self.home.path /
                           f".agentkit/state/session-{self.seat.name}.json").read_text())

    def assert_bar(self, label):
        done = self.home.tmux("show-options", "-qv", "-t", f"={self.seat.name}:", "@ak_top")
        self.assertEqual(done.code, 0, done.err)
        self.assertIn(label, done.out)

    def test_model_and_effort_then_effort_alone_follow_without_an_answer(self):
        self.summary("grok-4.7", "xhigh")
        self.assertEqual(self.look()["orchestrator"], "grok")
        self.summary()
        record = self.look()
        self.assertEqual(record["orchestrator"], "fast")
        self.assertEqual(record["efforts"]["fast"]["effort"], "low")
        self.assert_bar("Grok 4.7 Fast low")
        self.summary(effort="medium", at=self.launched + 120)
        record = self.look()
        self.assertEqual(record["orchestrator"], "fast")
        self.assertEqual(record["efforts"]["fast"]["effort"], "medium")
        self.assert_bar("Grok 4.7 Fast medium")
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": self.seat.name})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "esc back" in screen and re.search(
            r"^[› ] Grok 4\.7 Fast +\[?●\]? +\S+ +medium\b", screen, re.M))

    def test_old_missing_or_unreadable_summary_moves_nothing(self):
        self.summary(at=self.launched - 60)
        self.assertEqual(self.look()["orchestrator"], "grok")
        path = self.summary(at=self.launched)
        self.assertEqual(self.look()["orchestrator"], "grok")
        path.unlink()
        self.assertEqual(self.look()["orchestrator"], "grok")
        for contents in ("{", "[]", "null", "{}", '\x80'):
            with self.subTest(contents=contents):
                path.write_bytes(contents.encode("latin-1"))
                self.assertEqual(self.look()["orchestrator"], "grok")
        self.summary(model="grok-unknown")
        self.assertEqual(self.look()["orchestrator"], "grok")
        self.assert_bar("Grok 4.7 xhigh")

    def test_custom_grok_home_is_followed(self):
        self.home.env["GROK_HOME"] = str(self.home.path / "custom-grok")
        self.summary()
        record = self.look()
        self.assertEqual(record["orchestrator"], "fast")
        self.assertEqual(record["efforts"]["fast"]["effort"], "low")
        self.assert_bar("Grok 4.7 Fast low")


if __name__ == "__main__":
    unittest.main()
