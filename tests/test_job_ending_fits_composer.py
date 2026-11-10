"""A job's ending reaches its seat however long its task's reason is.  Offline.

A blocked reason runs past what a composer shows whole (`watch.too_long`): the seat is handed
the line cut at a word, naming the job, the task, BLOCKED and a file holding the whole of it,
whether the job's own loop built the line or the tick reads it back off an older record; and a
line `watch.too_long` refuses wakes no seat.  The seat is faked as `test_handback` fakes it: no
tmux, its screen what the classifier is told, the confirmed send keeping what it was given.
"""

from contextlib import nullcontext, redirect_stdout
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, job as jobs, notify, orch, watch

SEAT = "seat-acme"
REASON = ("The done-when command reads fixtures/api.json, which the task never names, so no "
          "change can make it pass; " * 20)[:1899] + "."


class JobEndingFitsComposer(Sandbox):
    def setUp(self):
        super().setUp()
        self.screen, self.typed, self.cards, self.logs = "at_prompt", [], [], []
        seat = {"name": SEAT, "path": str(self.root), "created": 1, "attached": False,
                "exited": False, "legacy": False, "resumable": False}
        for target, name, fake in (
                (orch, "sessions", lambda: [dict(seat)]),
                (orch, "listing", lambda *a, **k: [dict(seat)]),
                (orch, "tmux_out", AssertionError("tmux was called")),
                (watch, "_editor_kept", lambda *a: {}),
                (watch, "pinned", lambda session: session),
                (watch, "seat_model", lambda *a: ("claude", "anthropic")),
                (watch, "live_state", lambda *a, **k: {
                    "state": self.screen, "rule": "prompt.composer", "authority": "screen",
                    "evidence": "", "began": 9000, "since": 9000, "hooked": None,
                    "hooked_event": None}),
                (watch, "pane_text", lambda *a, **k: "❯\n"),
                (watch, "type_checked", self.send),
                (watch, "pane_unread", lambda *a: False),
                (watch.time, "sleep", lambda _s: None),
                (notify, "shaped", lambda kind, text, **k: self.cards.append(text) or 0)):
            self.stack.enter_context(patch.object(target, name, side_effect=fake))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        config.save_session(self.cfg, SEAT, "fable", ["astra"],
                            {"cwd": str(self.root), "created": 100,
                             "conversation": "thread-seat", "id_source": orch.LAUNCHER})
        self.job_dir = config.JOBS / "job-acme"
        self.job_dir.mkdir(parents=True)

    def send(self, session, text, log, harness=None, guard=nullcontext,
             veto=lambda _name: False, typed=lambda: None, **_kw):
        """The confirmed send, minus tmux: the real lock is taken and the real veto read."""
        with guard() as held:
            if veto(held if held is not None else session["name"]):
                return False
        typed()
        self.typed.append(text)
        return True

    def assert_fits(self, line, reason):
        """`line` is one a composer shows whole, cut at a word of `reason` and naming the file
        that holds all of it."""
        self.assertIsNone(watch.too_long(line))
        head = "job job-acme: b.md: BLOCKED: "
        self.assertTrue(line.startswith(head), line)
        said, _, rest = line.removeprefix(head).partition("… Result: ")
        self.assertTrue(rest.endswith(". Decide the next step."), line)
        self.assertTrue(reason.startswith(said) and reason[len(said)] == " ", said)
        whole = Path(os.path.expanduser(rest.removesuffix(". Decide the next step.")))
        self.assertIn(reason, whole.read_text())

    def test_an_ordered_job_blocked_with_a_long_reason_hands_its_seat_a_line_that_fits(self):
        self.assertEqual(len(REASON), 1900)
        blocked = {"name": "b.md", "state": "blocked", "after": []}
        blocked["verdict_line"] = jobs.job_verdict_line(blocked, {"error": REASON})
        tasks = [{"name": "a.md", "state": "merged", "after": [], "verdict_line": "a.md: PASS"},
                 blocked, {"name": "c.md", "state": "skipped", "after": []}]
        jobs.run_job_loop({}, self.job_dir, {"job_id": "job-acme", "seat": SEAT,
                                             "opts": {"--in-order": True}, "tasks": tasks})
        self.assertEqual(len(self.typed), 1, self.typed)
        self.assert_fits(self.typed[0], REASON)
        self.assertEqual(jobs.read_job(self.job_dir)["card_sent"]["kind"], "handback")
        self.assertEqual(self.cards, [])

    def test_a_record_holding_a_line_too_long_is_delivered_at_the_next_quiet_prompt(self):
        head = "job job-acme: b.md: BLOCKED: "
        tail = f". Result: {self.job_dir / 'log.txt'}. Decide the next step."
        reason = REASON[:1400 - len(head) - len(tail)]
        line = head + reason + tail
        self.assertEqual(len(line), 1400)
        jobs.save_job(self.job_dir, {"job_id": "job-acme", "seat": SEAT, "tasks": [],
                                     "finished_at": 9990, "handback_pending": line,
                                     "handback_card": "job job-acme: b.md: BLOCKED"})
        self.screen = "working"
        jobs.deliver_job_handbacks(self.logs.append)
        self.assertEqual(self.typed, [])
        self.assertEqual(jobs.read_job(self.job_dir)["handback_pending"], line)
        self.screen = "at_prompt"
        jobs.deliver_job_handbacks(self.logs.append)
        self.assertEqual(len(self.typed), 1, self.logs)
        self.assert_fits(self.typed[0], reason)
        self.assertNotIn("handback_pending", jobs.read_job(self.job_dir))
        jobs.deliver_job_handbacks(self.logs.append)
        self.assertEqual((len(self.typed), self.cards), (1, []))

    def test_an_asleep_seat_is_not_woken_for_a_line_too_long_to_type(self):
        config.update_session(SEAT, launched=1, asleep=2)
        line = f"job job-acme: b.md: BLOCKED: {REASON}. Result: x. Decide the next step."
        with patch.object(orch, "resume") as resume:
            self.assertEqual(jobs.job_hand_back(SEAT, line, self.logs.append), "busy")
            resume.assert_not_called()
            # the same ending cut to fit is what wakes it
            self.assertEqual(jobs.job_hand_back(SEAT, jobs.seat_line(self.job_dir, line),
                                                self.logs.append), "sent")
            resume.assert_called_once()
        self.assertEqual(len(self.typed), 1)


if __name__ == "__main__":
    unittest.main()
