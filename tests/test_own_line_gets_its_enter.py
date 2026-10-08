"""The tick finishes ak's fixed lines from the composer, even after their tries ran out.

Offline: captured harness panes, fake tmux and a temporary HOME. No typing receipt or
recovery mark is needed to recognize a line; delivery remains at least once.
"""

from contextlib import contextmanager
import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.sandbox import REPO, Sandbox
from test_tick_passes import PASSES
from agentkit import config, orch, watch

SEAT = "acme-api"
COMPOSERS = {
    "claude": ("opus", "❯\u00a0\n", "❯ {}\n"),
    "codex": ("astra", "› Ask Codex to do anything\n", "› {}\n"),
    "muse": ("spark", "\n❯\n", "\n❯ {}\n"),
    "opencode": ("mimo", '┃  Ask anything… "What is the tech stack of this project?"', "┃  {}"),
    "antigravity": ("gemini", "\n>\n", "\n> {}\n"),
}
SUFFIX_DRAFTS = (
    (watch.ACCOUNT_LINE, "usage available.\n  Continue where you stopped."),
    (watch.MIDTURN_LINE, "Continue that turn and finish it;\n  do not start over."),
)


class OwnLineGetsItsEnter(Sandbox):
    def setUp(self):
        super().setUp()
        self.seat = {"name": SEAT, "created": 1, "legacy": False, "exited": False}
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(orch, "rulebook_prepare"))
        self.stack.enter_context(patch.object(watch, "time", Clock(lambda _seconds: None)))
        self.stack.enter_context(patch.object(watch, "pane_text", side_effect=lambda *_a, **_kw: self.pane))
        self.stack.enter_context(patch.object(watch, "pane_unread", side_effect=AssertionError(
            "a pending Enter completes its line without gating new text")))
        # Run the real pass list: every other pass is outside this behavior.
        for where, name, _dry in PASSES:
            if name != "finish_own_lines":
                self.stack.enter_context(patch.object(where, name, return_value={}))
        self.keys, self.locked, self.fail_enter = [], False, False
        held = watch.seat_held

        @contextmanager
        def locking(name):
            with held(name) as current:
                self.locked = True
                try:
                    yield current
                finally:
                    self.locked = False

        self.stack.enter_context(patch.object(watch, "seat_held", locking))
        self.compose(watch.ACCOUNT_LINE)

    def compose(self, line, harness="claude"):
        model, empty, row = COMPOSERS[harness]
        config.save_session(self.cfg, SEAT, model, ["astra"], {"cwd": str(self.root)})
        self.base = (REPO / f"tests/fixtures/{harness}-prompt-pane.txt").read_text()
        self.assertIn(empty, self.base)
        if harness == "opencode":
            line = line.replace("\n", "\n┃  ")
        self.pane = self.base.replace(empty, row.format(line)) if line else self.base

    def tmux(self, *args, **kwargs):
        self.assertEqual(args, ("send-keys", "-t", f"={SEAT}:", "Enter"))
        self.assertEqual(kwargs.get("socket"), orch.seat_socket(self.seat))
        self.assertTrue(self.locked, "every Enter holds the typing lock")
        self.keys.append(args[-1])
        if self.fail_enter:
            return 1, "Enter failed"
        self.pane = self.base
        return 0, ""

    def tick(self, dry_run=False):
        for _what, step, also_dry in watch.local_passes({"stalls": {}}, dry_run, lambda _line: None):
            if not dry_run or also_dry:
                step()

    def test_account_line_left_after_its_mark_went_gets_only_enter(self):
        watch.seat_write(SEAT, state="working", midturn=None)
        before = watch.seat_read(SEAT)
        self.tick()
        self.assertEqual(self.keys, ["Enter"])
        self.assertEqual(self.pane, self.base)
        self.assertEqual(watch.seat_read(SEAT), before)
        self.assertFalse(config.seat_file("input", SEAT).exists())
        self.tick()
        self.assertEqual(self.keys, ["Enter"])

    def test_both_recovery_lines_and_stop_nudges_are_recognized_on_captured_composers(self):
        for harness in COMPOSERS:
            lines = [watch.ACCOUNT_LINE, watch.MIDTURN_LINE, "continue"]
            if harness == "codex":
                lines.append(config.manifest(harness)["resume"]["key"])
            for line in lines:
                with self.subTest(harness=harness, line=line):
                    self.keys.clear()
                    self.compose(line, harness)
                    self.assertEqual(watch.composer_holds(SEAT, self.seat, line, self.cfg), "line")
                    self.tick()
                    self.assertEqual(self.keys, ["Enter"])

    def test_an_enter_that_failed_is_finished_by_the_next_tick(self):
        self.fail_enter = True
        pending = self.pane
        self.tick()
        self.assertEqual(self.keys, ["Enter"])
        self.assertEqual(self.pane, pending)
        self.fail_enter = False
        self.tick()
        self.assertEqual(self.keys, ["Enter", "Enter"])
        self.assertEqual(self.pane, self.base)

    def test_full_recovery_lines_wrapped_over_several_rows_get_enter(self):
        for harness in COMPOSERS:
            for line in (watch.ACCOUNT_LINE, watch.MIDTURN_LINE):
                with self.subTest(harness=harness, line=line):
                    self.keys.clear()
                    self.compose("\n  ".join(line[at:at + 26] for at in range(0, len(line), 26)),
                                 harness)
                    self.tick()
                    self.assertEqual(self.keys, ["Enter"])

    def test_other_text_including_owner_edits_is_left_alone(self):
        for line in ("Fix the login redirect", watch.ACCOUNT_LINE[:60],
                     "My note: " + watch.ACCOUNT_LINE, watch.ACCOUNT_LINE + " Wait.",
                     watch.MIDTURN_LINE + "\nAsk me first.", "continue with my draft", ""):
            with self.subTest(line=line):
                self.compose(line)
                before = self.pane
                self.tick()
                self.assertEqual(self.keys, [])
                self.assertEqual(self.pane, before)

    def test_partial_multiline_recovery_lines_are_owner_drafts(self):
        for harness in COMPOSERS:
            for _line, draft in SUFFIX_DRAFTS:
                with self.subTest(harness=harness, draft=draft):
                    self.keys.clear()
                    self.compose(draft, harness)
                    self.tick()
                    self.assertEqual(self.keys, [])

    def test_a_line_edited_to_a_multiline_suffix_before_enter_stays_unsent(self):
        for harness in ("claude", "codex"):
            for line, draft in SUFFIX_DRAFTS:
                with self.subTest(harness=harness, draft=draft):
                    self.keys.clear()
                    self.compose(line, harness)
                    with patch.object(orch, "rulebook_prepare", side_effect=lambda _name:
                                      self.compose(draft, harness)):
                        self.tick()
                    self.assertEqual(self.keys, [])

    def test_a_multiline_suffix_typed_before_the_retry_gets_no_second_enter(self):
        for harness in ("claude", "codex"):
            for line, draft in SUFFIX_DRAFTS:
                with self.subTest(harness=harness, draft=draft):
                    self.keys.clear()
                    self.compose(line, harness)
                    pending = self.pane

                    def held_enter(*args, **kwargs):
                        result = self.tmux(*args, **kwargs)
                        self.pane = pending
                        return result

                    def prepare(_name):
                        if self.keys:
                            self.compose(draft, harness)

                    with patch.object(orch, "tmux_out", side_effect=held_enter), \
                            patch.object(orch, "rulebook_prepare", side_effect=prepare):
                        self.tick()
                    self.assertEqual(self.keys, ["Enter"])

    def test_an_empty_composer_with_an_old_echo_and_an_unreadable_screen_get_no_enter(self):
        for pane in (watch.ACCOUNT_LINE + "\n" + self.base, "", "harness starting"):
            with self.subTest(pane=pane):
                self.pane = pane
                self.tick()
                self.assertEqual(self.keys, [])

    def test_owner_edits_after_the_first_read_win_under_the_lock(self):
        prepare = orch.rulebook_prepare

        def edit(_name):
            self.compose(watch.ACCOUNT_LINE + " Wait.")

        with patch.object(orch, "rulebook_prepare", side_effect=edit):
            self.tick()
        self.assertEqual(self.keys, [])
        prepare.assert_not_called()

    def test_a_dialog_or_an_unanswered_owner_question_holds_the_enter(self):
        pending = self.pane
        self.pane = (REPO / "tests/fixtures/claude-dialog-pane.txt").read_text()
        self.tick()
        self.assertEqual(self.keys, [])
        self.pane = pending
        notice = {"kind": "needs", "text": "Which colour?", "time": 9999,
                  "source": "orchestrator"}
        with patch.object(watch.notify, "last", return_value=notice):
            self.tick()
        self.assertEqual(self.keys, [])

    def test_closed_legacy_and_dry_run_seats_get_no_enter(self):
        self.tick(dry_run=True)
        self.assertEqual(self.keys, [])
        for field in ("legacy", *orch.CLOSED):
            with self.subTest(field=field):
                self.seat[field] = True
                self.tick()
                self.assertEqual(self.keys, [])
                self.seat[field] = False


if __name__ == "__main__":
    unittest.main(verbosity=2)
