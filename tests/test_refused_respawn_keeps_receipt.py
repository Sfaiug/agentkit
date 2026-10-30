"""A launch whose harness never starts, refused by tmux or failing before it asks, leaves the
running harness on the launch receipt it was started with: the record still reads its
conversation from that receipt, and the receipt the failed launch wrote is gone. A respawn that
starts drops the receipt it replaced, and keeps its own though the setup after it fails.

Offline: a temporary HOME and an invented seat, with tmux and the adapters faked; the
receipts are real files in that HOME, and no real seat, process or transcript is touched.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, orch, statusbar, watch
from agentkit.harness import codex, opencode

SEAT = "acme-fix"


class RefusedRespawn(Sandbox):
    def setUp(self):
        super().setUp()
        self.refused, self.pane = "refused", ""
        seat = {"name": SEAT, "path": str(self.root), "exited": False, "legacy": False}

        def tmux(*args, **_kw):
            if args[0] == "capture-pane":
                return 0, self.pane
            if args[0] == "respawn-pane" and self.refused:
                return 1, self.refused
            return 0, ""

        for name, fake in (("_switch_plan", lambda *_a, **_kw: ("", None)),
                           ("find", lambda *_a, **_kw: seat),
                           ("command", lambda *_a, fresh=False, **_kw:
                            None if fresh else ["acme-tui"]),
                           ("opened", lambda *_a, **_kw: True),
                           ("seat_command", lambda *_a, **_kw: ("true", self.root / "launch")),
                           ("tmux_out", tmux),
                           ("tmux_lists", lambda *_a, **_kw: (0, ""))):
            self.stack.enter_context(patch.object(orch, name, side_effect=fake))
        def forget(record):     # no Codex remote to reach: the receipt is all it drops here
            path = codex.path_for(record)
            if path:
                path.unlink(missing_ok=True)

        for module, name, fake in ((watch, "announce_state", None), (statusbar, "dress", None),
                                   (codex, "forget", forget)):
            self.stack.enter_context(patch.object(module, name, side_effect=fake))

    def opened_on(self, model):
        """A seat on that model, its conversation in its launch receipt: the receipt and the
        conversation."""
        self.cfg["models"]["acme-next"] = dict(self.cfg["models"][model], model="acme/next")
        config.save(self.cfg)
        config.save_session(self.cfg, SEAT, model, ["opus"], {"cwd": str(self.root)})
        harness = config.model(self.cfg, model)["harness"]
        self.pane = (REPO / f"tests/fixtures/{harness}-prompt-pane.txt").read_text()
        if harness == "opencode":
            receipt = Path(opencode.launched(SEAT, self.root, None)[opencode.RECEIPT_ENV])
            (receipt / "session").write_text("ses_acme")
            return receipt, "ses_acme"
        transcript = self.root / "rollout.jsonl"
        transcript.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": "acme-thread", "cwd": str(self.root)}}) + "\n")
        receipt = codex.prepare(SEAT, self.root, None)
        codex.capture(receipt, {"hook_event_name": "SessionStart", "source": "startup",
                                "session_id": "acme-thread", "transcript_path": str(transcript),
                                "cwd": str(self.root)})
        return receipt, "acme-thread"

    def move(self):
        return orch.switch_orchestrator(self.cfg, SEAT, "acme-next", providers={})

    def conversation(self):
        return orch.seat_conversation(config.session_records()[SEAT])

    def receipts(self):
        return sorted(config.STATE.glob("*-launch-*"))

    def check_refused(self, model, why="refused"):
        receipt, own = self.opened_on(model)
        self.assertEqual(self.conversation(), own)
        self.assertIn(why, self.move())
        self.assertEqual(self.receipts(), [receipt])
        self.assertEqual(self.conversation(), own)
        self.assertEqual(config.session_records()[SEAT]["orchestrator"], model)

    def check_started(self, model, setup=(0, "")):
        self.refused = None
        receipt, own = self.opened_on(model)
        with patch.object(orch, "tmux_lists", return_value=setup):
            self.assertEqual(self.move(), setup[1] and f"cannot set up the session {SEAT}: {setup[1]}")
        [replacement] = self.receipts()
        self.assertNotEqual(replacement, receipt)
        self.assertEqual(self.conversation(), own)

    def test_a_refused_opencode_respawn_keeps_its_receipt(self):
        self.check_refused("mimo")

    def test_a_refused_codex_respawn_keeps_its_receipt(self):
        self.check_refused("astra")

    def test_an_opencode_respawn_that_starts_drops_the_receipt_it_replaced(self):
        self.check_started("mimo")

    def test_a_codex_respawn_that_starts_drops_the_receipt_it_replaced(self):
        self.check_started("astra")

    def test_a_launch_failing_before_its_respawn_keeps_the_receipt(self):
        self.refused = None
        facts = config.hook_facts_path(SEAT)
        facts.write_text("{}")
        replace = Path.replace

        def refused(path, target):
            if path == facts:
                raise PermissionError("acme facts stay")
            return replace(path, target)

        with patch.object(Path, "replace", refused):
            self.check_refused("astra", "acme facts stay")

    def test_a_respawn_whose_setup_fails_after_keeps_the_receipt_it_started_with(self):
        self.check_started("mimo", (1, "acme env refused"))


if __name__ == "__main__":
    unittest.main()
