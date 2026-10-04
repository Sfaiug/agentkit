"""A seat's status bar is two lines in ak's colours, and opens with its state.

Line one: the state as a chip in dark bold text on that state's colour, the seat's name in
bold, `<model> orchestrates` in the model's company colour, and a working seat's tasks bar
without an estimate.  Line two: why it needs you or is done, the key at its right end.  The
height is two on every write, so a seat dressed with one line gets its second at its next
redraw and no pane resizes after; the bar is statusbar.py's alone, and no
`@ak_runs` tally is left.  Offline: a temporary HOME, `orch.tmux_out` patched; no tmux runs.
"""

import os
import re
import subprocess
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, menu, notify, orch, run, statusbar, terminal, watch
from agentkit import record

NOW = 1_800_000_000
INK = "#11111b"


def drawn(value):
    """An option's text as tmux draws it: styles dropped, the doubled `#` and `%` single."""
    return re.sub(r"#\[[^\]]*\]", "", value).replace("##", "#").replace("%%", "%")


class TwoLines(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "acme")
        self.seat = {"name": "fix-api", "repo": self.repo, "path": self.repo, "created": NOW,
                     "attached": False, "exited": False, "legacy": False, "resumable": False}
        config.save_session(self.cfg, "fix-api", "fable", ["astra"],
                            {"repo": self.repo, "cwd": self.repo})
        self.options, self.calls = {}, []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text", return_value="$ "))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))
        # history knows how long a task takes, so the row carries an estimate the bar must not
        self.stack.enter_context(patch.object(menu.history, "estimate_seconds", return_value=600))

    def tmux(self, *args, socket=None, **_kw):
        self.calls.append((args, socket))
        if args[0] == "set-option":
            self.options[args[args.index("-t") + 2]] = args[-1]
        return 0, ""

    def plan(self, done, total):
        config.plan_path("fix-api").write_text(
            "".join(["- [x] done\n"] * done + ["- [ ] todo\n"] * (total - done)))

    def going(self):
        directory = config.RUNS / "20260101-0900-going"
        directory.mkdir(parents=True)
        record.save_state(directory, {"run_id": directory.name, "title": "Task", "state": "running",
                                      "verdict": None, "launched_session": "fix-api",
                                      "reported": False, "repo": self.repo, "executor": "opus",
                                      "reviewer": "astra", "rounds": 2, "round_summaries": [],
                                      "finished_at": None, "started_at": NOW - 600})

    def chip(self, word):
        rgb = "#" + terminal.STATE_STYLES[word][2]
        return f"#[fg={INK},bg={rgb},bold]{terminal.state_text(word)}#[default]"

    def test_a_dressing_a_seat_gives_it_two_lines_in_the_terminal_s_own_colours(self):
        statusbar.dress("fix-api", "fable")
        self.assertEqual(self.options["status"], "2")
        self.assertEqual(self.options["status-style"], "default")     # never tmux's green
        self.assertEqual(self.options["set-titles"], "on")
        self.assertEqual(self.options["status-format[0]"], statusbar.FORMATS[0])
        self.assertEqual(self.options["status-format[1]"], statusbar.FORMATS[1])
        top = self.options[statusbar.TOP]
        self.assertEqual(drawn(top), " fix-api  fable orchestrates")
        self.assertIn("#[bold]fix-api#[nobold]", top)
        self.assertIn("#[fg=#D97757]fable", top)                    # Claude's own colour
        self.assertEqual(drawn(self.options[statusbar.WHY]), "")
        self.assertEqual(drawn(self.options[statusbar.KEY]), "Ctrl-b m  menu ")
        self.assertEqual(self.options["set-titles-string"], "fix-api")
        # ak's own server and this seat's own options, never the server's or another's
        for args, socket in self.calls:
            self.assertEqual(socket, "agentkit-test")
            self.assertEqual(args[:3], ("set-option", "-t", "=fix-api:"))

    def test_b_a_working_seat_opens_with_its_chip_and_draws_its_tasks_bar_without_an_estimate(self):
        self.plan(2, 5)
        self.going()
        self.assertEqual(watch.announce_state(self.seat, cfg=self.cfg)["word"], "working")
        top = self.options[statusbar.TOP]
        self.assertTrue(top.startswith(f" #[fg=#89b4fa]▐{self.chip('working')}"), top)
        bar = f"tasks {terminal.progress_bar(2, 5)}"
        self.assertEqual(drawn(top), f" ▐● working▌  fix-api  fable orchestrates   {bar}")
        info = menu.v5o_seat_info(self.cfg, 1, self.seat, menu.run_records(), {}, {}, NOW)
        self.assertIn("left", menu._last_text(info))                 # the row still has one
        self.assertNotIn("left", top)
        self.assertEqual(self.options[statusbar.WHY], "")
        self.assertEqual(drawn(self.options[statusbar.KEY]), "Ctrl-b m  menu ")
        self.assertEqual(self.options["set-titles-string"], "fix-api · working")

    def test_c_a_seat_that_needs_you_carries_its_question_on_line_two(self):
        notify.record("fix-api", "needs", "Merge 50% of #75 first?")
        self.assertEqual(watch.announce_state(self.seat, cfg=self.cfg)["word"], "needs you")
        top, why = self.options[statusbar.TOP], self.options[statusbar.WHY]
        self.assertIn(self.chip("needs you"), top)
        self.assertEqual(drawn(top), " ▐! needs you▌  fix-api  fable orchestrates")
        # `#` and `%` doubled, so tmux draws them as they were said
        self.assertEqual(why, "  Merge 50%% of ##75 first?")
        self.assertEqual(drawn(self.options[statusbar.KEY]), "Ctrl-b m  menu ")

    def test_d_a_done_seat_carries_its_summary_and_the_close_key(self):
        top, why, key, title = statusbar.lines("fix-api", "fable", "#D97757", "done",
                                               "Merged the parser")
        self.assertIn(self.chip("done"), top)
        self.assertEqual(drawn(why), "  Merged the parser")
        self.assertEqual(drawn(key), "Ctrl-b m  x close ")
        self.assertEqual(title, "fix-api · done")

    def test_e_the_model_is_in_its_company_s_colour_from_the_one_table(self):
        self.assertEqual(statusbar.company(self.cfg, "fable"), menu.COLOURS["anthropic"])
        # ChatGPT's white is the terminal's own foreground: the mirror tone on a light terminal
        self.assertEqual(menu.COLOURS["openai"], "#FFFFFF")
        self.assertEqual(statusbar.company(self.cfg, "astra"), "default")
        with patch.object(terminal, "_LIGHT", True):
            self.assertEqual(terminal.on_background("FFFFFF"), "000000")   # as the usage rows
        # a provider's own `colour` key wins, as on its usage row
        self.cfg["providers"]["anthropic"] = dict(self.cfg["providers"]["anthropic"],
                                                  colour="#123456")
        self.assertEqual(statusbar.company(self.cfg, "fable"), "#123456")
        self.assertEqual(statusbar.company(self.cfg, "no-such-model"),
                         "#" + terminal.STATE_STYLES["working"][2])

    def test_f_a_seat_dressed_with_one_line_gets_two_and_a_legacy_seat_is_never_written(self):
        watch.announce_state(self.seat, cfg=self.cfg)
        self.assertEqual(self.options["status"], "2")     # the height dress sets, never another
        self.assertEqual(self.options["status-format[1]"], statusbar.FORMATS[1])
        self.calls.clear()
        watch.announce_state(dict(self.seat, legacy=True), cfg=self.cfg)
        self.assertEqual([args for args, _ in self.calls if args[0] == "set-option"], [])

    def test_g_each_line_is_cut_on_the_client_drawing_it_and_the_key_stays_whole(self):
        top, bottom = statusbar.FORMATS
        self.assertIn("client_width", top)
        self.assertIn(f"#{{w:{statusbar.KEY}}}", bottom)   # the reason stops short of the key
        # a space between the reason and the key's alignment: a reason's last `#`, single once
        # expanded, would otherwise turn `#[align=right]` into text
        self.assertIn(f"{statusbar.WHY}}} #[align=right]#{{E:{statusbar.KEY}}}", bottom)
        self.assertTrue(bottom.endswith(f"#[align=right]#{{E:{statusbar.KEY}}}"))

    def test_h_the_bar_has_one_home_and_no_run_tally(self):
        for module, name in ((orch, "bar"), (orch, "dress"), (orch, "set_runs"),
                             (orch, "RUNS_OPTION"), (menu, "redress"), (menu, "bar_tally"),
                             (run, "refresh_seat_tally"), (watch, "announce")):
            self.assertFalse(hasattr(module, name), f"{module.__name__}.{name}")
        found = subprocess.run(["git", "-C", str(REPO), "grep", "-n", "@ak_runs", "--",
                                "agentkit", "bin", "hooks", "install.sh"],
                               capture_output=True, text=True).stdout
        self.assertEqual(found, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
