"""Once a week ak audits itself: the first tick of an ISO week writes the board with its largest
loss against the vision and the line the `audit` seat is told; each tick after opens that seat
with `[audit]`'s models when none is open and types the line at its quiet prompt, at least
once, until it is delivered.  The owner closing the seat keeps it closed; `[audit].on = false`
runs nothing.

Offline: a temporary HOME holding the shipped default config, a fixed two-week board in place
of the history, and the seat finder, opener and typer faked; nothing starts a seat or tmux.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import audit, config, orch, scoreboard, terminal, usage, watch

NOW = 1_800_000_000.0        # a Friday in 2027-W02, UTC
WEEK = 7 * 86400
REAL_ENSURE = orch.ensure
STATS = {"runs": 10, "merged": 6, "first_round": .5, "unmerged": .3, "hours": 1.0, "tokens": 1000}
BOARD = {
    "products": [STATS, {**STATS, "runs": 8, "merged": 5, "first_round": .6, "unmerged": .2,
                         "hours": 2.0, "tokens": 900}],
    "ak": [None, None], "intent": [None, None], "owner": [None, None], "built": [None, None],
    "waits": [None, None], "merged": [None, None],
    "parks": [{"parked": 1}, {"parked": 0}], "sunk": [None, None],
    "broke": [{"merged": 6, "after_merge": 3, "landing": 0, "unknown": 0},
              {"merged": 5, "after_merge": 3, "landing": 0, "unknown": 0}],
    "size": [None, None],
}
EMPTY = {key: [None, None] for key in BOARD}
BROKE = "merged changes that broke main or live after merge"


class Weekly(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-weekly-audit-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "NO_COLOR": "1"}))
        for name in ("HOME", "STATE", "RUNS", "WT", "WORK", "TMP", "SECRETS", "ENV"):
            self.stack.enter_context(patch.object(config, name, self.root / ".agentkit" / name.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        config.ensure_dirs()
        self.cfg = config.load()
        self.log = []
        self.compute = self.stack.enter_context(patch.object(scoreboard, "compute", return_value=BOARD))
        self.stack.enter_context(patch.object(terminal, "content_width", return_value=200))
        self.closed = self.stack.enter_context(patch.object(watch, "seat_closed_by_owner", return_value=False))
        self.find = self.stack.enter_context(patch.object(orch, "find", return_value=None))
        self.stack.enter_context(patch.object(orch, "records", return_value={}))
        self.ensure = self.stack.enter_context(patch.object(orch, "ensure", return_value=True))
        self.typed = self.stack.enter_context(patch.object(watch, "type_at_prompt", return_value=False))

    def tick(self, now=NOW):
        watch.tell_audit(self.cfg, self.log.append, now)
        return audit.read()

    def test_the_loss_is_the_first_measure_in_the_vision_s_order_that_got_worse(self):
        self.assertEqual(scoreboard.loss(BOARD), ("product runs ended without merging", .3, .2, "%"))
        worse = {**BOARD, "broke": [BOARD["broke"][0], {**BOARD["broke"][1], "after_merge": 2}]}
        self.assertEqual(scoreboard.loss(worse), (BROKE, .5, .4, "%"))
        # nothing worse than the week before: the first measure the board reads at all
        same = {**BOARD, "products": [STATS, STATS], "parks": [{"parked": 0}, {"parked": 0}]}
        self.assertEqual(scoreboard.loss(same), (BROKE, .5, .6, "%"))
        only_size = {**EMPTY, "size": [{"code_lines": 100, "readme_words": 9, "agents_words": 9}, None]}
        self.assertEqual(scoreboard.loss(only_size), ("ak's code lines", 100, None, "n"))
        self.assertIsNone(scoreboard.loss(EMPTY))
        self.assertEqual((scoreboard.said(.3, "%"), scoreboard.said(1.25, "h"),
                          scoreboard.said(1234.0, "n"), scoreboard.said(None, "n")),
                         ("30%", "1.2 hours", "1,234", "not recorded"))
        self.assertEqual(audit.phrase(None), "no loss to name, since no run ended in two weeks")

    def test_the_first_tick_of_a_week_writes_the_report_and_the_line_and_opens_the_seat(self):
        state = self.tick()
        week = audit.week_of(NOW)
        self.assertEqual(week, "2027-W02")
        report = config.STATE / "audit" / f"{week}.md"
        text = report.read_text()
        self.assertTrue(text.startswith(f"# ak's week {week}\n\nScoreboard"), text)
        self.assertIn("products  10 runs ended; 50% merged in round 1", text)
        self.assertTrue(text.endswith("The largest loss is product runs ended without merging, "
                                      "30% against 20% the week before.\n"), text)
        self.assertEqual((state["week"], state["report"], state["typed"], state["delivered"]),
                         (week, str(report), None, None))
        self.assertEqual(state["line"], f"ak's week {week}: the largest loss is product runs ended "
                         f"without merging, 30% against 20% the week before; the board is at {report}. "
                         "Build the smallest change to ak that moves it, through the line. Quality, then speed, then cost: a gain in "
                         "speed or cost while a quality measure gets worse is no win.")
        # no seat and no record: opened with the setting's roles, filed under ak; typed next tick
        self.ensure.assert_called_once_with(self.cfg, "audit", log=self.log.append, saved=False,
                                            roles=config.audit(self.cfg), repo=config.REPO)
        self.assertEqual(self.typed.call_count, 0)
        self.assertEqual(self.log, [f"audit: week {week}'s board is at {report}; the largest loss is "
                                    "product runs ended without merging, 30% against 20% the week before"])
        # the same week again: the board is not computed again and the report stands
        before = report.read_bytes()
        self.tick(NOW + 3600)
        self.assertEqual((self.compute.call_count, report.read_bytes()), (1, before))

    def test_the_line_is_typed_at_the_seat_s_prompt_and_kept_until_delivered(self):
        self.find.return_value = {"name": "audit", "created": 7}
        marks = []

        def typing(seat, text, log, cfg=None, typed=None, receipt=None):
            marks.append(typed)
            if typed is None:
                receipt({"line": text, "seat": 7})   # in the composer, Enter not confirmed
                return False
            return True

        self.typed.side_effect = typing
        state = self.tick()
        self.assertEqual(self.ensure.call_count, 0)
        self.assertEqual((state["typed"], state["delivered"]), ({"line": state["line"], "seat": 7}, None))
        state = self.tick(NOW + 180)
        self.assertEqual((marks, state["delivered"]), ([None, {"line": state["line"], "seat": 7}], NOW + 180))
        self.assertEqual(self.log[-1], "audit: told the audit seat about week 2027-W02")
        self.tick(NOW + 360)
        self.assertEqual(self.typed.call_count, 2)       # delivered: nothing more this week
        # the next week starts over: a new report, a new line, typed again
        state = self.tick(NOW + WEEK)
        self.assertEqual((state["week"], state["delivered"], self.typed.call_count), ("2027-W03", None, 3))
        self.assertTrue((config.STATE / "audit" / "2027-W03.md").exists())

    def test_a_line_typed_and_not_yet_sent_is_finished_before_the_next_week_s(self):
        self.find.return_value = {"name": "audit", "created": 7}
        lines = []

        def typing(seat, text, log, cfg=None, typed=None, receipt=None):
            lines.append((text, typed))
            if typed is None:
                receipt({"line": text, "seat": 7})
                return False
            return True

        self.typed.side_effect = typing
        first = self.tick()["line"]
        state = self.tick(NOW + WEEK)        # its mark, not a new week's line, meets the composer
        self.assertEqual((state["week"], state["delivered"]), ("2027-W02", NOW + WEEK))
        state = self.tick(NOW + WEEK + 180)
        self.assertEqual(state["week"], "2027-W03")
        self.assertEqual(lines, [(first, None), (first, {"line": first, "seat": 7}),
                                 (state["line"], None)])

    def test_a_renamed_seat_is_found_and_left_closed_under_its_new_name(self):
        config.save_session(self.cfg, "audit", "astra", ["opus"], {"cwd": str(self.root)})
        config.rename_session("audit", "weekly")
        self.find.side_effect = lambda name: {"name": name, "created": 7} if name == "weekly" else None
        self.tick()
        self.assertEqual((self.ensure.call_count, self.typed.call_args.args[0]["name"]), (0, "weekly"))
        self.closed.side_effect = lambda name: name == "weekly"
        self.tick(NOW + 180)
        self.assertEqual((self.ensure.call_count, self.typed.call_count), (0, 1))

    def test_a_seat_whose_process_is_gone_is_resumed_and_one_the_owner_closed_waits(self):
        self.find.return_value = {"name": "audit", "exited": True}
        self.tick()
        self.ensure.assert_called_once_with(self.cfg, "audit", log=self.log.append, saved=True,
                                            roles=config.audit(self.cfg), repo=config.REPO)
        self.find.return_value = {"name": "audit", "resumable": True}
        self.tick(NOW + 180)
        self.assertEqual((self.ensure.call_count, self.typed.call_count), (1, 0))
        self.closed.return_value = True
        self.find.return_value = None
        state = self.tick(NOW + 360)
        self.tick(NOW + 540)
        self.assertEqual((self.ensure.call_count, self.typed.call_count, state["held"]), (1, 0, True))
        self.assertEqual(self.log.count("audit: the audit seat was closed by the owner; its "
                                        "line about week 2027-W02 waits for them to open it"), 1)

    def test_off_or_unreadable_runs_nothing(self):
        default = (REPO / config.DEFAULT_CONFIG_NAME).read_text()
        (config.HOME / config.CONFIG_NAME).write_text(default + "\n[audit]\non = false\n")
        self.cfg = config.load()
        self.tick()
        self.assertEqual((self.compute.call_count, audit.read(), self.ensure.call_count), (0, {}, 0))
        (config.HOME / config.CONFIG_NAME).write_text(default + '\n[audit]\norchestrator = "nova"\n')
        self.cfg = config.load()
        self.tick()
        self.assertEqual((self.compute.call_count, audit.read()), (0, {}))
        self.assertIn("WARN the weekly audit is not run: unknown model 'nova'", self.log[-1])

    def test_ensure_with_roles_records_them_for_the_seat_and_remembers_no_default(self):
        self.ensure.side_effect = REAL_ENSURE      # the real one, around faked seats and launches
        remembered = self.stack.enter_context(patch.object(config, "remember_defaults"))
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(orch, "select", side_effect=AssertionError("no selection")))
        self.stack.enter_context(patch.object(orch, "opening_account", return_value=None))
        self.stack.enter_context(patch.object(orch, "fresh_command", return_value=(["harness"], None)))
        self.stack.enter_context(patch.object(orch, "refuse_held"))
        launched = self.stack.enter_context(patch.object(orch, "launch"))
        self.stack.enter_context(patch.object(watch, "forget"))
        roles = {"on": True, "orchestrator": "astra", "workers": ["opus"], "reviewers": ["fable"]}
        self.assertTrue(orch.ensure(self.cfg, "audit", log=self.log.append, roles=roles,
                                    repo=config.REPO))
        record = config.session_records()["audit"]
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"], record["repo"]),
                         ("astra", ["opus"], ["fable"], str(config.REPO)))
        self.assertEqual((remembered.call_count, launched.call_count), (0, 1))
        self.assertEqual(self.log, ["orch: started audit on astra (its setting)"])


if __name__ == "__main__":
    unittest.main()
