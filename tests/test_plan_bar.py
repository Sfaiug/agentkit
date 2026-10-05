"""A seat's tasks bar moves with each live run's step, and no screen says when the work will finish.

Merged tasks fill solid; each live run fills part of the next slot by its step, dotted; ticks
part the tasks while each has two cells; the count is a chip on the fill, ending at its head, or
past the tasks in flight while the fill is shorter; a last round is red from its first step; a
plan bigger than the bar gives each task in flight a cell.  The rows draw it in the room they
have, never wrapped or cut, and without colour or UTF-8 it reads in plain characters.  Offline:
a throwaway HOME, fake plans and run records, the real renderer.
"""

from contextlib import redirect_stdout
import io
import os
import re
import time
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, history, menu, orch, statusbar, terminal, watch
from agentkit import run as ak_run
from agentkit import record

NOW = 1_800_000_000
WORKING, RED, INK, TRACK, DIM = (terminal.STATE_STYLES["working"][2],
                                 terminal.STATE_STYLES["FAIL"][2], "11111b", "313244",
                                 terminal.STATE_STYLES["dim"][2])


def cells(bar):
    """A tmux-drawn bar, a cell at a time: (glyph, ink, background, bold), and what follows it."""
    found = []
    for ink, back, bold, text in re.findall(r"#\[fg=#(\w+),bg=#(\w+),(\w+)\]([^#]*)", bar):
        found += [(char, ink, back, bold == "bold") for char in text]
    return found, bar.rpartition("#[default]")[2]


def run(step, rnd=1, rounds=3):
    return {"step": step, "round": rnd, "rounds": rounds}


class PlanBar(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "acme")

    def bar(self, done, total, runs, room=28):
        return cells(menu.last_column("working", "", done, total, runs, room, tmux=True))

    def test_merged_solid_runs_dotted_by_step_ticks_and_the_chip_at_the_head(self):
        drawn, after = self.bar(3, 7, [run("review"), run("building")], 28)
        self.assertEqual(len(drawn), 28)
        self.assertEqual(after, "")                     # the count rides the fill
        # seven slots of four cells: three merged, solid in working's colour
        self.assertTrue(all(back == WORKING for _, _, back, _ in drawn[:12]))
        # ... the count a chip of dark bold text on it, ending at the fill's head
        self.assertEqual("".join(char for char, *_ in drawn[7:12]), " 3/7 ")
        self.assertTrue(all(ink == INK and bold for _, ink, _, bold in drawn[7:12]))
        self.assertEqual(drawn[4], ("▏", INK, WORKING, False))        # a tick between merged
        # the run in review fills three quarters of the next slot, the one building a quarter
        fly = [char != " " and ink == WORKING and back == TRACK for char, ink, back, _ in drawn]
        self.assertEqual(fly[12:20], [True, True, True, False, True, False, False, False])
        self.assertEqual([char for char, *_ in drawn[12:16]], ["▏", "▒", "▒", " "])
        # the rest is track, a tick at each task's first cell
        self.assertEqual([n for n, (char, *_) in enumerate(drawn) if char == "▏"],
                         [4, 12, 16, 20, 24])
        self.assertTrue(all(back == TRACK and ink == DIM for _, ink, back, _ in drawn[21:]))

    def test_each_step_fills_its_part_of_a_slot(self):
        for step, lit in (("building", 2), ("checks", 4), ("review", 6), ("landing", 7)):
            with self.subTest(step):
                drawn, _ = self.bar(1, 3, [run(step)], 24)       # slots of eight cells
                self.assertEqual(sum(ink == WORKING for _, ink, *_ in drawn[8:16]), lit)
        # a run's step as the loop records it is one of the four
        self.assertEqual([menu.STEPS[step] for step in ("executor", "done-when", "reviewer",
                                                        "merge")],
                         ["building", "checks", "review", "landing"])

    def test_a_run_on_its_last_round_turns_its_slot_red(self):
        drawn, _ = self.bar(3, 7, [run("review", 3, 3), run("building", 2, 3)], 28)
        self.assertEqual({ink for _, ink, _, _ in drawn[12:15]}, {RED})
        self.assertEqual(drawn[16][1], WORKING)

    def test_a_big_plan_gives_each_task_in_flight_a_cell_of_its_own(self):
        drawn, after = self.bar(127, 143, [run("landing", 3, 3), run("checks")], 24)
        self.assertEqual(len(drawn), 24)
        self.assertNotIn("▏", "".join(char for char, *_ in drawn))   # no room for ticks
        head = max(n for n, (_, _, back, _) in enumerate(drawn) if back == WORKING) + 1
        self.assertEqual(head, 21)
        self.assertEqual("".join(char for char, *_ in drawn[head - 9:head]), " 127/143 ")
        self.assertEqual([(char, ink) for char, ink, _, _ in drawn[head:head + 2]],
                         [("▒", RED), ("▒", WORKING)])
        self.assertEqual(drawn[head + 2][1:3], (DIM, TRACK))
        self.assertEqual(after, "")

    def test_a_fill_shorter_than_the_chip_carries_it_past_the_tasks_in_flight(self):
        for done in (0, 1):
            with self.subTest(done=done):
                drawn, after = self.bar(done, 6, [run("checks")], 24)   # slots of four cells
                self.assertEqual((len(drawn), after), (24, ""))
                flight, chip = 4 * done, 4 * done + 4
                self.assertEqual(sum(ink == WORKING and back == TRACK
                                     for _, ink, back, _ in drawn[flight:chip]), 2)
                self.assertEqual("".join(char for char, *_ in drawn[chip:chip + 5]), f" {done}/6 ")
                self.assertTrue(all(cell[1:] == (INK, WORKING, True)
                                    for cell in drawn[chip:chip + 5]))
        # with nothing merged yet each step still shows, and a last round its red, in any plan
        steps = [self.bar(0, 6, [run(step, 3, 3)], 24)[0] for step in menu.FILLS]
        self.assertEqual(len({str(drawn) for drawn in steps}), len(menu.FILLS))
        for total in (6, 24, 143):
            with self.subTest(total=total):
                self.assertIn(("▒", RED, TRACK, False), self.bar(0, total, [run("building", 3, 3)],
                                                                 24)[0])

    def test_the_count_never_covers_a_task_in_flight(self):
        # every slot in flight, so no room on the fill or past it: the count follows the bar,
        # and the last run's step and its last-round red stay in sight
        for total, room in ((3, 11), (6, 24), (8, 24), (24, 24)):
            for tmux in (True, False):
                with self.subTest(total=total, tmux=tmux), \
                        patch.object(terminal, "colour_depth", return_value=24):
                    ahead = [run("landing")] * (total - 1)
                    bars = [menu.last_column("working", "", 0, total, ahead + [run("building", rnd)],
                                             room, tmux=tmux) for rnd in (2, 3)]
                    self.assertNotEqual(*bars)
                    self.assertIn(RED if tmux else "38;2;243;139;168", bars[1])
                    self.assertTrue(terminal.plain(re.sub(r"#\[[^\]]*\]", "", bars[1]))
                                    .endswith(f" 0/{total}"), bars[1])
        # a plan bigger than the bar keeps the runs on their last round first
        drawn, after = self.bar(0, 40, [run("landing")] * 30 + [run("checks", 3, 3)], 24)
        self.assertIn(("▒", RED, TRACK, False), drawn)
        self.assertEqual(after, " 0/40")

    def test_without_colour_or_utf8_it_reads_in_plain_characters(self):
        runs = [run("review"), run("building")]
        self.assertEqual(menu.last_column("working", "", 3, 7, runs, 20), "███████▒▒▒░░░░░░ 3/7")
        with patch.dict(os.environ, {"LANG": "C", "LC_ALL": ""}):
            self.assertEqual(menu.last_column("working", "", 3, 7, runs, 20),
                             "#######===------ 3/7")
        # a phone's line is all the room there is: its bar takes that and never more
        self.assertEqual(menu.last_column("working", "", 3, 7, runs, 8, narrow=True), "█▒▒░ 3/7")
        self.assertEqual(menu.last_column("working", "", 3, 7, runs, 4, narrow=True), "3/7")
        self.assertEqual(menu.last_column("working", "", 3, 7, runs, 6), "███▒▒░░░ 3/7")
        self.assertEqual(menu.last_column("working", "", 0, 0, runs), "")     # no plan, no bar
        self.assertEqual(menu.last_column("needs you", "Merge first?", 3, 7, runs),
                         "Merge first?")

    def going(self, run_id, owner, ran=0, **extra):
        """A run that seat launched, its first `ran` rounds' directories made as the loop makes
        them when each round's executor starts."""
        directory = config.RUNS / run_id
        directory.mkdir(parents=True)
        for rnd in range(1, ran + 1):
            (directory / f"round-{rnd}").mkdir()
        record.save_state(directory, {
            "run_id": run_id, "title": run_id, "state": "running", "launched_session": owner,
            "repo": self.repo, "executor": "opus", "reviewer": "astra", "rounds": 3,
            "round_summaries": [], "started_at": NOW - 900, **extra})

    def test_a_seats_live_runs_with_their_task_step_round_and_models(self):
        self.going("20261002-1500-fix-ci", "acme-ci", 2, task_file="/t/gh2-fix-ci.md",
                   step="executor", step_at=NOW - 180, round_summaries=[{}])
        self.going("20261002-1501-lint", "acme-ci", 3, task_file="/t/lg1-lint.md",
                   step="reviewer", step_at=NOW - 660, executor="sol", reviewer="opus",
                   round_summaries=[{}, {}])
        self.going("20261002-1502-other", "web-portal", step="merge")
        self.going("20261002-1503-ended", "acme-ci", state="pass")
        self.assertEqual(menu.seat_runs("acme-ci"), [
            {"task": "lg1", "step": "review", "since": NOW - 660, "round": 3, "rounds": 3,
             "executor": "sol", "reviewer": "opus"},
            {"task": "gh2", "step": "building", "since": NOW - 180, "round": 2, "rounds": 3,
             "executor": "opus", "reviewer": "astra"}])

    def test_a_round_its_summary_closed_is_still_that_round(self):
        # landing, waiting on the seat's push, or checked and reviewed again on landing: round
        # two of three is done, and no third has begun, so it is round two and not red
        for n, (step, extra) in enumerate((
                ("merge", {}), ("waiting for the seat's push", {"own_pr_round_pending": 2}),
                ("reviewer", {"review_pending": {"round": 2, "record": False}}),
                ("done-when", {"review_pending": {"round": 2, "record": False}}))):
            with self.subTest(step):
                self.going(f"20261002-150{n}-land", f"acme-{n}", 2, step=step,
                           round_summaries=[{"round": 1}, {"round": 2}], **extra)
                [live] = menu.seat_runs(f"acme-{n}")
                self.assertEqual((live["round"], live["rounds"]), (2, 3))
                drawn, _ = self.bar(2, 6, [live], 24)
                self.assertNotIn(RED, {ink for _, ink, _, _ in drawn})

    def draw(self, width):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(menu, "seat_row_state",
                             return_value={"word": "working", "reason": "", "since": None}), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, [{"name": "acme-ci", "repo": self.repo, "path": self.repo,
                                  "created": NOW}])
        return out.getvalue().splitlines()

    def test_rows_draw_it_in_the_room_they_have_and_no_estimate(self):
        config.save_session(self.cfg, "acme-ci", "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        (config.STATE / "plan-acme-ci.md").write_text("- [x] a\n- [x] b\n- [ ] c\n- [ ] d\n")
        self.going("20261002-1500-fix-ci", "acme-ci", task_file="/t/gh2-fix-ci.md",
                   step="reviewer", step_at=NOW - 60)
        row = next(line for line in self.draw(100) if "acme-ci" in line)
        self.assertRegex(row, r"● working  █+▒+░+ 2/4$")
        self.assertEqual(terminal.cells(row), 100)      # the whole room, to the content's edge
        # under 60 columns the bar goes on its own line, and still takes the room
        lines = self.draw(50)
        tail = lines[next(n for n, line in enumerate(lines) if "acme-ci" in line) + 1]
        self.assertRegex(tail, r"^    █+▒+░+ 2/4$")
        self.assertEqual(terminal.cells(tail), 50)
        for line in self.draw(100) + lines:
            self.assertNotRegex(line, r"~\d+[mhd] left")
        # eleven cells hold the bar and its chip; a column too short for it draws it whole
        # under the row: never wrapped or cut, its colours kept
        info = {"number": "1", "name": "acme-progress-checks", "orchestrator": "gpt-astra",
                "count": "working", "word": "working", "sentence": "", "bar": (0, 6),
                "runs": [run("building")]}
        with patch.object(terminal, "colour_depth", return_value=24):
            [line] = menu.v5o_seat_blocks([info], 60)[0]
            head, under = menu.v5o_seat_blocks([info], 59)[0]
        for drawn, width in ((line, 60), (under, 59)):
            self.assertEqual(terminal.cells(drawn), width)
            self.assertIn("48;2;137;180;250m 0/6 ", drawn)          # the chip, on the fill
        self.assertTrue(terminal.plain(head).endswith("● working"), head)
        self.assertTrue(under.startswith("    "), under)
        self.assertFalse(hasattr(menu, "seat_estimate"))
        self.assertFalse(hasattr(history, "estimate_seconds"))

    def test_a_row_draws_its_last_column_in_the_cells_it_truly_has_left(self):
        # long name and model columns leave fewer than ten cells: neither the bar nor a sentence
        # runs past the edge, and each is there whole or cut with its `…`
        info = {"number": "1", "name": "acme-integration-checks", "orchestrator": "gpt-astra",
                "count": "working", "word": "working", "sentence": "", "bar": (1, 9), "runs": []}
        asks = dict(info, count="needs you", word="needs you", sentence="Merge #75 first?")
        for width in (60, 61, 62, 63, 70):
            for depth in (0, 8, 256, 24):
                with self.subTest(width=width, depth=depth), \
                        patch.object(terminal, "colour_depth", return_value=depth):
                    bar, ask = menu.v5o_seat_blocks([info, asks], width)
                    for line in bar + ask:
                        self.assertLessEqual(terminal.cells(line), width, line)
                    # under ten cells left, each goes under its row, with colour or without
                    free = menu.v5o_column_widths([info, asks], width)["free"]
                    self.assertEqual((len(bar), len(ask)), (2, 2) if free < 10 else (1, 1))
                    self.assertIn("1/9", terminal.plain("".join(bar)))
                    self.assertIn("Merge #75 first?", terminal.plain(" ".join(ask)))

    def test_a_phone_s_tasks_line_never_runs_past_the_screen(self):
        # the line under a narrow row is all the room there is: beside `solo` and a long count
        for width, done, total in ((22, 127, 143), (24, 4999, 9999), (30, 3, 7), (40, 3, 7)):
            info = {"number": "1", "name": "acme", "orchestrator": "sol", "count": "working",
                    "word": "working", "sentence": "", "bar": (done, total), "solo": True,
                    "runs": [run("review", 3, 3)]}
            for depth in (0, 8, 256, 24):
                with self.subTest(width=width, depth=depth), \
                        patch.object(terminal, "colour_depth", return_value=depth):
                    head, tail = menu.v5o_seat_blocks([info], width)[0]
                    self.assertLessEqual(terminal.cells(tail), width, tail)
                    self.assertIn(f"{done}/{total}", terminal.plain(tail))

    def test_a_seat_waiting_to_land_wraps_or_cuts_its_sentence_as_any_row_does(self):
        info = {"number": "1", "name": "acme-ci", "orchestrator": "fable", "count": "working",
                "word": "working", "bar": (0, 6), "runs": [],
                "sentence": "waiting · 3rd in line to land on release/acme-api-integration"}
        self.assertFalse(menu.tasks_bar("working", info["sentence"]))
        self.assertTrue(menu.tasks_bar("working", ""))
        for width in (40, 50, 60, 100):
            with self.subTest(width=width):
                for line in menu.v5o_seat_blocks([info], width)[0]:
                    self.assertLessEqual(terminal.cells(line), width, line)


class FinalRound(Sandbox):
    """A run's last round turns its slot red on the seat's bar and in an open menu at that round's
    first step: before the sandbox sweep and the worker make the round's directory."""

    def test_a_last_round_is_red_from_its_first_step(self):
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        name, repo = "acme-ci", config.CODE / "acme"
        (repo / ".git").mkdir(parents=True)
        config.save_session(self.cfg, name, "fable", ["opus"], {"repo": str(repo), "cwd": str(repo)})
        seat = {"name": name, "repo": str(repo), "path": str(repo), "created": 9000,
                "legacy": False}
        config.plan_path(name).write_text("- [x] a\n- [ ] b\n- [ ] c\n")
        directory = config.RUNS / "20261002-1500-fix-ci"
        for rnd in (1, 2):
            (directory / f"round-{rnd}").mkdir(parents=True)
        state = {"run_id": directory.name, "title": "Fix CI", "state": "running",
                 "launched_session": name, "repo": str(repo), "rounds": 3,
                 "round_summaries": [{"round": 1}, {"round": 2}], "started_at": 9900,
                 "step": "reviewer", "step_at": 9990, "base": "origin/main",
                 "executor": "opus", "reviewer": "astra"}
        record.save_state(directory, state)
        lp = ak_run.Loop(self.cfg, directory, state, None, lambda *a: None, repo, "", [], "", [])
        lp.rnd = 3
        published, seen, last, live = {}, {}, [[], None], menu.Live(self.cfg)

        def tmux(*args, **_kw):
            if args[:1] == ("set-option",):
                published[args[3]] = args[4]
            elif args[:1] == ("run-shell",):
                ak_run.publish_seat(name)              # the job the run hands to tmux, run here
            return 0, ""

        def row(infos):
            return "".join(menu.v5o_seat_blocks(infos, 100)[0])

        def sweep(*_a):
            # the round's first step is out; its directory is not made yet
            self.assertFalse((directory / "round-3").exists())
            time.sleep(menu.STIR + 0.3)             # the open menu has read it again
            seat_top = published.get(statusbar.TOP, "")
            seen.update(bar=f"fg=#{RED}" in seat_top, menu=f"38;2;{rgb(RED)}" in row(last[1][1]))

        class AtWorker(Exception):
            pass

        def worker(_cfg, _model, _body, _cwd, out, *_a, **_kw):
            out.mkdir(parents=True, exist_ok=True)
            raise AtWorker

        with patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(terminal, "colour_depth", return_value=24), \
                patch.object(orch, "sessions", return_value=[seat]), \
                patch.object(orch, "listing", return_value=[seat]), \
                patch.object(menu.Live, "look"), \
                patch.object(history, "open_step"), patch.object(history, "update_run"), \
                patch.object(ak_run, "sweep_sandboxes", side_effect=sweep), \
                patch.object(ak_run, "call_retrying", side_effect=worker), \
                patch.object(ak_run, "history_role_tokens"), patch.object(ak_run, "record_disputes"):
            watch.announce_state(seat, cfg=self.cfg, records=menu.run_records(), now=10000)
            try:
                live.watch(last)
                time.sleep(menu.STIR + 0.1)
                live.drain()
                with self.assertRaises(AtWorker):
                    ak_run.execute(lp, "executor", "Fix CI", "executor")
            finally:
                live.close()
                live.watcher.join(5)
        self.assertEqual(seen, {"bar": True, "menu": True})
        self.assertEqual(menu.seat_runs(name)[0]["round"], 3)


def rgb(hex6):
    """`11aa22` as a truecolour escape's `17;170;34`."""
    return ";".join(str(int(hex6[at:at + 2], 16)) for at in (0, 2, 4))


if __name__ == "__main__":
    unittest.main(verbosity=2)
