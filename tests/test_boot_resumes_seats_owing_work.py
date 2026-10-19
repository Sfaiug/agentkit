"""After a reboot, only seats that still owe work come back.

Offline.  No tmux: `orch.sessions` lists what the boot pass reopened and `orch.resume` is
faked; each seat is its record, its hook's last word, its notices, its plan and its runs in
the sandbox's HOME.  The real boot pass and the real `session_state` decide.
"""

import json
import os
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, notify, orch, watch

OPEN_LINE = "- [ ] the parser parses · check: `false` · acme · written 2026-10-17 09:00\n"


class BootResumesOwingSeats(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": ""}))
        self.live = []
        self.stack.enter_context(patch.object(orch, "sessions", lambda: list(self.live)))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.resume = self.stack.enter_context(patch.object(orch, "resume",
                                                            side_effect=self.reopened))
        self.stack.enter_context(patch.object(watch, "boot_id", return_value="after"))
        watch.save_state({**watch.load_state(), "boot_id": "before"})

    def reopened(self, cfg, name, **_kw):
        self.live.append({"name": name, "path": str(self.root), "created": 1,
                          "attached": False, "exited": False, "legacy": False,
                          "resumable": False})
        return "resumed"

    def seat(self, name, event="Stop", notice=None, run=None):
        """A seat with its own conversation, its hook's last word before the host went down,
        the last thing it said with `ak notify` and a run of its own."""
        config.save_session(self.cfg, name, "fable", ["astra"],
                            {"cwd": str(self.root), "created": 100,
                             "conversation": f"thread-{name}", "id_source": orch.LAUNCHER})
        config.hook_facts_path(name).write_text(json.dumps(
            {"session": name, "event": event, "kind": "", "at": time.time() - 600}))
        if notice:
            notify.record(name, *notice)
        if run:
            self.ended(f"run-{name}", owner=name, finished_at=time.time() - 600, **run)

    def test_only_a_seat_that_owes_work_comes_back_and_the_rest_reopen_with_their_number(self):
        self.seat("midturn", "UserPromptSubmit")
        self.seat("asking", "PermissionRequest")
        self.seat("question", notice=("needs", "Which branch should fix-api land on?"))
        self.seat("planned")
        config.plan_path("planned").write_text(OPEN_LINE)
        self.seat("undecided", run={"state": "interrupted", "verdict": None})
        self.seat("running", run={"state": "running", "verdict": None})
        self.seat("landing", run={"state": "waiting", "verdict": None,
                                  "waiting_on": {"line": "acme"}})
        self.seat("done", run={"merged": True})
        config.plan_path("done").write_text("- [x] fix-api is live\n")
        self.seat("idle")
        self.seat("closed", "PermissionRequest", notice=("needs", "Ship it?"))
        orch.mark_owner_closed("closed")
        owing = ["landing", "planned", "question", "running", "undecided"]
        # what the seat's own word already says of each one nobody is in: the same test
        for name in owing:
            self.assertIn(watch.session_state(name)["word"], ("needs you", "working"), name)
        for name, word in (("done", "done"), ("idle", "idle")):
            self.assertEqual(watch.session_state(name)["word"], word, name)
        back = sorted(["asking", "midturn", *owing])
        said = []
        watch.resume_after_boot(self.cfg, dry_run=True, log=said.append)
        self.assertEqual([line.split()[2] for line in said], back)
        self.resume.assert_not_called()
        watch.resume_after_boot(self.cfg, log=lambda _line: None)
        self.assertEqual(sorted(call.args[1] for call in self.resume.call_args_list), back)
        # the rest stay down, each a closed seat its number reopens
        idle = watch.session_state("idle", number=7)
        self.assertEqual(idle["word"], "idle")
        self.assertIn("press 7 to reopen", idle["reason"])
        self.assertEqual(watch.session_state("done")["word"], "done")
        self.assertTrue(watch.seat_read("closed")["closed_by_owner"])
        # once per boot
        watch.resume_after_boot(self.cfg, log=lambda _line: None)
        self.assertEqual(self.resume.call_count, len(back))


if __name__ == "__main__":
    unittest.main()
