"""An owner's prompt answers the seat's question without an ak open.

Offline: real hook input, fake tmux and card delivery, and a temporary HOME.
"""

import json
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, notify, orch, watch

SEAT = "fix-api"
QUESTION = "Which schema should acme use?"
HANDBACK = "Run fix-parser finished: PASS. Decide the next step."
PROMPT = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()

# No command falls through to the host's tmux, including an inherited pane on another server.
FAKE_TMUX = r"""#!/bin/bash
[[ $1 = -L && $2 = agentkit-test ]] || exit 1
shift 2
case $1 in
  list-sessions) printf '%s\t%s\t100\t0\t1\n' "$FAKE_SEAT" "$HOME" ;;
  list-panes) printf '%s\t0\n' "$FAKE_SEAT" ;;
  display-message) case $4 in
                     %7) printf '/fake/agentkit-test\t%s\n' "$FAKE_SEAT" ;;
                     %8) printf '/fake/agentkit-test\tacme-other\n' ;;
                     *) exit 1 ;;
                   esac ;;
  capture-pane) [[ $6 = "=$FAKE_SEAT:" ]] || exit 1
                cat "$FAKE_CAPTURE" ;;
  set-option) ;;
  *) exit 1 ;;
esac
"""

# Wait for each detached look to finish before assertions or sandbox cleanup. Bound it even
# if an assertion fails, and report its exit status despite the hook's silent redirects.
PYTHON = r"""#!/bin/bash
if [[ $1 = -c && $2 = *watch.hook_look* ]]; then
  timeout -k 2 15 "$TEST_PYTHON" "$@"
  printf '%s\n' "$?" >"$LOOK_FINISHED"
else
  exec "$TEST_PYTHON" "$@"
fi
"""


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
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, script in (("tmux", FAKE_TMUX), ("python3", PYTHON)):
            path = self.bin / name
            path.write_text(script)
            path.chmod(0o755)
        self.looks = []

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

    def wait_look(self, finished):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if finished.exists() and finished.read_text():
                self.assertEqual(finished.read_text().strip(), "0")
                return
            time.sleep(0.01)
        self.fail("the hook's background look did not finish")

    def hook(self, event, script="seat-state.sh", wait=True, timeout=15, env=None, **payload):
        finished = self.root / f"look-{len(self.looks)}"
        self.looks.append(finished)
        environ = {"HOME": str(self.root), "PATH": f"{self.bin}:{os.environ['PATH']}",
                   "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator",
                   "AGENTKIT_TMUX_SOCKET": "agentkit-test", "AK_NOTIFY_SINK": "dry-run",
                   "TMUX": "/fake/agentkit-test,1,0", "TMUX_PANE": "%7",
                   "FAKE_SEAT": self.seat["name"],
                   "FAKE_CAPTURE": str(REPO / "tests/fixtures/claude-prompt-pane.txt"),
                   "TEST_PYTHON": sys.executable, "LOOK_FINISHED": str(finished), **(env or {})}
        looks = script == "seat-state.sh" and environ["TMUX"] and environ["TMUX_PANE"]
        if looks:
            self.addCleanup(self.wait_look, finished)
        result = subprocess.run(["bash", str(REPO / "hooks" / script)],
                                input=json.dumps({"hook_event_name": event, **payload}),
                                text=True, capture_output=True, timeout=timeout, env=environ)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        if script == "seat-state.sh":
            self.assertEqual(result.stdout, "")
        if looks and wait:
            self.wait_look(finished)
        return result.stdout

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
        # The answer ended its episode: the seat waiting now is one of its own, not carded yet.
        card = notify._card_read(name)
        self.assertNotEqual(card["episode"], "acme-question")
        self.assertFalse(card["sent"])
        self.assertTrue(self.handback())
        self.assertEqual(self.typed, [HANDBACK])

    def assert_open(self):
        name = self.seat["name"]
        self.hook("Stop")
        notice = notify.last(name)
        self.assertTrue(watch.owner_question(notice))
        self.assertFalse(notify.resolved(notice))
        self.assertEqual(notify.transition(name, seat=self.seat), 0)
        self.assertEqual(self.edits, [])
        self.assertNotIn("closed", notify._card_read(name))
        self.assertEqual(watch.session_state(name, session=self.seat, cfg=self.cfg)["reason"],
                         QUESTION)

    def test_a_hand_back_typed_while_a_question_is_open_answers_nothing(self):
        """review 20261007-0116: the harness's prompt hook reports a line ak typed as it
        reports the owner's words; its typing receipt says whose it is."""
        self.notice()
        self.assertTrue(self.handback())
        self.prompt(prompt=HANDBACK)
        self.typed = []
        self.assert_open()
        self.prompt()                   # the owner's own words still answer it
        self.assert_answered()

    def test_a_turn_a_hand_back_opened_ends_on_the_standing_question(self):
        """review 20261007-0336: the seat's question to the owner still stands, unanswered, so
        the turn the hand-back opened may end on it -- as `watch.stop_nudge` lets it -- and is
        never sent back to ask again."""
        self.notice()
        self.assertTrue(self.handback())
        self.prompt(prompt=HANDBACK)
        self.assertEqual(self.hook("Stop", script="orchestrator-stop.sh",
                                   last_assistant_message="Parser merged; the schema waits."), "")
        self.typed = []
        self.assert_open()

    def test_an_answer_longer_than_one_command_argument_still_answers(self):
        """review 20261007-0336: a pasted log past Linux's 128 KiB argument limit reaches the
        look on its stdin, not its command line."""
        self.notice()
        self.prompt(prompt="Use the second schema; the failing log follows.\n"
                    + "acme log line\n" * 11000)
        self.assert_answered()

    def test_owner_prompt_answers_without_opening_through_ak(self):
        self.notice()
        self.prompt()
        self.assert_answered()

    def test_prompt_never_waits_for_the_notice_lock_and_the_answer_lands_after_release(self):
        self.notice()
        # This process holds the lock while the harness's hook and its look run elsewhere.
        with notify.session_lock(SEAT):
            began = time.monotonic()
            self.hook("UserPromptSubmit", prompt="Use the second schema.", wait=False, timeout=1)
            self.assertLess(time.monotonic() - began, 1)
            self.assertNotIn("answered_at", notify.last(SEAT, include_seen=True))
        self.wait_look(self.looks[-1])
        self.assertEqual(notify.last(SEAT, include_seen=True)["answered_at"],
                         json.loads(config.stop_path(SEAT).read_text())["turn"])
        self.assert_answered()

    def test_remote_control_prompt_answers_the_seats_question(self):
        self.notice()
        self.prompt(message="Use the second schema.")
        self.assert_answered()

    def test_owner_prompt_closes_a_card_no_notice_asked(self):
        # The screen alone said needs you and its card went out: no notice holds the answer.
        notify._card_write(SEAT, {"word": "needs you", "since": 10000, "began": 10000,
                                  "episode": "acme-dialog", "sent": True,
                                  "open_needs": [{"message_id": "1"}]})
        self.prompt()
        answer = {"word": "needs you", "since": 10000, "reason": "waiting for you"}
        self.assertEqual(notify.transition(SEAT, answer=answer, seat=self.seat), 0)
        self.assertEqual(self.edits, [("1", "Answered")])
        card = notify._card_read(SEAT)
        self.assertNotEqual(card["episode"], "acme-dialog")
        self.assertFalse(card["sent"])

    def test_prompt_leaves_a_watcher_alert_open(self):
        self.notice(watcher=True)
        for text in ("Use the second schema.", HANDBACK):
            with self.subTest(text=text):
                self.prompt(prompt=text)
                self.hook("Stop")
                notice = notify.last(SEAT, include_seen=True)
                self.assertNotIn("answered_at", notice)
                self.assertFalse(notify.resolved(notice))
                self.assertEqual(notify.transition(SEAT, seat=self.seat), 0)
                self.assertEqual(self.edits, [])
                self.assertNotIn("closed", notify._card_read(SEAT))
        # Recovery still owns the alert's ending.
        notify.clear(SEAT, notice=QUESTION)
        self.assertTrue(notify.resolved(notify.last(SEAT, include_seen=True)))

    def test_slash_commands_leave_a_question_open(self):
        self.notice()
        for field in ("prompt", "message"):
            for command in ("/compact", "/rename x", " \n /compact"):
                with self.subTest(field=field, command=command):
                    self.prompt(**{field: command})
                    self.assert_open()

    def test_prompt_outside_the_seats_pane_leaves_a_question_open(self):
        self.notice()
        for outside in ({"TMUX_PANE": "%8"}, {"TMUX": "/fake/other-server,1,0"},
                        {"TMUX_PANE": ""}, {"TMUX": ""}):
            with self.subTest(outside=outside):
                self.prompt(prompt="Use the second schema.", env=outside)
                self.assert_open()

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
        with notify.session_lock(SEAT):
            turn = self.prompt(prompt="Use the second schema.", wait=False)
            self.notice(time=turn)
        self.wait_look(self.looks[-1])
        self.assert_open()

    def test_task_notification_leaves_it_open(self):
        self.notice()
        for field in ("prompt", "message"):
            with self.subTest(field=field):
                self.prompt(**{field: "<task-notification><task-id>acme-task</task-id>"
                               "<status>completed</status></task-notification>"})
                self.assert_open()

    def test_task_notification_cannot_end_on_a_done_from_before_its_turn(self):
        notify.record(SEAT, "done", "Acme reads both schemas.")
        for field in ("prompt", "message"):
            with self.subTest(field=field):
                self.prompt(**{field: "<task-notification><status>failed</status>"
                               "</task-notification>"})
                output = self.hook("Stop", script="orchestrator-stop.sh", background_tasks=[],
                                   last_assistant_message="The background acme test run failed in fix-api.")
                self.assertTrue(output, "background results still require the seat to act")
                self.assertEqual(json.loads(output)["decision"], "block")

    def test_task_notification_question_keeps_its_plain_reply_ending(self):
        for field in ("prompt", "message"):
            with self.subTest(field=field):
                self.prompt(**{field: "<task-notification>Which acme schema failed?\n"
                               "</task-notification>"})
                output = self.hook("Stop", script="orchestrator-stop.sh", background_tasks=[],
                                   last_assistant_message="Acme's second schema failed.")
                self.assertEqual(output, "")

    def test_no_prompt_leaves_it_open(self):
        self.notice()
        self.assert_open()

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
        permission = {"word": "needs you", "since": turn + 1, "reason": "Allow the command?"}
        with patch.object(watch, "session_state", return_value=permission):
            notify.transition(SEAT, answer=permission, seat=self.seat)
        self.assertEqual(self.edits, [])
        self.assertNotIn("closed", notify._card_read(SEAT))

    def test_opening_through_ak_and_output_after_it_answer_nothing(self):
        self.notice()
        notify.opened(SEAT, lambda: PROMPT)
        self.assertFalse(notify.progress(SEAT, lambda: PROMPT + "\nThe schema is updated.",
                                         watch.seat_model(self.cfg, SEAT)[0]))
        self.assertTrue(watch.owner_question(notify.last(SEAT)))

    def test_owner_prompt_leaves_a_done_standing(self):
        notify.record(SEAT, "done", "Acme now reads both schemas.")
        self.prompt()
        self.assertEqual(notify.last(SEAT)["kind"], "done")
        self.assertNotIn("answered_at", notify.last(SEAT))


if __name__ == "__main__":
    unittest.main(verbosity=2)
