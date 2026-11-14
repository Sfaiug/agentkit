"""A line ak typed earlier, back whole in a seat's composer, is ak's to send only while it went
into the conversation the seat holds now: read again under the send lock, as the seat may move
to another while that lock is awaited, and never where its harness names no conversation yet,
whose receipts from two launches look alike.  Either way it reads as the owner's unsent text and
gets no Enter.  fixtures.seats' throwaway seat, its pane and tmux faked.
"""

from contextlib import contextmanager
import json
import unittest
from unittest.mock import patch

from fixtures.seats import REPO, SEAT, Seats
from agentkit import config, harness, notify, watch

OLDER = "run 20261113-0915-fix-api is live: https://github.com/acme/api/pull/42."
NEWER = "run 20261114-0840-fix-docs ended PASS, merged; your wait is over."


class OwnLineIsTheCurrentConversations(Seats):
    def setUp(self):
        super().setUp()
        self.enters = []

    def tmux(self, *args, **kwargs):
        if args[0] == "send-keys" and args[-1] == "Enter":
            self.enters.append(config.session_records()[SEAT].get("conversation"))
        return super().tmux(*args, **kwargs)

    def receipts(self, *rows):
        config.seat_file("input", SEAT).write_text("".join(json.dumps(row) + "\n" for row in rows))

    def unsent(self, model):
        found = watch.live_state(self.seat, model, pane=self.pane, cfg=self.cfg)
        self.assertEqual(found.get("state"), "draft")
        return watch.unsent(SEAT, model, found, self.seat, self.cfg)

    def test_a_conversation_left_while_the_lock_is_awaited_gets_no_enter(self):
        plugin, record = harness.load("claude"), config.session_records()[SEAT]
        self.receipts(*(plugin.receipt(record, "thread", text) for text in (OLDER, NEWER)))
        self.pane = self.base.replace(self.empty, "❯ " + OLDER + "\n")
        self.assertEqual(self.unsent("claude"), "")
        locking = notify.session_lock

        @contextmanager
        def moving_on(name):
            with locking(name) as held:
                config.update_session(held, conversation="thread-next")
            with locking(name) as held:
                yield held

        with patch.object(notify, "session_lock", moving_on):
            watch.finish_own_lines(self.cfg, lambda _: None)
        self.assertEqual(self.enters, [])
        self.assertEqual(self.unsent("claude"), OLDER)

    def test_receipts_of_launches_naming_no_conversation_prove_no_line(self):
        self.cfg["models"]["opus"]["harness"] = "codex"
        config.save(self.cfg)
        config.update_session(SEAT, conversation=None, codex_launch="b" * 32)
        plugin, record = harness.load("codex"), config.session_records()[SEAT]
        self.receipts(plugin.receipt(dict(record, codex_launch="a" * 32), None, OLDER),
                      plugin.receipt(record, None, NEWER))
        self.pane = (REPO / "tests/fixtures/codex-prompt-pane.txt").read_text().replace(
            "› Ask Codex to do anything\n", "› " + OLDER + "\n")
        self.assertEqual(self.unsent("codex"), OLDER)
        watch.finish_own_lines(self.cfg, lambda _: None)
        self.assertEqual(self.enters, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
