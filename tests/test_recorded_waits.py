"""A seat's turn ends on a fact ak records, and nothing is owed without an open plan line.

The stop hook decides from the record alone: a question, a done, a run of the seat's going, a
merged run of its not yet live where its project declares `health:`, or an `ak wait` on a pull
request or run ends the turn; with no open line in the seat's plan nothing is owed and any
reply stands; with one open and none of those recorded the stop is sent back twice, and the
third becomes a question to the owner carrying the seat's last words.  No words of the owner's
prompt decide anything.  Offline: hooks/seat-state.sh and hooks/orchestrator-stop.sh run as
their harness runs them, JSON on stdin, against fake records in a throwaway HOME.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, watch

HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT_STATE = REPO / "hooks/seat-state.sh"
SEAT = "facts-seat"
SAID = "The parser is fixed and the tests pass. Let me know if I should continue."
LINE = "- [ ] the parser parses · check: `false` · acme · written 2026-10-09 12:00\n"
SPENT = "three rounds spent: split or re-scope the task"


class RecordedWaits(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-recorded-waits-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.runs = self.home / ".agentkit/runs"
        self.state.mkdir(parents=True)
        self.runs.mkdir(parents=True)
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
                              env=self.env())
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def blocked(self, output):
        self.assertTrue(output.strip(), "the hook allowed the stop")
        return json.loads(output)

    def owes(self):
        (self.state / f"plan-{SEAT}.md").write_text(LINE)

    def notice(self):
        path = self.state / f"notify-{SEAT}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def parked_exhausted(self, name="parked-exhausted"):
        directory = self.runs / name
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps(
            {"run_id": name, "launched_session": SEAT, "state": "exhausted", "error": SPENT,
             "started_at": time.time() - 9000, "finished_at": time.time() - 60}) + "\n")

    def read_as(self):
        """(state, event) a Claude seat's row reads off what its hooks have written down."""
        with patch.object(config, "STATE", self.state):
            return watch.hook_state("claude", watch.hook_facts(SEAT))[:2]

    def merged(self, name, *, health=True, live=False, age=600):
        """A merged run of the seat's, its project declaring `health:` or not."""
        repo = self.home / f"code-{name}"
        repo.mkdir()
        (repo / "AGENTS.md").write_text("---\nusers: real\n" + ("health: curl -fsS https://acme.test/ok\n" if health else "") + "---\n# acme\n")
        directory = self.runs / name
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps({
            "run_id": name, "launched_session": SEAT, "state": "pass", "verdict": "PASS",
            "merged": True, "repo": str(repo), "pr": "https://github.com/acme/widget/pull/7",
            "started_at": time.time() - age - 3600, "finished_at": time.time() - age,
            **({"live_at": time.time() - 10} if live else {})}) + "\n")

    def test_a_reply_stands_while_nothing_is_owed_whatever_the_prompt_said(self):
        for opened in ("Which parser does it use?", "Merge the parser now", "is main green"):
            with self.subTest(opened=opened):
                latch = self.prompt(opened)
                self.assertNotIn("asked", latch)
                self.assertEqual(self.stop(), "")
                self.assertEqual(json.loads((self.state / f"stop-{SEAT}.json").read_text())["blocks"], 0)

    def test_with_work_open_a_reply_is_sent_back_and_the_third_stop_asks_the_owner(self):
        self.owes()
        self.prompt("Which parser does it use?")
        for _ in range(2):
            back = json.loads(self.stop())
            self.assertEqual(back["decision"], "block")
            self.assertIn("You stopped with work open and nothing recorded", back["reason"])
            self.assertIsNone(self.notice())
        self.assertEqual(self.stop(), "")               # the third stop stands ...
        notice = self.notice()                           # ... as a question to the owner
        self.assertEqual(notice["kind"], "needs")
        self.assertEqual(notice["text"], "Stopped three times with work open: " + SAID)

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
        self.assertIsNone(self.notice())        # ... on the parked card, with no question of its own


if __name__ == "__main__":
    unittest.main(verbosity=2)
