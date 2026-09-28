"""An owner's prompt answers the seat's question without an ak open.

Offline: real hook input, fake tmux and card delivery, and a temporary HOME.
"""

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, notify, orch, watch

SEAT = "fix-api"
QUESTION = "Which schema should acme use?"
HANDBACK = "Run fix-parser finished: PASS. Decide the next step."
PROMPT = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()


class AnswerClosesQuestion(Sandbox):
    def setUp(self):
        super().setUp()
        # The subprocess hook and the in-process readers share this sandbox's paths.
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "orchestrator", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_NOTIFY_SINK": "dry-run"}))
        self.seat = {"name": SEAT, "path": str(self.root), "created": 100,
                     "attached": False, "exited": False, "legacy": False}
        config.save_session(self.cfg, SEAT, "opus", ["astra"],
                            {"cwd": str(self.root), "session_title": SEAT})
        self.pane, self.typed, self.edits = PROMPT, [], []
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        self.stack.enter_context(patch.object(notify, "close_needs", side_effect=self.close))

    def tmux(self, *args, **kwargs):
        if args[0] in ("capture-pane", "send-keys"):
            self.assertEqual(args[args.index("-t") + 1], f"={self.seat['name']}:")
        if args[0] == "capture-pane":
            return 0, self.pane
        if args[0] == "send-keys":
            if "-l" in args:
                self.typed.append(args[-1])
                self.pane = PROMPT.replace("❯\u00a0\n", f"❯ {args[-1]}\n")
            elif args[-1] == "Enter":
                self.pane = PROMPT
            return 0, ""
        return 1, "unsupported fake tmux command"

    def close(self, previous, status):
        self.edits.extend((receipt["message_id"], status)
                          for receipt in previous.get("open_needs", []))
        return []

    def notice(self, **extra):
        name = self.seat["name"]
        pending = [{"message_id": "1"}]
        notify.record(name, "needs", QUESTION, open_needs=pending, **extra)
        notify._card_write(name, {"word": "needs you", "since": 10000, "began": 10000,
                                  "episode": "acme-question", "sent": True,
                                  "open_needs": pending})

    def hook(self, event, **payload):
        result = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")],
                                input=json.dumps({"hook_event_name": event, **payload}),
                                text=True, capture_output=True, timeout=15,
                                env={"HOME": str(self.root), "PATH": os.environ["PATH"],
                                     "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def prompt(self, **payload):
        self.hook("UserPromptSubmit", **(payload or {"prompt": "Use the second schema."}))
        return json.loads(config.stop_path(SEAT).read_text())["turn"]

    def handback(self):
        return watch.type_at_prompt(self.seat, HANDBACK, lambda _: None, cfg=self.cfg)

    def assert_answered(self):
        name = self.seat["name"]
        notice = notify.last(name, include_seen=True)
        self.assertNotIn("opened_at", notice)
        self.assertGreater(notice["answered_at"], notice["time"])
        self.assertTrue(notify.resolved(notice))
        self.assertFalse(watch.owner_question(notify.last(name)))
        # The whole owner turn can finish between ticks: the word remains needs you,
        # but the question and its card are answered even without an observed working word.
        self.hook("Stop")
        harness, live = watch.look_at(self.seat, cfg=self.cfg)
        answer = watch.session_state(name, session=self.seat, cfg=self.cfg,
                                     harness=harness, live=live)
        self.assertEqual((answer["word"], answer["reason"]), ("needs you", "waiting for you"))
        self.assertEqual(notify.transition(name, answer=answer, seat=self.seat), 0)
        self.assertEqual(self.edits, [("1", "Answered")])
        self.assertEqual(notify._card_read(name)["closed"], "Answered")
        self.assertTrue(self.handback())
        self.assertEqual(self.typed, [HANDBACK])

    def assert_open(self):
        name = self.seat["name"]
        self.hook("Stop")
        notice = notify.last(name)
        self.assertTrue(watch.owner_question(notice))
        self.assertFalse(notify.resolved(notice))
        self.assertFalse(self.handback())
        self.assertEqual(self.typed, [])
        self.assertEqual(notify.transition(name, seat=self.seat), 0)
        self.assertEqual(self.edits, [])
        self.assertNotIn("closed", notify._card_read(name))
        self.assertEqual(watch.session_state(name, session=self.seat, cfg=self.cfg)["reason"],
                         QUESTION)

    def test_owner_prompt_releases_a_handback_without_opening_through_ak(self):
        self.notice()
        self.assertFalse(self.handback())
        self.prompt()
        self.assert_answered()

    def test_launch_name_answers_after_rename_and_releases_title_sync(self):
        self.notice()
        for name in ("fix-schema", "fix-parser"):
            config.rename_session(self.seat["name"], name)
            self.seat = dict(self.seat, name=name)
        self.assertFalse(watch.sync_title(self.seat))
        self.prompt()
        self.assert_answered()
        self.assertTrue(watch.sync_title(self.seat))
        self.assertEqual(self.typed[-1], "/rename fix-parser")

    def test_prompt_before_the_notice_leaves_it_open(self):
        turn = self.prompt()
        self.notice(time=turn + 1)
        self.assert_open()

    def test_a_hook_finishing_after_a_newer_notice_cannot_answer_it(self):
        turn = self.prompt()
        self.notice(time=turn)
        notify.answered(SEAT, turn)
        self.assert_open()

    def test_cross_session_prompt_leaves_it_open(self):
        self.notice()
        for field in ("prompt", "message"):
            with self.subTest(field=field):
                self.prompt(**{field: "<cross-session-message from='acme'>Ready.</cross-session-message>"})
                self.assert_open()

    def test_no_prompt_leaves_it_open(self):
        self.notice()
        self.assert_open()

    def test_a_peer_prompt_cannot_reopen_an_answered_question(self):
        self.notice()
        self.prompt()
        self.prompt(prompt="<cross-session-message>Ready.</cross-session-message>")
        self.assert_answered()

    def test_a_failed_card_edit_is_retried(self):
        self.notice()
        self.prompt()
        self.hook("Stop")
        with patch.object(notify, "close_needs", side_effect=lambda card, _: card["open_needs"]):
            notify.transition(SEAT, seat=self.seat)
        self.assertEqual(notify._card_read(SEAT)["open_needs"], [{"message_id": "1"}])
        notify.transition(SEAT, seat=self.seat)
        self.assertEqual(self.edits, [("1", "Answered")])
        self.assertEqual(notify._card_read(SEAT)["open_needs"], [])

    def test_an_answer_does_not_close_a_later_question_episode(self):
        self.notice()
        turn = self.prompt()
        card = notify._card_read(SEAT)
        card.update(since=turn + 1, episode="acme-permission")
        notify._card_write(SEAT, card)
        notify.transition(SEAT, answer={"word": "needs you", "since": turn + 1,
                                       "reason": "Allow the command?"}, seat=self.seat)
        self.assertEqual(self.edits, [])
        self.assertNotIn("closed", notify._card_read(SEAT))

    def test_opening_through_ak_still_answers_after_output(self):
        self.notice()
        notify.opened(SEAT, lambda: PROMPT)
        self.assertTrue(notify.progress(SEAT, lambda: PROMPT + "\nThe schema is updated."))
        self.assertFalse(watch.owner_question(notify.last(SEAT)))
        self.assertTrue(self.handback())

    def test_owner_prompt_leaves_a_done_standing(self):
        notify.record(SEAT, "done", "Acme now reads both schemas.")
        self.prompt()
        self.assertEqual(notify.last(SEAT)["kind"], "done")
        self.assertNotIn("answered_at", notify.last(SEAT))


if __name__ == "__main__":
    unittest.main(verbosity=2)
