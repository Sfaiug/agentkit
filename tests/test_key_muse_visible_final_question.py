"""A Muse question logged after the final message its chat shows goes back until a turn shows it.

Muse 1.4.12's chat shows a run's first final answer and none after it: a turn that closed on
`Ready` and then, asked by Muse's own end-of-turn reminder, logged the question in the same
run left the owner nothing to answer.  That seat reads `working` and is sent ak's reminder;
`needs you` begins once a later run's shown final holds the question, a commentary before it
no final, and the owner's answer clears it.  Black-box: `AK_BIN` through
tests/fixtures/akbin.py, before a seat of tests/fixtures/akseat.py whose hooks fire as Muse
fires them, its conversation in Muse's own store.
"""

import json
import sys
import time
import uuid
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, hookdrive
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, Seat

QUESTION = "Which colour should the acme preview use? Options: Blue (Recommended) · Green"
SHOWN = "Which colour should the acme preview use?\n\n- Blue (Recommended)\n- Green"
TOKEN = "0" * 32


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class MuseVisibleFinalQuestion(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "spark"])
        home.write(f".agentkit/state/muse-launch-{TOKEN}/session", "muse-acme")
        self.seat = Seat(home, "muse", model="spark", composer="❯",
                         screen="muse-working-pane.txt", record={"muse_launch": TOKEN})
        self.log = home.path / ".local/share/muse/sessions/2026/10/26/muse-acme/session.jsonl"
        self.log.parent.mkdir(parents=True)
        self.prompt("Build the acme preview.")
        done = home.ak("notify", "needs", QUESTION, env={"AGENTKIT_SESSION": "muse"})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(home.tick().code, 0)

    def prompt(self, text):
        """Muse opens a run on `text`: the run's events go under one run id, as 1.4.12's do."""
        self.run = uuid.uuid4().hex
        self.logs({"kind": "started", "prompt": text})
        self.hook("UserPromptSubmit", prompt=text)

    def logs(self, *events):
        with self.log.open("a") as fh:
            for event in events:
                payload = {"kind": "run", "run_id": self.run, "event": event}
                fh.write(json.dumps({"schema_version": 1, "record_type": "event",
                                     "stream": {"kind": "session", "id": "muse-acme"},
                                     "recorded_at": round(time.time() * 1e6),
                                     "payload": payload}) + "\n")

    def hook(self, event, **payload):
        done = self.home.run("bash", str(hookdrive.ROOT / "adapters/muse.sh"), "hook",
                             env={"AGENTKIT_SESSION": "muse"},
                             input=json.dumps({"hook_event_name": event, **payload}))
        self.assertEqual(done.code, 0, done.err)

    def stop(self, shown):
        """The turn stops, its chat showing `shown` above the empty composer."""
        screen = (FIXTURES / "muse-prompt-pane.txt").read_text().replace(
            "\n", f"{' ' * 320}\n" + "".join(f"  {line}\n" for line in shown.split("\n")), 1)
        rows = screen.split("\n")
        at = max(row for row, text in enumerate(rows) if text.lstrip().startswith("❯"))
        cursor = f"\x1b[{at + 1};{rows[at].index('❯') + 3}H"
        self.seat.show(f"{screen.removesuffix(chr(10))}{cursor}\n")
        self.hook("Stop", background_tasks=[])
        self.assertEqual(self.home.tick().code, 0)

    def reads(self, word, lines):
        done = self.home.ak("orch", "why", "muse")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out.splitlines()[0], f"muse  {word}", done.out)
        self.assertEqual(len(self.seat.lines()), lines, self.seat.lines())
        self.assertTrue(all(QUESTION in line for line in self.seat.lines()), self.seat.lines())

    def test_a_question_after_the_shown_final_goes_back_until_a_turn_shows_it(self):
        self.logs(
            {"kind": "assistant_message_committed", "phase": "commentary",
             "text": "Sending the notification."},
            {"kind": "assistant_message_committed", "message_id": "acme-first", "text": "Ready"},
            {"kind": "reminder_reconciler_outcome", "outcome": "accepted",
             "reason": "within_budget"},
            {"kind": "assistant_message_committed", "message_id": "acme-later", "text": SHOWN},
            {"kind": "terminal", "terminal": "completed"})
        self.stop("Ready")
        self.reads("working", 1)                # the later final is logged, never shown

        self.prompt(self.seat.lines()[-1])
        self.logs(
            {"kind": "assistant_message_committed", "phase": "commentary",
             "text": "Repeating the question."},
            {"kind": "assistant_message_committed", "message_id": "acme-next", "text": SHOWN},
            {"kind": "terminal", "terminal": "completed"})
        self.stop(SHOWN)
        self.reads("needs you", 1)

        self.prompt("Blue.")
        self.logs({"kind": "assistant_message_committed", "text": "Using blue."},
                  {"kind": "terminal", "terminal": "completed"})
        self.stop("Using blue.")
        self.reads("idle", 1)                   # the owner's answer cleared it


if __name__ == "__main__":
    unittest.main()
