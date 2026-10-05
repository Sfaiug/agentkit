"""A working seat's bar names what each of its runs is doing now, on line two.

Each run reads `<task id> <a cell per step> <the model doing it> <the step's word> · round N of
M · <time in the step>`; more than two runs on one step, and the runs queued for a slot, are
counts; a line short of room folds whole steps into counts before tmux cuts anything.  Offline
but for the last case, which reads line two the way tmux 3.5a draws it, on a server of its own.
"""

import os
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, menu, orch, record, statusbar, terminal, watch

NOW = 1_800_000_000


def drawn(value):
    """tmux text as tmux draws it: styles dropped, the doubled `#` single."""
    return re.sub(r"#\[[^\]]*\]", "", value).replace("##", "#")


def run(task, step, ago=600, round=1, rounds=3):
    return {"task": task, "step": step, "since": NOW - ago, "round": round, "rounds": rounds,
            "executor": "opus", "reviewer": "astra"}


class LiveLine(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))

    def versions(self, runs):
        return ["".join(said for said, _, _ in version)
                for version in statusbar.live(runs, self.cfg, NOW)]

    def test_a_each_run_names_its_task_its_step_and_the_model_doing_it(self):
        runs = [run("gh2", "building", 180, round=2), run("lg1", "review", 660),
                run("s4a2", "checks", 5580, round=3), run("ln7", "landing", 7200)]
        self.assertEqual(self.versions(runs)[0],
                         "gh2 ■□□□ opus building · round 2 of 3 · 3m   "
                         "s4a2 ■■□□ checking · round 3 of 3 · 1h   "
                         "lg1 ■■■□ astra reviewing · 11m   ln7 ■■■■ landing · 2h")
        parts = statusbar.live(runs, self.cfg, NOW)[0]
        opus, astra = (menu.model_colour(self.cfg, "opus"), menu.model_colour(self.cfg, "astra"))
        self.assertIn(("gh2", None, True), parts)
        self.assertIn(("s4a2", "FAIL", True), parts)     # its last round
        self.assertIn(("■", opus, False), parts)          # the step opus is on, in its colour
        self.assertIn(("opus", opus, False), parts)
        self.assertIn(("astra", astra, False), parts)
        self.assertIn(("■■", "dim", False), parts)        # the steps a run has passed

    def test_b_more_than_two_on_a_step_and_the_queued_are_counts(self):
        runs = [run("a1", "landing", 600), run("a2", "landing", 7200), run("a3", "landing", 60),
                run("b1", "building", 120), run("q1", "waiting"), run("q2", "waiting")]
        self.assertEqual(self.versions(runs)[0],
                         "b1 ■□□□ opus building · 2m   landing 3 · longest 2h   waiting 2")

    def test_c_each_version_folds_one_more_step_the_last_first(self):
        runs = [run("b1", "building", 120), run("c1", "checks", 300), run("r1", "review", 60)]
        self.assertEqual(self.versions(runs), [
            "b1 ■□□□ opus building · 2m   c1 ■■□□ checking · 5m   r1 ■■■□ astra reviewing · 1m",
            "b1 ■□□□ opus building · 2m   c1 ■■□□ checking · 5m   r1 ■■■□ astra reviewing · 1m",
            "b1 ■□□□ opus building · 2m   c1 ■■□□ checking · 5m   reviewing 1 · 1m",
            "b1 ■□□□ opus building · 2m   checking 1 · 5m   reviewing 1 · 1m",
            "building 1 · 2m   checking 1 · 5m   reviewing 1 · 1m",
            "building 1   checking 1   reviewing 1"])
        self.assertEqual(len(statusbar.live(runs, self.cfg, NOW)), len(statusbar.WHYS))

    def test_d_a_seat_s_live_runs_count_its_line_and_its_queue(self):
        def save(name, **state):
            directory = config.RUNS / name
            directory.mkdir(parents=True)
            record.save_state(directory, {"run_id": name, "launched_session": "fix-api",
                                          "task_file": f"/t/{name.split('-')[-1]}-x.md",
                                          "executor": "opus", "reviewer": "astra", **state})
        save("20260101-0900-b1", state="running", step="executor", started_at=NOW - 60)
        save("20260101-0901-l1", state="waiting", waiting_on={"line": ".merge-x.lock",
                                                              "joined": NOW - 3600})
        save("20260101-0902-q1", state="queued", slot_waiting=True, queued_at=NOW - 30)
        save("20260101-0903-c1", state="waiting", waiting_on={"ref": "main"})   # not live
        save("20260101-0904-o1", state="running", step="executor", launched_session="other")
        found = {one["task"]: (one["step"], one["since"]) for one in menu.seat_runs("fix-api")}
        self.assertEqual(found, {"b1": ("building", NOW - 60), "l1": ("landing", NOW - 3600),
                                 "q1": ("waiting", NOW - 30)})
        # a run in the line fills its slot on the tasks bar; a queued one has no step to show
        bar = menu.last_column("working", "", 0, 4, menu.seat_runs("fix-api"), 16)
        self.assertEqual(menu.last_column("working", "", 0, 4, [r for r in menu.seat_runs(
            "fix-api") if r["step"] != "waiting"], 16), bar)


class OnTmux(Sandbox):
    """Line two as tmux 3.5a draws it from the options a write sets, at a client's width."""

    def setUp(self):
        super().setUp()
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        sockets = tempfile.mkdtemp(prefix="ak", dir="/tmp")   # a socket path has a length limit
        self.addCleanup(shutil.rmtree, sockets, ignore_errors=True)
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMUX_TMPDIR": sockets,
            orch.SOCKET_ENV: "live"}))
        os.environ.pop("TMUX", None)
        self.addCleanup(orch.tmux_out, "kill-server")
        self.assertEqual(orch.tmux_out("new-session", "-d", "-s", "fix-api", "sleep 600")[0], 0)

    def line(self, number, width):
        shown = statusbar.FORMATS[number].replace("#{client_width}", str(width))
        rc, out = orch.tmux_out("display-message", "-p", "-t", "=fix-api:", shown)
        self.assertEqual(rc, 0, out)
        return drawn(out)

    def line_two(self, width):
        return self.line(1, width)

    def test_e_a_narrow_client_folds_whole_runs_and_never_cuts_one(self):
        runs = [run("gh2", "building", 180, round=2), run("lg1", "review", 660)]
        versions = statusbar.live(runs, self.cfg, NOW)
        statusbar._write("fix-api", "fable", "working", None, self.cfg, versions)
        key = "Ctrl-b m  menu "
        whole = "  gh2 ■□□□ opus building · round 2 of 3 · 3m   lg1 ■■■□ astra reviewing · 11m"
        self.assertEqual(self.line_two(120).rstrip(), whole + " " + key.rstrip())
        # a client too narrow for both runs folds the one furthest on into its count
        folded = "  gh2 ■□□□ opus building · round 2 of 3 · 3m   reviewing 1 · 11m"
        self.assertTrue(self.line_two(85).startswith(folded + " "), self.line_two(85))
        # one too narrow for any run whole draws only counts, a phone's without their times
        self.assertTrue(self.line_two(60).startswith("  building 1 · 3m   reviewing 1 · 11m "),
                        self.line_two(60))
        self.assertTrue(self.line_two(44).startswith("  building 1   reviewing 1 "),
                        self.line_two(44))
        # a seat that needs you has its reason on every version
        statusbar._write("fix-api", "fable", "needs you", ["Merge #75 first?"] * len(statusbar.BARS),
                         self.cfg)
        self.assertTrue(self.line_two(80).startswith("  Merge #75 first? "), self.line_two(80))

    def test_f_a_line_two_that_fits_is_never_cut_even_to_the_cell(self):
        runs = [run("gh2", "building", 180, round=2), run("lg1", "review", 660)]
        statusbar._write("fix-api", "fable", "working", None, self.cfg,
                         statusbar.live(runs, self.cfg, NOW))
        # the counts alone beside the key, whole, in the cells tmux counts
        least = 2 + sum(int(orch.tmux_out("display-message", "-p", "-t", "=fix-api:",
                                          "#{w:" + option + "}")[1])
                        for option in (statusbar.WHYS[-1], statusbar.KEY))
        for width in range(least - 3, 130):
            shown = self.line_two(width)
            self.assertEqual("…" in shown, width < least, (width, shown))
            self.assertLessEqual(len(shown.rstrip()), width, width)


if __name__ == "__main__":
    unittest.main(verbosity=2)
