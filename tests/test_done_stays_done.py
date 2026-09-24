"""A done session stays done when the owner opens it; only the seat declares itself done.

Opening a seat, reading it, scrolling it and its redraws leave the seat's own `ak notify done`
standing, and only a newer notice replaces it.  A job's `all N tasks finished` is not the
seat's word, and a question on the seat's screen, or typed text nobody sent, outranks a done.
Offline: fake captures, fake hook records, a sandboxed HOME and state directory.
"""

from contextlib import redirect_stdout
import io
import json
import os
import re
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, menu, notify, orch, run, terminal, watch, worker

NOW = 1_800_000_000
SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8", errors="replace")
DRAFT = (FIX / "claude-draft-pane.txt").read_text(encoding="utf-8", errors="replace")
# Claude's permission prompt has no capture (it needs a model): its hook is the authority
ASKING = "Bash(rm -rf build)\n\nDo you want to proceed?\n❯ 1. Yes\n  2. No\n"
SUMMARY = "Merged #75: the parser reads both schemas\n\nThe loop pushes and merges now."


class DoneStaysDone(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_ROLE": "orchestrator",
            notify.SINK_ENV: "dry-run", "AGENTKIT_DISCORD_WEBHOOK": "",
            config.SESSION_ENV: SEAT}))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        repo = str(config.CODE / "acme")
        self.seat = {"name": SEAT, "repo": repo, "path": repo, "created": NOW - 86400,
                     "attached": False, "exited": False, "legacy": False, "resumable": False}
        config.save_session(self.cfg, SEAT, "fable", ["opus"], {"repo": repo, "cwd": repo})
        self.pane = PROMPT
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))
        self.stack.enter_context(patch.object(orch, "listing", return_value=[self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text",
                                              side_effect=lambda *_a, **_k: self.pane))
        self.stack.enter_context(patch.object(worker, "auth_ok",
                                              side_effect=lambda h, seat=False: (True, h)))
        # Discord, faked: the title of every card posted, and every edit of one
        self.posts, self.edits = [], []

        def post(payload, files, message, receipt):
            self.posts.append(payload["embeds"][0]["title"])
            receipt.update(status="delivered", message_id=str(len(self.posts)), webhook="sink")

        def close_needs(previous, status):
            self.edits.extend((p["message_id"], status) for p in previous.get("open_needs", []))
            return []
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "close_needs", side_effect=close_needs))

    def fact(self, event, kind="", text=""):
        """What this seat's own lifecycle hook would have written."""
        config.hook_facts_path(SEAT).write_text(json.dumps(
            {"session": SEAT, "event": event, "kind": kind, "text": text, "at": NOW}))

    def decide(self):
        """Look at the seat the way a screen does, then decide from what was seen."""
        harness, live = watch.look_at(self.seat, cfg=self.cfg)
        found = watch.session_state(SEAT, NOW, session=self.seat, cfg=self.cfg,
                                    live=live, harness=harness)
        return found["word"], found["reason"]

    def open_and_redraw(self):
        """The owner opens the seat, and its pane changes under him: a redraw, a scroll."""
        notify.opened(SEAT, lambda: self.pane)
        self.pane = PROMPT + "\n  scrolled back through the summary"
        return notify.progress(SEAT, lambda: self.pane)

    def tick(self, later=0):
        """The watch tick's part in it, a moment after what came before: a look at the seat,
        then its card's transition."""
        with patch.object(menu.time, "time", return_value=menu.time.time() + 1 + later):
            watch.look_at(self.seat, cfg=self.cfg)
            notify.transition(SEAT, now=NOW + later, seat=self.seat)

    def row(self, width):
        """The seat's row on the menu, drawn at that many columns."""
        with patch.object(menu.time, "time", return_value=NOW), \
                patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=40), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, [self.seat])
        lines = [terminal.ANSI.sub("", line) for line in out.getvalue().splitlines()]
        first = next(n for n, line in enumerate(lines) if re.match(rf"\s*1\s+{SEAT}\b", line))
        return lines[first:first + 2]

    def test_opened_and_a_pane_change_leave_a_done_standing(self):
        notify.record(SEAT, "done", SUMMARY)
        self.fact("Stop")
        self.assertEqual(self.decide(), ("done", "Merged #75: the parser reads both schemas"))
        self.assertFalse(self.open_and_redraw())
        self.assertEqual(self.decide(), ("done", "Merged #75: the parser reads both schemas"))
        self.assertEqual(notify.last(SEAT)["text"], SUMMARY)
        # and more redraws, ticks later, answer nothing either
        for tail in ("  a redraw", "  another one"):
            self.pane = PROMPT + "\n" + tail
            self.assertFalse(notify.progress(SEAT, lambda: self.pane))
        self.assertEqual(self.decide()[0], "done")

    def test_the_record_the_owner_found_reads_done_on_the_next_draw(self):
        # 24 Sep: declared, opened, its pane redrew, and it read `needs you` since.  The
        # record as that left it, with no hand edit: done, opened, progress after the open.
        config.notify_path(SEAT).write_text(json.dumps(
            {"session": SEAT, "kind": "done", "text": SUMMARY, "time": NOW - 900,
             "opened_at": NOW - 600, "opened_pane": PROMPT, "last_progress_at": NOW - 300,
             "open_needs": []}) + "\n")
        self.fact("Stop")
        self.assertEqual(self.decide(), ("done", "Merged #75: the parser reads both schemas"))
        for width in (170, 40):
            with self.subTest(width=width):
                row = " ".join(self.row(width))
                self.assertIn("✓ done", row)
                self.assertIn("Merged #75", row)
                self.assertNotIn("needs you", row)

    def test_a_newer_needs_replaces_it(self):
        notify.record(SEAT, "done", SUMMARY)
        self.fact("Stop")
        self.open_and_redraw()
        notify.record(SEAT, "needs", "Which of the two schemas should it read?")
        self.assertEqual(self.decide(),
                         ("needs you", "Which of the two schemas should it read?"))

    def test_a_question_on_its_screen_and_a_draft_outrank_it(self):
        notify.record(SEAT, "done", SUMMARY)
        self.fact("Notification", kind="permission_prompt",
                  text="Claude needs your permission to use Bash")
        self.pane = ASKING
        self.assertEqual(self.decide(),
                         ("needs you", "Claude needs your permission to use Bash"))
        self.fact("Stop")
        self.pane = DRAFT
        word, reason = self.decide()
        self.assertEqual(word, "needs you")
        self.assertIn("Fix the login redirect", reason)
        # the question and the draft outranked the declaration without ending it
        self.pane = PROMPT
        self.assertEqual(self.decide()[0], "done")

    def test_a_question_card_over_a_done_stays_open_until_the_done_is_back(self):
        self.fact("Stop")
        self.assertEqual(notify.shaped("done", SUMMARY, session=SEAT), 0)
        self.assertEqual(self.posts, ["Done · fix-api"])
        self.open_and_redraw()
        self.fact("Notification", kind="permission_prompt",
                  text="Claude needs your permission to use Bash")
        self.pane = ASKING
        self.tick()
        self.tick(120)          # a minute of `needs you` with nobody attached
        self.assertEqual(self.posts, ["Done · fix-api", "Needs you · fix-api"])
        self.assertEqual(self.edits, [])    # the done from before answers nothing
        self.fact("Stop")
        self.pane = PROMPT
        self.tick(240)
        self.assertEqual(self.decide()[0], "done")
        # the question's card is finished, and the declaration, carded once, is not again
        self.assertEqual(self.edits, [("2", "Done")])
        self.assertEqual(self.posts, ["Done · fix-api", "Needs you · fix-api"])

    def test_a_jobs_all_finished_is_no_word_of_the_seats(self):
        self.fact("Stop")
        other = config.RUNS / "20260924-1250-fix-api"
        other.mkdir(parents=True)
        run.save_state(other, {"run_id": other.name, "state": "running",
                               "launched_session": SEAT, "title": "Another task"})
        text = "job 20260924-1300-acme: all 3 tasks finished"
        self.assertEqual(notify.shaped("done", text, session=SEAT,
                                       event_id="job:20260924-1300-acme:1800000000"), 0)
        self.assertEqual(notify.last(SEAT)["text"], text)
        # a run of its own still going holds the job's card back, as it always did
        self.assertEqual(self.decide()[0], "working")
        self.assertEqual(self.posts, [])
        run.save_state(other, {**run.read_state(other), "state": "pass",
                               "finished_at": NOW - 60})
        self.assertEqual(self.decide(), ("needs you", "waiting for you"))
        # its card is the green one it always was, once, and no question card follows it
        self.tick()
        self.tick(600)
        self.assertEqual(self.posts, ["Done · fix-api"])
        # a question on its screen is still the reason, never the job's line
        self.fact("Notification", kind="permission_prompt",
                  text="Claude needs your permission to use Bash")
        self.pane = ASKING
        self.assertEqual(self.decide(),
                         ("needs you", "Claude needs your permission to use Bash"))
        # and the seat's own declaration after it is done
        self.fact("Stop")
        self.pane = PROMPT
        notify.record(SEAT, "done", SUMMARY)
        self.assertEqual(self.decide()[0], "done")

    def test_a_needs_still_resolves_on_open_and_fresh_output(self):
        notify.record(SEAT, "needs", "Merge PR #7? yes/no")
        self.fact("Stop")
        self.assertEqual(self.decide(), ("needs you", "Merge PR #7? yes/no"))
        notify.opened(SEAT, lambda: self.pane)
        self.assertFalse(notify.progress(SEAT, lambda: self.pane))   # the open alone: no answer
        self.assertEqual(self.decide(), ("needs you", "Merge PR #7? yes/no"))
        self.assertTrue(notify.progress(SEAT, lambda: "Merging the approved patch"))
        self.assertIsNone(notify.last(SEAT))
        self.assertEqual(self.decide(), ("needs you", "waiting for you"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
