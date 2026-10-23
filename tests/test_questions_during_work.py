"""A question the owner has not answered waits through the seat's independent work.

A seat stopped on a question: `needs you`, and one card.  A run's result opens a turn: the
seat works without him, so it reads `working`, and a newer question it asks then waits beside
the first for that turn's stop.  The stop reads `needs you` with both, though a run of its own
goes on, and pages nobody again: the same question still stands.  A blocking card the harness
draws meanwhile pauses the seat at once.  Every registered harness, through the look, the
ladder and the card pass, its hooks' facts and its screens its own fixtures; a sandbox HOME, a
fixed clock, tmux and Discord faked.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, notify, orch, record, watch

SEAT = "fix-api"
FIRST = "Which schema should acme use? The parser reads both; v2 drops the legacy fields."
SECOND = "Ship v2 to acme today? The parser needs the schema first."
CARD = "🙋 Needs you · " + SEAT
FIXTURE = {"grokbuild": "grok"}     # its screen captures predate its name


class QuestionsDuringWork(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        self.posts, self.harness, self.now = [], None, 10000

        def post(payload, files, message, receipt):
            self.posts.append(payload["content"])
            receipt.update(status="disabled", message_id=str(len(self.posts)), webhook="sink")
            return 0
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_SESSION": SEAT, "AGENTKIT_DISCORD_WEBHOOK": "off", "AK_NOTIFY_SINK": "off",
            "AK_RUN_ROLE": ""}))
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(orch, "listing", return_value=[
            {"name": SEAT, "attached": False}]))
        self.stack.enter_context(patch.object(
            watch, "seat_model", side_effect=lambda *_a, **_k: (self.harness, "acme")))

    def fact(self, state, mark=None):
        """What the harness's own hooks write down for `state`: the event its manifest marks
        `mark`, else one with no kinds, a blocking card's being the first; {} where none does."""
        for event in (config.manifest(self.harness).get("hooks") or {}).get("event") or ():
            kinds = event.get("kinds") or [""]
            if event["state"] == state and (event.get(mark) if mark
                                            else state == "asking" or kinds == [""]):
                return {"session": SEAT, "event": event["name"], "kind": kinds[0], "text": "",
                        "at": self.now}
        return {}

    def clock(self, after):
        self.now += after
        return patch.object(watch.time, "time", return_value=self.now)

    def asks(self, question):
        """The seat's own `ak notify needs`, during a turn."""
        with self.clock(1):
            self.assertEqual(notify.main(["needs", question]), 0)

    def looked(self, screen, fact):
        """The seat as every screen reads it after a fresh look: its word and reason."""
        pane = (REPO / "tests/fixtures" /
                f"{FIXTURE.get(self.harness, self.harness)}-{screen}-pane.txt").read_text()
        with self.clock(10), patch.object(watch, "hook_facts", return_value=fact), \
                patch.object(watch, "pane_text", return_value=pane):
            answer = watch.announce_state({"name": SEAT, "attached": False}, cfg=self.cfg,
                                          look=True, auth_out={}, gh_out={}, token_out={})
        return answer["word"], answer["reason"]

    def carded(self):
        """The cards sent once the tick's card pass has run past a card's wait."""
        with self.clock(notify.CARD_WAIT):
            notify.transition(SEAT, now=self.now, seat={"name": SEAT, "attached": False})
        return self.posts

    def test_every_harness_holds_its_question_through_independent_work(self):
        for harness, _manifest in config.manifests():
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.asks(FIRST)
                self.assertEqual(self.looked("working", self.fact("working"))[0], "working")
                self.assertEqual(self.looked("prompt", self.fact("at_prompt")),
                                 ("needs you", FIRST))
                self.assertEqual(self.carded(), [CARD])
                # a run of its own goes on, and its result opens a turn that works without him
                (config.RUNS / "acme-parser").mkdir(parents=True)
                record.save_state(config.RUNS / "acme-parser", {
                    "run_id": "acme-parser", "state": "running", "launched_session": SEAT,
                    "started_at": self.now, "finished_at": None})
                self.assertEqual(self.looked("working", self.fact("working"))[0], "working")
                self.asks(SECOND)
                self.assertEqual(self.looked("working", self.fact("working"))[0], "working")
                self.assertEqual(self.carded(), [CARD])
                self.assertEqual(notify.last(SEAT)["text"], FIRST)    # nothing answered it
                # a blocking card is a pause, at once; its turn then runs on
                self.assertEqual(self.looked("dialog", self.fact("asking"))[0], "needs you")
                self.assertEqual(self.looked("working", self.fact("working"))[0], "working")
                # its stop asks both, on background work as on none, and pages nobody again
                stop = self.fact("working", "background") or self.fact("at_prompt")
                self.assertEqual(self.looked("prompt", stop),
                                 ("needs you", FIRST + " Also: " + SECOND))
                self.assertEqual(self.carded(), [CARD])
                self.assertIsNone(watch.seat_read(SEAT).get("unasked"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
