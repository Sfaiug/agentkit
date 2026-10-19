"""A question open when the host went down is asked again after the boot.

Offline.  The seats are faked (no tmux: `orch.sessions` lists what the boot pass reopened,
captured Claude panes are their screens, a fake `send-keys` takes each Enter) and the line's
text is recorded where it would go in; the real boot pass, `continue_turns`,
`finish_own_lines` and the real locked send decide what is typed.
"""

import json
import os
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, notify, orch, watch

PROMPT = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
QUESTION = (REPO / "tests/fixtures/claude-question-pane.txt").read_text()
EMPTY = "❯ \n"


class BootReasks(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": ""}))
        self.live, self.texts, self.keys, self.meanwhile = [], [], [], []
        self.pane, self.fail_enter = PROMPT, False
        self.stack.enter_context(patch.object(orch, "sessions", lambda: list(self.live)))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        # what changes once the send has its lock, after every look before it
        self.stack.enter_context(patch.object(
            orch, "rulebook_prepare",
            side_effect=lambda _name: [self.meanwhile.pop(0)() for _ in list(self.meanwhile)]))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text",
                                              side_effect=lambda *_a, **_kw: self.pane))
        self.stack.enter_context(patch.object(watch, "_send_line", side_effect=self.send_line))
        self.stack.enter_context(patch.object(watch.time, "sleep", lambda _s: None))
        self.resume = self.stack.enter_context(patch.object(orch, "resume",
                                                            side_effect=self.reopened))
        self.stack.enter_context(patch.object(watch, "boot_id", return_value="after"))
        watch.save_state({**watch.load_state(), "boot_id": "before"})

    def send_line(self, session, text, log, typed=lambda: None, **_kw):
        self.texts.append((session["name"], text))
        self.pane = PROMPT.replace(EMPTY, f"❯ {text}\n")
        typed()
        return True

    def tmux(self, *args, **_kw):
        self.assertEqual((args[0], args[-1]), ("send-keys", "Enter"))
        self.keys.append(args[2])
        if self.fail_enter:
            return 1, "Enter failed"
        self.pane = PROMPT
        return 0, ""

    def fact(self, name, event, kind="", at=None):
        config.hook_facts_path(name).write_text(json.dumps(
            {"session": name, "event": event, "kind": kind,
             "at": time.time() - 600 if at is None else at}))

    def reopened(self, cfg, name, **_kw):
        self.live.append({"name": name, "path": str(self.root), "created": 1,
                          "attached": False, "exited": False, "legacy": False,
                          "resumable": False})
        self.fact(name, "Notification", "idle_prompt", at=time.time())   # back at its prompt
        return "resumed"

    def seat(self, name, event, kind="", notice=None):
        """A seat with its own conversation, its hook's last word before the host went down,
        and the last thing it said with `ak notify`."""
        config.save_session(self.cfg, name, "fable", ["astra"],
                            {"cwd": str(self.root), "created": 100,
                             "conversation": f"thread-{name}", "id_source": orch.LAUNCHER})
        self.fact(name, event, kind)
        if notice:
            notify.record(name, *notice)

    def boot(self):
        watch.resume_after_boot(self.cfg, log=lambda _line: None)
        watch.continue_turns(self.cfg, lambda _line: None)

    def tick(self):
        """The tick's own order: a line left in its composer is finished before new ones."""
        watch.finish_own_lines(self.cfg, lambda _line: None)
        watch.continue_turns(self.cfg, lambda _line: None)

    def test_a_seat_asking_when_the_host_went_down_is_told_once_to_ask_again(self):
        # its harness's question prompt was up, or its own `ak notify needs` was unanswered,
        # in a turn or not
        self.seat("dialog", "PermissionRequest")
        self.seat("needs", "Stop", notice=("needs", "Which branch should fix-api land on?"))
        self.seat("asked-in-turn", "UserPromptSubmit", notice=("needs", "Keep the old API?"))
        self.seat("working", "UserPromptSubmit")
        self.seat("idle", "Stop")
        self.seat("done", "Stop")
        config.plan_path("done").write_text("- [x] fix-api is live\n")
        self.seat("closed", "PermissionRequest", notice=("needs", "Ship it?"))
        orch.mark_owner_closed("closed")
        self.boot()
        self.assertEqual(sorted(call.args[1] for call in self.resume.call_args_list),
                         ["asked-in-turn", "dialog", "needs", "working"])
        self.assertEqual(sorted(self.texts), [("asked-in-turn", watch.ASKED_LINE),
                                              ("dialog", watch.ASKED_LINE),
                                              ("needs", watch.ASKED_LINE),
                                              ("working", watch.MIDTURN_LINE)])
        self.assertIn("host restarted", watch.ASKED_LINE)
        self.assertIn("Ask it again", watch.ASKED_LINE)
        # once per boot: the same boot's next passes type nothing more
        self.boot()
        self.tick()
        self.assertEqual(len(self.texts), 4)

    def test_the_line_waits_under_the_send_lock_for_a_quiet_prompt(self):
        self.seat("dialog", "PermissionRequest")
        watch.resume_after_boot(self.cfg, log=lambda _line: None)
        marked = watch.seat_read("dialog")["midturn"]["at"]

        def screen(event, pane):
            if event:
                self.fact("dialog", *event, at=marked - 1)
            else:
                config.hook_facts_path("dialog").unlink()   # a relaunch forgets its hook's word
            self.pane = pane
        # a turn begun as it was reopened, before its mark; a draft of the owner's; a question
        # on its screen; a harness still loading, which nothing reads
        for event, pane in ((("UserPromptSubmit",), PROMPT),
                            (("Notification", "idle_prompt"),
                             PROMPT.replace(EMPTY, "❯ use the staging db\n")),
                            (("Notification", "idle_prompt"), QUESTION),
                            (None, "Resuming the conversation…\n")):
            screen(("Notification", "idle_prompt"), PROMPT)
            self.meanwhile.append(lambda: screen(event, pane))
            watch.continue_turns(self.cfg, lambda _line: None)
            self.assertEqual((self.texts, self.keys), ([], []))
            self.assertNotIn("tries", watch.seat_read("dialog")["midturn"])
        screen(("Notification", "idle_prompt"), PROMPT)
        watch.continue_turns(self.cfg, lambda _line: None)
        self.assertEqual(self.texts, [("dialog", watch.ASKED_LINE)])
        self.assertIsNone(watch.seat_read("dialog")["midturn"])

    def test_a_reask_whose_enter_failed_is_finished_past_its_open_notice_once(self):
        self.seat("needs", "Stop", notice=("needs", "Which branch should fix-api land on?"))
        self.fail_enter = True
        self.boot()
        self.assertEqual((self.texts, self.keys), ([("needs", watch.ASKED_LINE)], ["=needs:"]))
        self.fail_enter = False
        self.tick()
        self.assertEqual(self.keys, ["=needs:", "=needs:"])
        self.assertIsNone(watch.seat_read("needs")["midturn"])
        self.tick()
        self.assertEqual(len(self.texts), 1)

    def test_a_newer_mark_saved_while_the_enter_went_is_left_for_its_own_line(self):
        self.seat("needs", "Stop", notice=("needs", "Which branch should fix-api land on?"))
        self.fail_enter = True
        self.boot()
        self.fail_enter = False
        newer = {"boot": "after", "at": time.time(), "name": "needs",
                 "line": "You now run on another model; read your plan and go on."}
        self.meanwhile.append(lambda: watch.seat_write("needs", midturn=newer))
        watch.finish_own_lines(self.cfg, lambda _line: None)
        self.assertEqual(self.keys, ["=needs:", "=needs:"])
        self.assertEqual(watch.seat_read("needs")["midturn"], newer)

    def newer_mark_kept_by_the_boot_pass(self, fail_enter):
        self.seat("needs", "Stop", notice=("needs", "Which branch should fix-api land on?"))
        self.fail_enter = fail_enter
        newer = {"boot": "after", "at": time.time(), "name": "needs",
                 "line": "You now run on another model; read your plan and go on."}
        self.meanwhile.append(lambda: watch.seat_write("needs", midturn=newer))
        self.boot()
        self.assertEqual(self.texts, [("needs", watch.ASKED_LINE)])
        self.assertEqual(watch.seat_read("needs")["midturn"], newer)

    def test_a_newer_mark_saved_while_the_boot_pass_line_landed_is_left(self):
        self.newer_mark_kept_by_the_boot_pass(fail_enter=False)

    def test_a_newer_mark_saved_while_the_boot_pass_line_missed_is_left(self):
        self.newer_mark_kept_by_the_boot_pass(fail_enter=True)


if __name__ == "__main__":
    unittest.main()
