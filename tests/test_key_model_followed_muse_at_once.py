"""A Muse /model change reaches the seat's record, bar and c on one look, before an answer.

Black-box against AK_BIN: Muse 1.4.14 records runtime.model_reconfigure.completed in the
seat's session.jsonl. Its effective model counts at that entry's time, keeping the effort
the seat already holds; a later answer wins and a change before the launch moves nothing.
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from test_key_model_followed_opencode_muse import SPARK, WONDER, WONDER_NAMED, muse_answer, muse_line
from test_key_orch_list_rows import bar

SESSION = "01a18c52-a770-75a1-9576-acme00000001"
RUN = "01a18c52-0000-7000-8000-run000000001"


def reconfigured(at, model):
    return muse_line(SESSION, at, "runtime.model_reconfigure.completed",
                     {"record": {"effective": {"model_id": model}}}) + "\n"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MuseModelFollowedAtOnce(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {"spark": {}, "wonder": {
            "harness": "muse", "model": WONDER, "effort": "xhigh"}})
        fakeadapter.install(home, muse="pass")
        self.now = int(time.time())
        self.launched = self.now - 600
        self.efforts = {"spark": {"effort": "high"},
                        "wonder": {"effort": "medium", "exec_effort": "high",
                                   "review_effort": "max"}}
        token = "a" * 32
        self.seat = Seat(home, "acme-muse", model="spark", screen="muse-prompt-pane.txt",
                         record={"launched": self.launched, "muse_launch": token,
                                 "efforts": self.efforts})
        home.write(f".agentkit/state/muse-launch-{token}/session", SESSION)
        day = datetime.fromtimestamp(self.now, timezone.utc).strftime("%Y/%m/%d")
        self.log = home.write(f".local/share/muse/sessions/{day}/{SESSION}/session.jsonl",
                              muse_answer(SESSION, RUN, self.now - 900, SPARK, "startup"))

    def append(self, text):
        with self.log.open("a", encoding="utf-8") as fh:
            fh.write(text)

    def looked(self):
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads((self.home.path / ".agentkit/state/session-acme-muse.json").read_text())

    def test_a_reconfigure_without_a_new_answer_moves_the_record_bar_and_c_at_once(self):
        self.append(reconfigured(self.now - 60, WONDER))
        record = self.looked()
        self.assertEqual(record["orchestrator"], "wonder")
        self.assertEqual(record["efforts"], {
            **self.efforts, "wonder": {**self.efforts["wonder"], "effort": "high"}})
        self.assertIn(f"{WONDER_NAMED} high", bar(self.home, self.seat))
        term = Terminal(self.home, "attach", "--overlay", size=(120, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": self.seat.name})
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "esc back" in screen and re.search(
            rf"^[› ] {re.escape(WONDER_NAMED)} +\[?●\]? +\S+ +high\b", screen, re.M))

    def test_a_reconfigure_before_any_answer_also_moves_the_seat(self):
        self.log.write_text(reconfigured(self.now - 60, WONDER))
        self.assertEqual(self.looked()["orchestrator"], "wonder")

    def test_a_reconfigure_up_to_the_launch_moves_nothing(self):
        for at in (self.launched - 60, self.launched):
            with self.subTest(at=at):
                self.append(reconfigured(at, WONDER))
                self.assertEqual(self.looked()["orchestrator"], "spark")

    def test_a_later_answer_wins_over_a_reconfigure(self):
        self.append(reconfigured(self.now - 60, WONDER)
                    + muse_answer(SESSION, RUN, self.now - 30, SPARK, "model_reconfigure"))
        self.assertEqual(self.looked()["orchestrator"], "spark")

    def test_only_a_completed_reconfigure_naming_an_effective_model_counts(self):
        self.append(reconfigured(self.now - 60, WONDER))
        for payload in ({}, {"record": None}, {"record": {"effective": None}},
                        {"record": {"effective": {"model_id": 42}}}):
            self.append(muse_line(SESSION, self.now - 30,
                                  "runtime.model_reconfigure.completed", payload) + "\n")
        self.append(muse_line(SESSION, self.now - 20, "runtime.model_reconfigure.started",
                              {"record": {"effective": {"model_id": SPARK}}}) + "\n"
                    + '{"payload_type": "runtime.model_reconfigure.completed"')
        self.assertEqual(self.looked()["orchestrator"], "wonder")


if __name__ == "__main__":
    unittest.main()
