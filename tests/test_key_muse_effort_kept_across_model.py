"""Muse keeps the seat's effort across /model; one look follows it in the record and bar.

Black-box against AK_BIN, with Muse's session.jsonl and an effort the seat holds for itself,
different from both models' configured efforts and the destination's previously held effort.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from test_key_model_followed_muse_at_once import RUN, SESSION, reconfigured
from test_key_model_followed_opencode_muse import SPARK, WONDER, WONDER_NAMED, muse_answer
from test_key_orch_list_rows import bar


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MuseEffortKeptAcrossModel(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {
            "spark": {"harness": "muse", "model": SPARK, "effort": "high"},
            "wonder": {"harness": "muse", "model": WONDER, "effort": "max"}})
        fakeadapter.install(home, muse="pass")
        self.now = int(time.time())
        self.efforts = {"spark": {"effort": "xhigh", "exec_effort": "low"},
                        "wonder": {"effort": "medium", "exec_effort": "high",
                                   "review_effort": "max"}}
        token = "b" * 32
        self.seat = Seat(home, "acme-muse", model="spark", screen="muse-prompt-pane.txt",
                         record={"launched": self.now - 600, "muse_launch": token,
                                 "efforts": self.efforts})
        home.write(f".agentkit/state/muse-launch-{token}/session", SESSION)
        day = datetime.fromtimestamp(self.now, timezone.utc).strftime("%Y/%m/%d")
        self.log = home.write(f".local/share/muse/sessions/{day}/{SESSION}/session.jsonl", "")

    def followed_at_seat_effort(self, text):
        self.log.write_text(text)
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.out + done.err)
        record = json.loads((self.home.path / ".agentkit/state/session-acme-muse.json").read_text())
        self.assertEqual(record["orchestrator"], "wonder")
        expected = {**self.efforts, "wonder": {**self.efforts["wonder"], "effort": "xhigh"}}
        self.assertEqual(record["efforts"], expected)
        self.assertIn(f"{WONDER_NAMED} xhigh", bar(self.home, self.seat))

    def test_reconfigure_before_an_answer_keeps_the_effort(self):
        self.followed_at_seat_effort(reconfigured(self.now - 60, WONDER))

    def test_an_answer_after_a_model_change_keeps_the_effort(self):
        self.followed_at_seat_effort(
            muse_answer(SESSION, RUN, self.now - 900, SPARK, "startup")
            + muse_answer(SESSION, RUN, self.now - 60, WONDER, "model_reconfigure"))


if __name__ == "__main__":
    unittest.main()
