"""A run's step, round and ending rewrite its seat's status bar at once, through the one writer.

Not three minutes later at the next tick: every step a run enters (a new round enters its
executor step again) and every ending rewrites the bar of the seat that launched it, through
`watch.announce_state`, without looking at the seat's screen.  A run without a seat, a legacy
seat and a seat tmux has lost get nothing written, and a writer that fails never reaches the
run.  Offline: fake seats and run records in a temporary HOME, `orch.tmux_out` patched.
"""

import types
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, menu, orch, run, watch
from agentkit import record


class BarFollowsRuns(Sandbox):
    def setUp(self):
        super().setUp()
        repo = config.CODE / "acme"
        (repo / ".git").mkdir(parents=True)
        self.seat = {"name": "acme", "path": str(repo), "created": 1, "attached": False,
                     "exited": False, "legacy": False, "resumable": False}
        other = dict(self.seat, name="fix-api")
        config.save_session(self.cfg, "acme", "fable", ["opus"], {"repo": str(repo), "cwd": str(repo)})
        self.calls = []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.sessions = self.stack.enter_context(
            patch.object(orch, "sessions", return_value=[self.seat, other]))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.look = self.stack.enter_context(patch.object(watch, "look_at"))
        self.pane = self.stack.enter_context(patch.object(watch, "pane_text"))
        self.redress = self.stack.enter_context(patch.object(menu, "redress", wraps=menu.redress))
        self.run_dir = config.RUNS / "20261002-1400-fix-api"
        self.run_dir.mkdir(parents=True)
        self.state = {"run_id": self.run_dir.name, "title": "Fix the api", "state": "running",
                      "verdict": None, "launched_session": "acme", "repo": str(repo),
                      "executor": "opus", "reviewer": "astra", "rounds": 3,
                      "round_summaries": [], "started_at": 1}
        record.save_state(self.run_dir, self.state)
        self.loop = types.SimpleNamespace(
            state=self.state, log=lambda *_a, **_kw: None,
            save=lambda: record.save_state(self.run_dir, self.state))

    def tmux(self, *args, **_kw):
        self.calls.append(args)
        return 0, ""

    def bars(self, name="acme"):
        """The status-left writes that seat's bar got."""
        return [args[-1] for args in self.calls
                if args[:4] == ("set-option", "-t", name, "status-left")]

    def step(self, name):
        run.Loop.step(self.loop, name)

    def test_every_step_rewrites_the_launching_seats_bar_without_a_look(self):
        for count, name in enumerate(("executor", "done-when", "reviewer", "executor", "merge"), 1):
            if count == 4:    # round two begins with its executor step again
                self.state["round_summaries"].append({"round": 1, "summary": "fixed"})
            self.step(name)
            self.assertEqual(record.read_state(self.run_dir)["step"], name)
            self.assertEqual(self.redress.call_count, count)
            self.assertEqual(self.redress.call_args.args[0]["name"], "acme")
            self.assertEqual(len(self.bars()), count)
        self.assertIn("working", self.bars()[-1])
        self.assertEqual(self.bars("fix-api"), [])
        self.look.assert_not_called()
        self.pane.assert_not_called()
        self.assertFalse([args for args in self.calls if args[0] == "capture-pane"])

    def test_an_ending_rewrites_the_bar(self):
        run.mark_state(self.run_dir, "error", error="the api is down")
        self.assertEqual(self.redress.call_count, 1)
        self.assertEqual(self.redress.call_args.args[0]["name"], "acme")
        self.assertEqual(len(self.bars()), 1)

    def test_nothing_is_written_without_a_live_seat_of_ours(self):
        cases = {"no seat": (None, [self.seat]),
                 "legacy seat": ("acme", [dict(self.seat, legacy=True)]),
                 "seat tmux lost": ("acme", [])}
        for case, (launched, seats) in cases.items():
            with self.subTest(case):
                self.calls.clear()
                self.state["launched_session"] = launched
                self.sessions.return_value = seats
                with patch.object(watch, "announce_state") as announce:
                    self.step("reviewer")
                announce.assert_not_called()
                self.assertFalse([args for args in self.calls if args[0] == "set-option"])
                self.assertEqual(record.read_state(self.run_dir)["step"], "reviewer")

    def test_a_failing_writer_never_reaches_the_run(self):
        for fault in (patch.object(watch, "announce_state", side_effect=RuntimeError("boom")),
                      patch.object(orch, "sessions", side_effect=OSError("no tmux"))):
            with self.subTest(str(fault.attribute)), fault:
                self.step("done-when")
                self.assertEqual(record.read_state(self.run_dir)["step"], "done-when")


if __name__ == "__main__":
    unittest.main()
