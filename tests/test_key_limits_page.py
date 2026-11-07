"""`c` shows `review_rounds`, `executor_lines` and `orchestrator_lines` on one `Limits` row, at a glance, and
Enter there opens `config · limits`: a row each under a plain name, its value and `default N`
where that is not ak's default, and under the rows the pointed one's meaning, its chart and
what its runs would have done at its value, in that order; off says what it does with no run
too.  ← and → move the pointed one a step (tests/test_key_limits_arrow_steps.py), saved to
config.toml at once, every other key kept; both line limits end with `no limit`, and a save that
fails changes nothing and says why.

The owner's ask of 3 Nov 2026: the keys' names were unclear to users.  Black-box: history.db's
`runs` rows written into the Home, then the program `AK_BIN` names, in a person's terminal
(tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py, judged by
the screen and config.toml.  The terminal has no colour (NO_COLOR).  This test fails against
`/bin/false`.
"""

import calendar
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MODELS = {"fable": {"harness": "claude", "effort": "xhigh"},
          "astra": {"harness": "codex", "effort": "high"}}
NAMES = ("Review rounds", "Max lines per executor task", "Max lines per orchestrator task")
WIDE = max(map(len, NAMES))
FIRST, DAY = calendar.timegm((2026, 10, 1, 12, 0, 0)), 86400
COLUMNS = ("run_id", "repo", "change", "kind", "own_orchestrator", "final_state", "rounds_used",
           "changed_lines", "first_review_lines", "started_at", "finished_at")
# (run_id, change, kind, own_orchestrator, final_state, rounds_used, changed_lines,
# first_review_lines, started): three builds and an orchestrator's own pull request
RUNS = [("20261001-1200-fix-api-1", None, "task", None, "pass", 1, 40, 40, FIRST),
        ("20261002-1200-fix-api-2", None, "task", None, "pass", 3, 350, 350, FIRST + DAY),
        ("20261003-1200-fix-api-3", None, "task", None, "fail", 3, None, 120, FIRST + 2 * DAY),
        ("20261004-1200-review-pr-api-1", "acme/api#1", "seat PR", "fable", "pass", 1, 60, 60,
         FIRST + 3 * DAY)]
# What each limit's lines under the rows say over RUNS, in order: what it means, its chart's
# heading, and what the runs would have done at ak's default and at 0.
SAYS = {"review_rounds": (
            "The review rounds a change has before it goes back to its orchestrator to split or "
            "re-scope.", "how your 4 runs ended, since 1 Oct",
            {3: "1 change (25%) went back to their orchestrator after 3 rounds.",
             0: "Off: no reviewer, so a change lands when its checks pass. None of your runs went "
                "that way, so they can't say how it would go."}),
        "executor_lines": (
            "The most added lines a first review reads.",
            "how often a build passed its first review, by size · 3 builds since 1 Oct",
            {300: "1 of your 3 builds (33%) was 300 lines or more and would have been split. "
                  "Their first review passed 0% of the time, and 50% below 300 lines.",
             0: "Off: executors build nothing, so your runs can't say how that would go."}),
        "orchestrator_lines": (
            "The most added lines an orchestrator builds.",
            "how often an orchestrator's own pull request merged in its first round, by size · "
            "1 since 4 Oct",
            {50: "1 of your orchestrators' 1 own pull requests was 50 lines or more and would have "
                 "been a task. Round 1 merged 100% of them.",
             0: "Off: orchestrators build nothing themselves, so every one of their 1 own pull "
                "request would have been a task."})}
# The same with no run in the history, each limit at 0: its chart says it has none, and what
# off does is still said.
UNRUN = {key: (SAYS[key][0], heading, {0: off}) for key, heading, off in (
    ("review_rounds", "no finished runs yet", SAYS["review_rounds"][2][0]),
    ("executor_lines", "how often a build passed its first review, by size · none yet",
     SAYS["executor_lines"][2][0]),
    ("orchestrator_lines", "how often an orchestrator's own pull request merged in its first "
     "round, by size · none yet", "Off: orchestrators build nothing themselves."))}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def flat(screen):
    """The screen's words, each run of spaces and line ends one space: wrapped words read on."""
    return " ".join(screen.split())


def write_runs(home):
    connection = sqlite3.connect(home.path / ".agentkit/history.db")
    try:
        connection.execute(f"CREATE TABLE runs ({', '.join(map(repr, COLUMNS))})")
        connection.executemany(f"INSERT INTO runs VALUES ({', '.join('?' * len(COLUMNS))})",
                               [(run_id, "acme", *rest, start, start + 3600)
                                for run_id, *rest, start in RUNS])
        connection.commit()
    finally:
        connection.close()


def row(name, value, on=False):
    return f"{'›' if on else ' '} {name:<{WIDE}}  {value}"


# Settings on the settings screen are each shown with ak's default and the board
# numbers it moves [30 Oct 2026]; since 5 Nov 2026, the numbers a limit moves show as its
# chart under it.
@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LimitsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        fakeadapter.install(cls.home, claude="pass", codex="pass")
        write_runs(cls.home)

    def c(self, settings=None, size=(100, 40)):
        """`c` in a window of its own, over a config.toml setting `settings`."""
        akconfig.write(self.home, MODELS, settings=settings)
        return self.opened(size)

    def opened(self, size):
        term = Terminal(self.home, size=size, env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        return term

    def limits(self, term):
        """`config · limits` opened from `c`."""
        term.keys(*["j"] * 30)       # Limits is the last config row.
        term.wait("› Limits")
        term.keys("Enter")
        # the page's own key line, drawn after its rows: the header can read `config · limits`
        # over `c`'s rows while the page reads what it shows
        return term.wait("←→ value")

    def moved(self, term, name, arrows, value):
        """`name` pointed, `arrows` pressed there, once its value reads `value`."""
        term.keys(*["j"] * NAMES.index(name))
        term.wait(f"› {name}")
        term.keys(*arrows)
        return lines(term.wait(lambda screen: any(
            line.startswith(f"› {name:<{WIDE}}  ") and f" {value} " in f"{line} "
            for line in lines(screen))))

    def pointed(self, key, held):
        """`config · limits` over a config.toml setting `key` to `held`, the pointer on its row."""
        name = NAMES[list(SAYS).index(key)]
        term = self.c({key: held})
        self.limits(term)
        term.keys(*["j"] * NAMES.index(name))
        term.wait(f"› {name}")
        return term

    def reads(self, term, key, held, says=SAYS):
        """`key`'s row pointed at `held`: what it means, its chart's heading and what its runs
        would have done there, as `says` has them, show in that order, and no clause naming the
        board rows it moves."""
        meaning, heading, said = says[key]
        parts = (meaning, heading, said[held])
        shown = flat(term.wait(lambda screen: all(part in flat(screen) for part in parts)))
        self.assertEqual(sorted(parts, key=shown.index), list(parts), shown)
        self.assertNotIn("it moves", shown)

    def test_each_limit_says_what_it_means_then_shows_how_your_runs_did(self):
        for key in SAYS:
            for held in SAYS[key][2]:
                with self.subTest(key=key, held=held):
                    self.reads(self.pointed(key, held), key, held)

    def test_with_no_runs_each_limit_off_still_says_what_off_does(self):
        self.home = Home()            # its own, holding no history
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        for key in UNRUN:
            with self.subTest(key=key):
                self.reads(self.pointed(key, 0), key, 0, UNRUN)

    def test_c_shows_one_limits_row_with_the_three_values(self):
        shown = lines(self.c().wait("Limits"))
        self.assertIn("  Limits        review 3 rounds · executor 300 lines · orchestrator 50 "
                      "lines", shown)
        for gone in ("review_rounds", "executor_lines", "orchestrator_lines"):
            self.assertFalse([line for line in shown if line.split()[:1] == [gone]], shown)

    def test_enter_on_limits_opens_the_page_with_the_three_plain_names(self):
        shown = lines(self.limits(self.c({"orchestrator_lines": 0})))
        self.assertIn("agentkit · config · limits", shown[0])
        self.assertEqual([line for line in shown if any(name in line for name in NAMES)],
                         [row(NAMES[0], "◂ 3 ▸", on=True), row(NAMES[1], "300"),
                          row(NAMES[2], "off default 50")])
        self.assertEqual(akconfig.read(self.home)["orchestrator_lines"], 0)

    def test_the_pointer_off_every_row_takes_its_lines_away(self):
        term = self.c()
        self.limits(term)
        term.wait(lambda screen: SAYS["review_rounds"][0] in flat(screen))
        term.type("\x1b[<35;8;1M")      # onto the header: the highlight goes out, and its lines
        term.wait(lambda screen: SAYS["review_rounds"][0] not in flat(screen))

    def test_on_a_narrow_terminal_each_value_folds_under_its_name_never_cut(self):
        shown = lines(self.limits(self.c(
            {"review_rounds": 4, "executor_lines": 1000, "orchestrator_lines": 0}, size=(40, 50))))
        at = shown.index(f"› {NAMES[0]}")
        self.assertEqual(shown[at:at + 6], [
            f"› {NAMES[0]}", "    ◂ 4 ▸ default 3", f"  {NAMES[1]}", "    1000 default 300",
            f"  {NAMES[2]}", "    off default 50"])

    def test_moving_to_1000_lines_per_executor_task_saves_it(self):
        term = self.c({"executor_lines": 900, "max_runs": 7, "custom_flag": True})
        self.limits(term)
        shown = self.moved(term, NAMES[1], ("Right",), "1000")
        self.assertIn(row(NAMES[1], "◂ 1000 ▸ default 300", on=True), shown)
        saved = akconfig.read(self.home)
        self.assertEqual((saved["executor_lines"], saved["max_runs"], saved["custom_flag"]),
                         (1000, 7, True))
        term.keys("Escape")
        term.wait("executor 1000 lines")

    def test_moving_off_lines_per_orchestrator_task_saves_zero(self):
        term = self.c()
        self.limits(term)
        shown = self.moved(term, NAMES[2], ("Left",) * 2, "off")
        self.assertIn(row(NAMES[2], "off ▸ default 50", on=True), shown)
        self.assertEqual(akconfig.read(self.home)["orchestrator_lines"], 0)
        self.reads(term, "orchestrator_lines", 0)

    def test_moving_executors_off_saves_zero_and_explains_who_builds(self):
        term = self.c()
        self.limits(term)
        shown = self.moved(term, NAMES[1], ("Left",) * 3, "off")
        self.assertIn(row(NAMES[1], "off ▸ default 300", on=True), shown)
        self.assertEqual(akconfig.read(self.home)["executor_lines"], 0)
        self.reads(term, "executor_lines", 0)
        term.keys("Escape")
        term.wait("executor off")

    def test_the_second_builder_cannot_be_switched_off(self):
        # the other on its lowest step over 0, so the one ← that would take it to 0 is refused
        for off, target, (key, low) in (("executor_lines", NAMES[2], ("orchestrator_lines", 25)),
                                        ("orchestrator_lines", NAMES[1], ("executor_lines", 100))):
            with self.subTest(off=off):
                term = self.c({off: 0, key: low})
                given = (self.home.path / ".agentkit/config.toml").read_bytes()
                self.limits(term)
                self.moved(term, target, ("Left",), str(low))
                term.wait("cannot both be 0")
                self.assertEqual((self.home.path / ".agentkit/config.toml").read_bytes(), given)

    def test_moving_review_off_saves_zero_and_explains_checks_only(self):
        term = self.c()
        self.limits(term)
        shown = self.moved(term, NAMES[0], ("Left",) * 3, "off")
        self.assertIn(row(NAMES[0], "off ▸ default 3", on=True), shown)
        self.assertEqual(akconfig.read(self.home)["review_rounds"], 0)
        self.reads(term, "review_rounds", 0)
        term.keys("Escape")
        term.wait("review off")

    def test_both_line_limits_end_with_no_limit_and_save_it(self):
        for key, name in zip(("executor_lines", "orchestrator_lines"), NAMES[1:]):
            with self.subTest(key=key):
                term = self.c()
                self.limits(term)
                shown = self.moved(term, name, ("Right",) * 20, "no limit")
                self.assertIn(row(name, "◂ no limit default " + ("300" if key == "executor_lines" else "50"),
                                  on=True), shown)
                self.assertEqual(akconfig.read(self.home)[key], "no limit")
                term.keys("Escape")
                term.wait(("executor" if key == "executor_lines" else "orchestrator") + " no limit")

    def test_a_pick_that_cannot_be_saved_changes_nothing_and_says_why(self):
        term = self.c()
        given = (self.home.path / ".agentkit/config.toml").read_bytes()
        blocked = self.home.path / ".agentkit/config.tmp"
        blocked.mkdir()
        self.addCleanup(blocked.rmdir)
        self.limits(term)
        term.keys("Right")
        shown = lines(term.wait("Is a directory"))
        self.assertIn(row(NAMES[0], "◂ 3 ▸", on=True), shown)
        self.assertEqual((self.home.path / ".agentkit/config.toml").read_bytes(), given)


if __name__ == "__main__":
    unittest.main()
