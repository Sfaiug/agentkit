"""The stop hook's stuck question lasts only while the seat has no ending of its own.

Real hook input and notification records, in a temporary HOME; no seats or delivery.
"""

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
from fixtures.merged_run import MergedRuns, SEAT
from agentkit import config, notify, watch

SAID = "The parser still has work open."
OWN = "Which schema should acme use?"
LINE = "- [ ] the parser parses · check: `false` · acme · written 2026-10-09 12:00\n"


class StuckQuestionGoesWithItsCause(MergedRuns):
    def setUp(self):
        super().setUp()
        for name in ("HOME", "STATE", "RUNS", "WT", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            path = self.home / ".agentkit" if name == "HOME" else self.home / ".agentkit" / name.lower()
            self.enterContext(patch.object(config, name, path))
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.home),
                    "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator",
                    "AK_NOTIFY_SINK": "off", "IDLE_COMPACT_STATE": ""}
        self.enterContext(patch.dict(os.environ, {"AK_NOTIFY_SINK": "off"}))
        config.plan_path(SEAT).write_text(LINE)

    def hook(self, event, script="seat-state.sh", **payload):
        done = subprocess.run(["bash", str(REPO / "hooks" / script)], text=True,
                              capture_output=True, timeout=30, env=self.env,
                              input=json.dumps({"hook_event_name": event, **payload}))
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def prompt(self):
        self.assertEqual(self.hook("UserPromptSubmit", prompt="Run acme-parser finished."), "")

    def stop(self, said=SAID, **payload):
        return self.hook("Stop", "orchestrator-stop.sh",
                         last_assistant_message=said, **payload)

    def look(self):
        with notify.session_lock(SEAT) as name:
            notify.ask_kept(name, ended=True)

    def stuck(self, *, publish=True):
        self.prompt()
        for _ in range(2):
            self.assertEqual(json.loads(self.stop())["decision"], "block")
        self.assertEqual(self.stop(), "")
        kept = watch.questions_kept(watch.seat_read(SEAT).get("unasked"))
        self.assertEqual(len(kept), 1)
        self.assertIn("How should this seat go on?", kept[0]["text"])
        self.assertTrue(kept[0]["text"].endswith(SAID))
        if publish:
            self.look()
            self.assertEqual(notify.last(SEAT)["text"], kept[0]["text"])
        return kept[0]["text"]

    def pending_card(self):
        notice = notify.last(SEAT)
        card = {"word": "needs you", "since": notice["time"], "began": notice["time"],
                "episode": "acme-stuck", "sent": True}
        notify._card_write(SEAT, card)
        with notify.outbox_lock():
            notify._write_event({"id": notify._card_key(card["episode"]), "status": "pending",
                                 "next_attempt": notice["time"] + 60})
        return card

    def assert_retired(self, card):
        self.assertIsNone(notify.last(SEAT))
        self.assertIsNone(watch.seat_read(SEAT).get("unasked"))
        self.assertGreater(notify._card_read(SEAT)["answered_at"], card["since"])
        self.assertEqual(notify._read_event(notify._card_key(card["episode"]))["status"], "disabled")

    def test_a_later_ak_wait_on_its_going_run_retires_the_question_and_card(self):
        self.stuck()
        card = self.pending_card()
        self.prompt()
        directory = self.runs / "acme-parser"
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps({
            "run_id": directory.name, "launched_session": SEAT, "state": "running",
            "started_at": time.time() - 600}))
        done = subprocess.run([sys.executable, str(REPO / "bin/ak"), "wait", directory.name],
                              env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        wait = watch.seat_read(SEAT)["wait"]
        self.assertEqual(self.stop(), "")
        self.assert_retired(card)
        self.assertEqual(watch.seat_read(SEAT)["wait"], wait)

    def test_a_plan_with_its_last_line_ticked_retires_the_question_and_card(self):
        self.stuck()
        card = self.pending_card()
        self.prompt()
        config.plan_path(SEAT).write_text(LINE.replace("[ ]", "[x]").replace(
            "`false`", "`true`").rstrip() + " · done abcdef123\n")
        self.assertEqual(self.stop(), "")
        self.assert_retired(card)

    def test_a_merged_run_not_yet_live_retires_the_question(self):
        self.stuck()
        self.prompt()
        self.merged("acme-parser", health=True, live=False)
        self.assertEqual(self.stop(), "")
        self.assertIsNone(notify.last(SEAT))

    def test_a_wait_in_the_harness_retires_the_question(self):
        self.stuck()
        self.prompt()
        self.assertEqual(self.stop(background_tasks=[{"type": "subagent", "id": "acme"}]), "")
        self.assertIsNone(notify.last(SEAT))

    def test_its_next_question_is_asked_alone_and_the_old_card_is_retired(self):
        self.stuck()
        card = self.pending_card()
        self.prompt()
        self.hook("PreToolUse", "orchestrator-stop.sh", tool_name="AskUserQuestion",
                  tool_input={"questions": [{"question": OWN}]})
        self.assertEqual(self.stop(OWN), "")
        self.assertIsNone(notify.last(SEAT))
        self.assertEqual([q["text"] for q in watch.questions_kept(
            watch.seat_read(SEAT).get("unasked"))], [OWN])
        self.look()
        self.assertEqual(notify.questions(notify.last(SEAT)), [OWN])
        self.assertGreater(notify._card_read(SEAT)["answered_at"], card["since"])

    def test_another_standing_question_keeps_its_words_and_dates(self):
        self.stuck()
        self.prompt()
        with notify.session_lock(SEAT):
            notify._said(SEAT, "needs", OWN, question_ids={notify.question_key(OWN): "acme-card"})
        before = notify.last(SEAT)
        self.assertEqual(self.stop(OWN), "")
        after = notify.last(SEAT)
        self.assertEqual(notify.questions(after), [OWN])
        for field in ("asked_at", "question_times", "question_ids"):
            self.assertEqual(after[field], {notify.question_key(OWN): before[field][notify.question_key(OWN)]})

    def test_a_kept_copy_goes_and_every_other_kept_question_stays(self):
        text = self.stuck(publish=False)
        self.prompt()
        notify.keep_back(SEAT, OWN, question_id="acme-card")
        notify.keep_back(SEAT, text)
        self.assertEqual(self.stop(OWN), "")
        kept = watch.questions_kept(watch.seat_read(SEAT).get("unasked"))
        self.assertEqual([(q["text"], q["id"]) for q in kept], [(OWN, "acme-card")])
        self.assertIsNone(notify.last(SEAT))
        self.look()
        self.assertEqual(notify.questions(notify.last(SEAT)), [OWN])

    def test_a_still_stuck_turn_stands_at_its_first_stop_unchanged(self):
        self.stuck()
        self.pending_card()
        notice = config.notify_path(SEAT).read_bytes()
        card = config.card_path(SEAT).read_bytes()
        self.prompt()
        for _ in range(3):
            self.assertEqual(self.stop(), "")
            self.assertEqual(config.notify_path(SEAT).read_bytes(), notice)
            self.assertEqual(config.card_path(SEAT).read_bytes(), card)
            self.assertIsNone(watch.seat_read(SEAT).get("unasked"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
