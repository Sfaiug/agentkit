"""A seat's status bar is its row on the `ak` screen, with the line under it always open.

Line one: its word -- `! needs you` alone as a chip, dark bold text on its amber, any other word
in its colour -- the seat's name in bold, the model that orchestrates it, dim, and its progress
line.  Line two: who builds and who reviews and each task in flight as its squares, the key at
its right end; inside a seat its question is on its own screen, so line two never repeats it.
The height is two on every write, so a seat dressed with one line gets its second at its next
redraw and no pane resizes after; the bar is statusbar.py's alone, and no `@ak_runs` tally is
left.  Offline: a temporary HOME, `orch.tmux_out` patched; no tmux runs.
"""

import os
import re
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, menu, notify, orch, run, statusbar, terminal, watch
from agentkit.guard import commands  # noqa: E402
from agentkit import record

NOW = 1_800_000_000
INK = "#11111b"
DIM = terminal.STATE_STYLES["dim"][2]


def drawn(value):
    """An option's text as tmux draws it: styles dropped, the doubled `#` single."""
    return re.sub(r"#\[[^\]]*\]", "", value).replace("##", "#")


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

    def tmux(self, *args, socket=None, **_kw):
        self.calls.append((args, socket))
        for command in commands(args):
            if command[0] == "set-option":
                self.options[command[command.index("-t") + 2]] = command[-1]
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

    def test_a_dressing_a_seat_gives_it_two_lines_in_the_terminal_s_own_colours(self):
        statusbar.dress("fix-api", "fable")
        self.assertEqual(self.options["status"], "2")
        self.assertEqual(self.options["status-style"], "default")     # never tmux's green
        self.assertEqual(self.options["set-titles"], "on")
        self.assertEqual(self.options["status-format[0]"], statusbar.FORMATS[0])
        self.assertEqual(self.options["status-format[1]"], statusbar.FORMATS[1])
        top = self.options[statusbar.TOP]
        self.assertEqual(drawn(top), " fix-api   Fable 5.1")
        self.assertIn("#[bold]fix-api#[nobold]", top)
        self.assertIn(f"#[fg=#{DIM}]Fable 5.1", top)                 # dim, never a company's
        self.assertEqual(drawn(self.options[statusbar.WHY]), "")
        self.assertEqual(drawn(self.options[statusbar.KEY]), "Ctrl-b m  menu ")
        self.assertEqual(self.options["set-titles-string"], "fix-api")
        # ak's own server and this seat's own options, never the server's or another's
        for args, socket in self.calls:
            self.assertEqual(socket, "agentkit-test")
            # beside the read of the other seats it counts, and the click on their names
            if args != statusbar.CLICK and args[0] != "list-sessions":
                self.assertEqual(args[:3], ("set-option", "-t", "=fix-api:"))

    def test_b_a_working_seat_draws_its_word_its_line_and_who_builds_its_tasks(self):
        self.plan(2, 5)
        self.going()
        self.assertEqual(watch.announce_state(self.seat, cfg=self.cfg)["word"], "working")
        top = self.options[statusbar.TOP]
        self.assertTrue(top.startswith(" #[fg=#89b4fa]● working#[default]   #[bold]fix-api"), top)
        # two of five done: the line in working's colour, then its count
        bar = menu.last_column("working", 2, 5, statusbar.CELLS, tmux=True)
        self.assertTrue(top.endswith(f"Fable 5.1#[default]   {bar}"), top)
        self.assertEqual(drawn(top), f" ● working   fix-api   Fable 5.1   {drawn(bar)}")
        # line two is its row's open line: who builds and reviews, and its task building
        self.assertEqual(drawn(self.options[statusbar.WHY]),
                         "  GPT-6-Astra ⚒◎   ■□□")
        self.assertNotIn("going", self.options[statusbar.WHY])      # never a task's name
        self.assertEqual(drawn(self.options[statusbar.KEY]), "Ctrl-b m  menu ")
        self.assertEqual(self.options["set-titles-string"], "fix-api · working")

    def test_c_a_seat_that_needs_you_says_so_loud_and_its_question_stays_on_its_screen(self):
        notify.record("fix-api", "needs", "Merge 50% of #75 first?")
        self.assertEqual(watch.announce_state(self.seat, cfg=self.cfg)["word"], "needs you")
        top, why = self.options[statusbar.TOP], self.options[statusbar.WHY]
        self.assertIn(f"#[fg={INK},bg=#f9e2af,bold] ! needs you #[default]", top)
        self.assertEqual(drawn(top), "  ! needs you    fix-api   Fable 5.1")
        self.assertEqual(drawn(why), "  GPT-6-Astra ⚒◎")
        self.assertNotIn("Merge", "".join(self.options.values()))
        self.assertEqual(drawn(self.options[statusbar.KEY]), "Ctrl-b m  menu ")

    def test_c2_a_seat_waiting_to_land_keeps_its_line(self):
        self.plan(2, 5)
        statusbar.redress(self.seat, {"word": "working",
                                      "reason": "waiting · 3rd in line to land on main"},
                          cfg=self.cfg)
        bar = menu.last_column("working", 2, 5, statusbar.CELLS, tmux=True)
        self.assertTrue(self.options[statusbar.TOP].endswith(f"Fable 5.1#[default]   {bar}"))

    def test_d_a_done_seat_offers_the_menu_key(self):
        top, why, key, title = statusbar.lines("fix-api", "fable", "done", "", "astra builds")
        self.assertIn("#[fg=#a6e3a1]✓ done#[default]", top)
        self.assertEqual(drawn(why), "  astra builds")
        self.assertEqual(drawn(key), "Ctrl-b m  menu ")
        self.assertEqual(title, "fix-api · done")

    def test_e_a_client_short_of_room_keeps_its_tasks_over_who_builds(self):
        versions = statusbar.whys({"crew": (["astra"], ["opus"]), "tasks": [(0, "moving")] * 101})
        self.assertEqual(len(versions), len(statusbar.WHYS))
        self.assertTrue(all("■" in drawn(version) for version in versions), versions)
        # the narrowest, which fits beside the key on a client 40 columns wide: one and a count
        self.assertEqual(drawn(versions[-1]), "■□□  +100")

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
        # a space between the reason and the key; each option drawn as it is, never expanded
        self.assertIn(f"…:{statusbar.WHYS[-1]}}}", bottom)
        self.assertIn(f"}} #[align=right]#{{{statusbar.KEY}}}", bottom)
        self.assertTrue(bottom.endswith(f"#[align=right]#{{{statusbar.KEY}}}"))
        self.assertNotIn("E:", top + bottom)
        self.assertNotIn("E;", top + bottom)

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
