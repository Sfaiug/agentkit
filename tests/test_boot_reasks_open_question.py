"""A question open when the host went down is asked again after the boot.

Offline.  The seats are faked (no tmux: `orch.sessions` lists what the boot pass reopened,
`watch.live_state` says what each screen shows after it came back) and the typing is
recorded; the real boot pass and the real `continue_turns` decide what is typed.
"""

import json
import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, notify, orch, watch

NOW = 1_800_000_000


class BootReasks(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": ""}))
        self.live, self.typed, self.screen = [], [], "at_prompt"
        self.stack.enter_context(patch.object(orch, "sessions", lambda: list(self.live)))
        self.stack.enter_context(patch.object(
            orch, "tmux_out", side_effect=AssertionError("tmux was called")))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(
            watch, "live_state",
            side_effect=lambda *a, **k: {"state": self.screen, "rule": "screen",
                                         "authority": "screen", "evidence": "",
                                         "began": NOW, "since": NOW}))
        self.stack.enter_context(patch.object(
            watch, "type_into",
            side_effect=lambda session, text, *_a, **_kw: self.typed.append(
                (session["name"], text)) or True))
        self.stack.enter_context(patch.object(watch.time, "sleep", lambda _s: None))
        self.resume = self.stack.enter_context(patch.object(orch, "resume",
                                                            side_effect=self.reopened))
        self.stack.enter_context(patch.object(watch, "boot_id", return_value="after"))
        watch.save_state({**watch.load_state(), "boot_id": "before"})

    def reopened(self, cfg, name, **_kw):
        self.live.append({"name": name, "path": str(self.root), "created": 1,
                          "attached": False, "exited": False, "legacy": False,
                          "resumable": False})
        return "resumed"

    def seat(self, name, event, kind="", notice=None):
        """A seat with its own conversation, its hook's last word before the host went down,
        and the last thing it said with `ak notify`."""
        config.save_session(self.cfg, name, "fable", ["astra"],
                            {"cwd": str(self.root), "created": 100,
                             "conversation": f"thread-{name}", "id_source": orch.LAUNCHER})
        config.hook_facts_path(name).write_text(json.dumps(
            {"session": name, "event": event, "kind": kind, "at": NOW - 600}))
        if notice:
            notify.record(name, *notice)

    def boot(self):
        watch.resume_after_boot(self.cfg, log=lambda _line: None)
        watch.continue_turns(self.cfg, lambda _line: None)

    def test_a_seat_asking_when_the_host_went_down_is_told_once_to_ask_again(self):
        # its harness's question prompt was up, or its own `ak notify needs` was unanswered
        self.seat("dialog", "PermissionRequest")
        self.seat("needs", "Stop", notice=("needs", "Which branch should fix-api land on?"))
        self.seat("working", "UserPromptSubmit")
        self.seat("idle", "Stop")
        self.seat("done", "Stop", notice=("done", "fix-api is live."))
        self.seat("closed", "PermissionRequest", notice=("needs", "Ship it?"))
        orch.mark_owner_closed("closed")
        self.boot()
        self.assertEqual(sorted(call.args[1] for call in self.resume.call_args_list),
                         ["dialog", "done", "idle", "needs", "working"])
        self.assertEqual(sorted(self.typed), [("dialog", watch.ASKED_LINE),
                                              ("needs", watch.ASKED_LINE),
                                              ("working", watch.MIDTURN_LINE)])
        self.assertIn("host restarted", watch.ASKED_LINE)
        self.assertIn("Ask it again", watch.ASKED_LINE)
        # once per boot: the same boot's next passes type nothing more
        self.boot()
        self.boot()
        self.assertEqual(len(self.typed), 3)

    def test_the_line_waits_for_its_quiet_prompt(self):
        self.seat("dialog", "PermissionRequest")
        for screen in ("asking", "draft"):
            self.screen = screen
            self.boot()
            self.assertEqual(self.typed, [])
        self.screen = "at_prompt"
        self.boot()
        self.assertEqual(self.typed, [("dialog", watch.ASKED_LINE)])
        self.assertIsNone(watch.seat_read("dialog")["midturn"])


if __name__ == "__main__":
    unittest.main()
