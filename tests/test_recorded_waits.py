"""A seat's turn ends on a fact ak records, and nothing is owed without an open plan line.

The stop hook decides from the record alone: a question, a done, a run of the seat's going, a
merged run of its not yet live where its project declares `health:`, or an `ak wait` on a pull
request or run ends the turn; with no open line in the seat's plan nothing is owed and any
reply stands; with one open and none of those recorded the stop is sent back twice, and the
third becomes a question to the owner carrying the seat's last words, kept back for the next
look to ask as the seat's own `ak notify needs` is.  No words of the owner's prompt decide
anything, and the hook waits on no notice lock.  Offline: hooks/seat-state.sh and hooks/orchestrator-stop.sh run as
their harness runs them, JSON on stdin, against fake records in a throwaway HOME.
"""

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.merged_run import SEAT, MergedRuns
from agentkit import config, notify, watch

HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT_STATE = REPO / "hooks/seat-state.sh"
SAID = "The parser is fixed and the tests pass. Let me know if I should continue."
LINE = "- [ ] the parser parses · check: `false` · acme · written 2026-10-09 12:00\n"
HAND_KEPT = "- [ ] fix the parser\n"      # open as a done reads it, though `ak plan` never wrote it
ASKED = "How should this seat go on? It stopped three times with work open: " + SAID


class RecordedWaits(MergedRuns):
    def setUp(self):
        super().setUp()
        self.turn = time.time() - 60

    def env(self):
        return {"PATH": os.environ["PATH"], "HOME": str(self.home),
                "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}

    def prompt(self, text):
        """Open a turn through hooks/seat-state.sh, as the harness does on a prompt."""
        done = subprocess.run(["bash", str(SEAT_STATE)], text=True, capture_output=True,
                              input=json.dumps({"hook_event_name": "UserPromptSubmit",
                                                "prompt": text}),
                              env={**self.env(), "IDLE_COMPACT_STATE": ""})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads((self.state / f"stop-{SEAT}.json").read_text())

    def stop(self, said=SAID, hook=HOOK, **payload):
        """One end-of-turn hook call; what it prints is what the harness reads back."""
        transcript = self.home / "transcript.jsonl"
        transcript.write_text("".join(json.dumps(line) + "\n" for line in (
            {"type": "user", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "text", "text": said}]}})))
        done = subprocess.run(["bash", str(hook)], text=True, capture_output=True,
                              input=json.dumps({"hook_event_name": "Stop", "session_id": "fake",
                                                "transcript_path": str(transcript), **payload}),
                              env=self.env(), timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def blocked(self, output):
        self.assertTrue(output.strip(), "the hook allowed the stop")
        return json.loads(output)

    def owes(self, line=LINE):
        (self.state / f"plan-{SEAT}.md").write_text(line)

    def notice(self):
        path = self.state / f"notify-{SEAT}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def kept(self):
        path = self.state / f"seat-{SEAT}.json"
        return (json.loads(path.read_text()) if path.exists() else {}).get("unasked")

    def held_notice_lock(self):
        """The seat's notice lock, held as a delivery or a card post holds it."""
        lock = (self.state / f"notify-{SEAT}.lock").open("a")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        return lock

    def look(self):
        """What the next look does with a question kept back for a turn that has ended."""
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from agentkit import notify\n"
                "with notify.session_lock(sys.argv[2]) as name: notify.ask_kept(name, ended=True)")
        subprocess.run([sys.executable, "-c", code, str(REPO), SEAT], env=self.env(), check=True,
                       timeout=120)

    def read_as(self):
        """(state, event) a Claude seat's row reads off what its hooks have written down."""
        with patch.object(config, "STATE", self.state):
            return watch.hook_state("claude", watch.hook_facts(SEAT))[:2]

    def test_a_reply_stands_while_nothing_is_owed_whatever_the_prompt_said(self):
        for opened in ("Which parser does it use?", "Merge the parser now", "is main green"):
            with self.subTest(opened=opened):
                latch = self.prompt(opened)
                self.assertNotIn("asked", latch)
                self.assertEqual(self.stop(), "")
                self.assertEqual(json.loads((self.state / f"stop-{SEAT}.json").read_text())["blocks"], 0)

    def test_with_work_open_a_reply_is_sent_back_and_the_third_stop_asks_the_owner(self):
        for line in (LINE, HAND_KEPT):
            with self.subTest(line=line):
                self.setUp()
                self.owes(line)
                self.prompt("Which parser does it use?")
                (self.state / f"seat-{SEAT}.json").write_text(json.dumps({  # over, not yet told
                    "session": SEAT, "wait": {"kind": "run", "on": "gone", "at": self.turn,
                                              "over": True}}) + "\n")
                lock = self.held_notice_lock()          # the hook decides without it
                for _ in range(2):
                    back = json.loads(self.stop())
                    self.assertEqual(back["decision"], "block")
                    self.assertIn("You stopped with work open and nothing recorded", back["reason"])
                    self.assertIsNone(self.kept())
                self.assertEqual(self.stop(), "")       # the third stop stands ...
                self.assertIsNone(self.notice())        # ... its question kept back, its turn ended
                self.assertEqual(self.kept()["text"], ASKED)
                notify.asks_first(ASKED)                # shaped as `ak notify needs` takes one
                self.assertIsInstance(self.kept()["ended"], float)
                seat = json.loads((self.state / f"seat-{SEAT}.json").read_text())
                self.assertIsNone(seat["wait"])         # the question ends the wait's line
                lock.close()
                self.look()                             # ... and the next look asks the owner
                notice = self.notice()
                self.assertEqual(notice["kind"], "needs")
                self.assertEqual(notice["text"], ASKED)
                self.assertIsNone(self.kept())

    def test_the_third_stops_question_carries_the_owners_earlier_answer(self):
        # recorded as `ak notify needs` records one: the owner's answer to the question it
        # replaces rides along, so that question's card closes as answered
        self.owes()
        (self.state / f"notify-{SEAT}.json").write_text(json.dumps({            # answered before this turn
            "session": SEAT, "kind": "done", "text": "Finished the parser", "time": time.time() - 60,
            "answered_at": 1234.5}) + "\n")
        self.prompt("Carry on")
        for _ in range(2):
            self.assertEqual(json.loads(self.stop())["decision"], "block")
        self.assertEqual(self.stop(), "")
        self.look()
        notice = self.notice()
        self.assertEqual(notice["text"], ASKED)
        self.assertEqual(notice["earlier_answer_at"], 1234.5)

    def test_a_merged_run_not_yet_live_is_a_wait_where_its_project_proves_itself_live(self):
        self.owes()
        self.prompt("go")
        self.merged("20260101-0900-merged", health=True, live=False)
        self.assertEqual(self.stop(), "")
        # ... not once it is live, and not where the project declares no health
        for name, kwargs in (("20260101-0800-live", {"health": True, "live": True}),
                             ("20260101-0700-plain", {"health": False, "live": False}),
                             ("20260101-0600-old", {"health": True, "live": False,
                                                    "age": watch.AFTER_MERGE_WINDOW + 60})):
            with self.subTest(run=name):
                self.setUp()
                self.owes()
                self.prompt("go")
                self.merged(name, **kwargs)
                self.assertEqual(json.loads(self.stop())["decision"], "block")

    def test_a_done_this_turn_ends_it_with_work_open(self):
        self.owes()
        self.prompt("go")
        (self.state / f"notify-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "kind": "done", "text": "Shipped the parser", "time": time.time()}) + "\n")
        self.assertEqual(self.stop(), "")

    def test_a_standing_stop_is_written_down_as_the_seat_at_its_prompt(self):
        self.prompt("Which parser does it use?")
        self.assertEqual(self.stop(background_tasks=[]), "")
        self.stop(hook=SEAT_STATE, background_tasks=[])
        self.assertEqual(self.read_as(), ("at_prompt", "Stop"))
        self.assertEqual(json.loads((self.state / f"stop-{SEAT}.json").read_text())["blocks"], 0)

    def test_a_parked_run_holds_a_reply_with_nothing_owed_and_the_third_stop_asks_nothing(self):
        self.prompt("Which parser does it use?")
        self.assertEqual(self.stop(), "")       # no parked run, nothing owed: the reply stands
        self.parked_exhausted()
        self.prompt("Which parser does it use?")
        for _ in range(2):
            reason = self.blocked(self.stop())["reason"]
            self.assertIn("run parked-exhausted parked: ", reason)
            self.assertIn("ak run resume parked-exhausted", reason)
        self.assertEqual(self.stop(), "")       # the third stop stands ...
        self.assertIsNone(self.kept())          # ... on the parked card, with no question of its own
        self.assertIsNone(self.notice())


if __name__ == "__main__":
    unittest.main(verbosity=2)
