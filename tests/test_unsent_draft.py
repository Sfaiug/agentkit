"""The owner's unsent text reads needs you, even while the seat's runs go.

On 25 Sep three seats read `working` for up to nineteen hours over text the owner had typed
and never sent, because a seat's going runs sat above its draft on the ladder.  Typed text
nobody sent, or a question on its screen, at a quiet prompt is him whatever its runs are
doing, with the reason `unsent: <text>` -- except while a client is attached to the seat,
where the draft is his typing, and never mid-turn, where the composer is the turn's.
Offline: fake captures, fake hook records, a fake tmux that answers the attached-client
question, and a sandboxed HOME.
"""

from contextlib import redirect_stdout
import io
import json
import os
import re
import shutil
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, menu, notify, orch, run, terminal, watch, worker

NOW = 1_800_000_000
SEAT = "fix-api"
FIX = REPO / "tests/fixtures"


def capture(name):
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


PROMPT = capture("claude-prompt-pane.txt")
DRAFT = capture("claude-draft-pane.txt")
TEXT = "Fix the login redirect"        # what sits typed in the draft capture's composer
# Claude's permission prompt has no capture (it needs a model): its hook is the authority
ASKING = "Bash(rm -rf build)\n\nDo you want to proceed?\n❯ 1. Yes\n  2. No\n"
BASH = "Claude needs your permission to use Bash"
RUNS = "2 running · Parked on a window"


class UnsentDraft(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_ROLE": "orchestrator",
            notify.SINK_ENV: "dry-run", "AGENTKIT_DISCORD_WEBHOOK": "",
            config.SESSION_ENV: SEAT}))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "acme")
        config.save_session(self.cfg, SEAT, "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        self.attached = False       # is a tmux client on the seat
        self.pane = DRAFT
        listed = lambda *_a, **_k: [self.seat]
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=listed))
        self.stack.enter_context(patch.object(orch, "listing", side_effect=listed))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text",
                                              side_effect=lambda *_a, **_k: self.pane))
        self.stack.enter_context(patch.object(worker, "auth_ok",
                                              side_effect=lambda h, seat=False: (True, h)))
        # Discord, faked: the title of every card it took, and every edit of one
        self.posts, self.edits = [], []

        def post(payload, files, message, receipt):
            self.posts.append(payload["embeds"][0]["title"])
            receipt.update(status="delivered", message_id=str(len(self.posts)), webhook="sink")

        def close_needs(previous, status):
            self.edits.extend((p["message_id"], status) for p in previous.get("open_needs", []))
            return []
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "close_needs", side_effect=close_needs))

    @property
    def seat(self):
        """The seat as the listing offers it: `attached` is tmux's own `session_attached`."""
        return {"name": SEAT, "repo": self.repo, "path": self.repo, "created": NOW - 86400,
                "attached": self.attached, "exited": False, "legacy": False,
                "resumable": False}

    def tmux(self, *args, **kwargs):
        """The fake server; the one question asked of it is whether a client is on the seat."""
        if args[0] == "list-clients":
            return 0, f"/dev/pts/3: {SEAT} [170x40 xterm-256color] (utf8)\n" if self.attached else ""
        return 0, ""

    def fact(self, event, kind="", text="", at=NOW):
        """What this seat's own lifecycle hook would have written."""
        config.hook_facts_path(SEAT).write_text(json.dumps(
            {"session": SEAT, "event": event, "kind": kind, "text": text, "at": at}))

    def receipt(self, name, **extra):
        """A run of this seat's own, going, as `ak run` leaves its record."""
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        run.save_state(directory, {
            "run_id": name, "title": f"Task {name}", "state": "running",
            "launched_session": SEAT, "reported": False, "repo": self.repo,
            "executor": "opus", "reviewer": "astra", "rounds": 2, "round_summaries": [],
            "finished_at": None, "started_at": NOW - 3600, **extra})
        for path in list(directory.rglob("*")) + [directory]:
            os.utime(path, (NOW, NOW))

    def going(self):
        """Two runs of its own going: one running, one parked on a window it resumes from."""
        self.receipt("20260101-0900-schema", title="Read both schemas", started_at=NOW - 900)
        self.receipt("20260101-1000-window", state="exhausted", title="Parked on a window",
                     started_at=NOW - 600)

    def decide(self):
        """Look at the seat the way a screen does, then decide from what was seen."""
        harness, live = watch.look_at(self.seat, cfg=self.cfg)
        found = watch.session_state(SEAT, NOW, session=self.seat, cfg=self.cfg,
                                    live=live, harness=harness)
        return found["word"], found["reason"]

    def tick(self, later=0):
        """The watch tick's part in it: a look at the seat, then its card's transition."""
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

    def test_a_draft_at_a_quiet_prompt_with_two_going_runs_is_needs_you_unsent(self):
        self.going()
        self.fact("Stop")
        self.assertEqual(self.decide(), ("needs you", f"unsent: {TEXT}"))
        # ... and the row says it at any width, the runs never
        for width in (170, 40):
            with self.subTest(width=width):
                row = " ".join(self.row(width))
                self.assertIn("! needs you", row)
                self.assertNotIn("running", row)
        self.assertIn(f"unsent: {TEXT}", " ".join(self.row(170)))
        # the same seat with its text sent is its runs' again
        self.pane = PROMPT
        self.assertEqual(self.decide(), ("working", RUNS))

    def test_b_a_question_on_its_screen_with_going_runs_is_needs_you(self):
        self.going()
        self.fact("Notification", kind="permission_prompt", text=BASH)
        self.pane = ASKING
        self.assertEqual(self.decide(), ("needs you", BASH))
        # ... and one only the screen shows, on a harness whose screen is the authority
        config.hook_facts_path(SEAT).unlink()
        with patch.object(watch, "seat_model", return_value=("codex", "openai")):
            self.pane = capture("codex-dialog-pane.txt")
            word, reason = self.decide()
        self.assertEqual(word, "needs you")
        self.assertNotIn("running", reason)

    def test_c_an_attached_client_keeps_it_working_and_sends_no_card(self):
        self.going()
        self.fact("Stop")
        self.attached = True
        self.assertEqual(self.decide(), ("working", RUNS))
        self.tick()
        self.tick(120)
        self.assertEqual(self.posts, [])
        # He leaves it sitting there: it is his to send, and the existing card and its
        # hold say so, once
        self.attached = False
        self.assertEqual(self.decide(), ("needs you", f"unsent: {TEXT}"))
        self.tick(240)
        self.assertEqual(self.posts, [])            # a minute of `needs you` first
        self.tick(360)
        self.assertEqual(self.posts, [f"Needs you · {SEAT}"])
        self.tick(480)
        self.assertEqual(self.posts, [f"Needs you · {SEAT}"])
        # Back in the seat it is his typing again: the runs' word, and the card answered
        self.attached = True
        self.assertEqual(self.decide(), ("working", RUNS))
        self.tick(600)
        self.assertEqual(self.edits, [("1", "Answered")])
        self.assertEqual(self.posts, [f"Needs you · {SEAT}"])

    def test_c2_a_question_is_his_wherever_he_is_and_no_card_goes_while_he_is_in(self):
        # A question on the screen is not his typing: a client left attached to the seat
        # never turns it into `working`, and the card rule alone holds the card while he is in
        self.going()
        self.fact("Notification", kind="permission_prompt", text=BASH)
        self.pane = ASKING
        self.attached = True
        self.assertEqual(self.decide(), ("needs you", BASH))
        self.tick()
        self.tick(120)
        self.assertEqual(self.posts, [])

    def test_d_a_draft_mid_turn_stays_working(self):
        # The composer is the turn's while it runs: Claude's hook says so, and no draft rule
        # talks the row out of it -- with runs going, and without
        self.going()
        self.fact("UserPromptSubmit", at=NOW - 60)
        self.assertEqual(self.decide(), ("working", RUNS))
        for name in ("20260101-0900-schema", "20260101-1000-window"):
            shutil.rmtree(config.RUNS / name)
        self.assertEqual(self.decide(), ("working", ""))

    def test_e_an_empty_composer_with_going_runs_stays_working(self):
        self.going()
        self.fact("Stop")
        self.pane = PROMPT
        self.assertEqual(self.decide(), ("working", RUNS))
        # a suggestion the harness drew in faint text is nobody's draft either
        self.pane = capture("claude-suggestion-pane.txt")
        self.assertEqual(self.decide(), ("working", RUNS))

    def test_f_a_seat_nobody_is_in_is_never_read_by_its_last_draft(self):
        # The draft is written down in the seat's record; once nobody is in the seat that
        # record is history, and the seat reads by its runs, as it always did
        self.going()
        self.fact("Stop")
        self.assertEqual(self.decide()[0], "needs you")
        gone = dict(self.seat, exited=True)
        with patch.object(orch, "listing", return_value=[gone]):
            found = watch.session_state(SEAT, NOW, session=gone, cfg=self.cfg)
        self.assertEqual((found["word"], found["reason"]), ("working", RUNS))


if __name__ == "__main__":
    unittest.main()
