"""Under `executor_lines` on `config · limits`, what your tasks of each size took (`ak models
--json`'s `runs.sizes`, tests/test_key_models_json_counts_tasks_by_size.py): a row per hundred
lines, smallest first -- its tasks, from 20 of them the share that went live, and with a line
live each part's hours for every 100 lines live, rounded half to even to a tenth in plain digits
whatever its size, and what its tasks took in all three roles together for every 100 lines live
as money in the config's currency (`-` with no points or an unpriced plan) -- marked `over`
wholly above the limit, off and `no limit` marking none, following → as it raises the limit;
fixed columns where the table fits, folded rows with named numbers where it does not.

The owner's ask of 24 Nov 2026.  Black-box: history.db rows in the Home, `AK_BIN` in a person's
terminal (tests/fixtures/akterm.py), judged by the screen without colour; it fails against
`/bin/false`.
"""

from contextlib import closing
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_json_counts_tasks_by_team import FAILED, history, run
from test_key_models_json_run_usage import TABLES
from test_key_models_json_week_meters import DAY, HOUR, NOW, THEN

MODELS = {"fable": {"harness": "claude", "effort": "xhigh"},
          "astra": {"harness": "codex", "effort": "high"}}

# (first review's lines, tasks live, tasks) filling three sizes: each task spends 1 h build,
# 0.5 h review, 0.25 h checks and 2 h waiting (360 + 720 + 1080 + 5040 = 7200 s)
SIZES = [(25, 16, 20), (150, 19, 19), (350, 0, 20)]
TASKS = [run(f"fix-api-{lines}-{n}", 1 + n / 10, first_review_lines=lines,
             lander_wait_seconds=5040, **({} if n < live else FAILED))
         for lines, live, tasks in SIZES for n in range(tasks)]
HEADING = "What your tasks of each size took, for every 100 lines that went live · last 30 days"
# 1–100's hours over 400 lines live: 20 h build, 10 h review, 5 h checks, 40 h waiting; its
# own tests, 1.25 h, round half to even
TABLE = ["lines    tasks  went live  building  reviewing  own tests  waiting  usage",
         "1–100       20        80%     5.0 h      2.5 h      1.2 h   10.0 h      -",
         "101–200     19",
         "301–400     20         0%                                               -"]
FOLDED_HEADING = ["What your tasks of each size took, for",
                  "every 100 lines that went live · last",
                  "30 days"]
FOLDED = ["1–100  20 tasks",
          "  went live 80%  building 5.0 h",
          "  reviewing 2.5 h  own tests 1.2 h",
          "  waiting 10.0 h  usage -",
          "101–200  19 tasks",
          "301–400  20 tasks  over",
          "  went live 0%  usage -"]


def over(table):
    """`table` with its last row marked `over`."""
    return [*table[:3], f"{table[3]:<{len(table[0]) + 2}}over"]


def with_usage(table, text, last=None):
    """`table` with 1–100's `usage` cell reading `text`, and 301–400's `last` when given."""
    row3 = table[3].rstrip(" -") if last == "" else table[3]
    return [table[0], table[1][:-len(text)] + text, table[2], row3]


def drawn(body, heading=(HEADING,)):
    """A test of the screen: `heading`'s lines, a blank line, then `body` and nothing more."""
    block = [f"  {line}".rstrip() for line in (*heading, "", *body, "")]

    def shows(screen):
        shown = [line.rstrip() for line in screen.split("\n")]
        return any(shown[at:at + len(block)] == block for at in range(len(shown)))
    return shows


def opened(case, home, row, size=(100, 40)):
    """`config · limits` from `c`, in a window of its own, the pointer on `row`."""
    term = Terminal(home, size=size, env={"NO_COLOR": "1"})
    case.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                    server=SERVER)
    term.wait("esc leave")
    term.keys("c")
    term.wait("r recommended")
    term.keys(*["j"] * 7)     # Limits is the eighth row, the two models first.
    term.wait("› Limits")
    term.keys("Enter")
    term.wait("› Review rounds")
    term.keys(*["j"] * {"Review rounds": 0, "Max lines per executor task": 1,
                        "Max lines per orchestrator task": 2,
                        "Findings that end a run for rescoping": 4}[row])
    term.wait(f"› {row}")
    return term


def open_at(case, limit, size=(100, 40), tasks=TASKS):
    """A Home of its own with `tasks` and `executor_lines = limit`, opened on that row."""
    home = Home()
    case.addCleanup(home.close)
    fakeadapter.install(home, claude="pass", codex="pass")
    akconfig.write(home, MODELS, settings={"executor_lines": limit})
    history(home, tasks, [])
    return opened(case, home, "Max lines per executor task", size=size)


def open_used(case, limit, currency="USD", size=(100, 40)):
    """A Home of its own holding TASKS with two roles' usage on 1–100: nova orchestrating 59
    points of Claude Max 20x ($200, €180) split over the 59 tasks (20 points on 1–100), and
    bolt building 12 points of ChatGPT Pro ($200, no euro price) on fix-api-25-0.  In USD,
    (20 + 12) * $200 / 400 * 12 / 52 = $3.69 for every 100 lines live."""
    home = Home()
    case.addCleanup(home.close)
    fakeadapter.install(home, claude="pass", codex="pass")
    akconfig.write(home, MODELS, settings={"executor_lines": limit,
                                           "money": {"currency": currency}},
                   providers={"anthropic": {"mode": "subscription", "accounts": ["default"]},
                              "openai": {"mode": "subscription", "accounts": ["default"]}})
    history(home, TASKS, [])
    week = {"name": "weekly", "used": 50, "window_secs": 7 * DAY, "resets_at": NOW + DAY}
    home.write(".agentkit/state/usage.json", {"fetched_at": NOW, "providers": {
        provider: {"accounts": {"default": {"meters": [week]}}}
        for provider in ("anthropic", "openai")}})
    turn = home.path / ".agentkit/runs/fix-api-25-0/round-1/executor-default"
    turn.mkdir(parents=True)
    (turn / "harness").write_text("codex")
    rows = {"meter_readings": [
        (provider, "default", "weekly", used, THEN + DAY, 7 * DAY, THEN - ago * HOUR, "probe",
         plan, None)
        for provider, plan, rose in (("anthropic", "max 20x", 59), ("openai", "pro", 12))
        for ago, used in ((50, 0), (40, rose))],
        "seat_usage": [("claude:event-0", THEN - 45 * HOUR, 100_000, "default", "nova-7", "nova",
                        "high")],
        "turn_usage": [("fix-api-25-0", "executor", str(turn), "default", "bolt-3",
                        THEN - 45 * HOUR, 100_000, 0, 0, 0)]}
    with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
        for table, items in rows.items():
            db.execute(f"CREATE TABLE {table} ({TABLES[table]})")
            db.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(items[0]))})", items)
    return opened(case, home, "Max lines per executor task", size=size)


def wider(term, width):
    """The lines of `term`'s screen wider than `width`, read as the terminal wrapped none."""
    return [line.rstrip() for line in term.screen(copied=True).splitlines()
            if len(line.rstrip()) > width]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SizeTable(unittest.TestCase):
    def test_at_100_cells_each_size_shows_its_numbers_and_19_tasks_alone(self):
        open_at(self, 300).wait(drawn(over(TABLE)))

    def test_raising_the_limit_past_a_row_clears_its_over_mark(self):
        term = open_at(self, 300)
        term.wait(drawn(over(TABLE)))
        term.keys("Right")            # 300 to 400: 301–400 is no longer wholly above it
        term.wait(drawn(TABLE))

    def test_off_and_no_limit_mark_no_row(self):
        for limit in (0, "no limit"):
            with self.subTest(limit=limit):
                open_at(self, limit).wait(drawn(TABLE))

    def test_at_40_cells_rows_fold_with_named_numbers_and_fit_the_terminal(self):
        term = open_at(self, 200, size=(40, 50))
        shown = term.wait(drawn(FOLDED, FOLDED_HEADING))
        self.assertNotIn("lines    tasks", shown)
        self.assertFalse(wider(term, 40))

    def test_a_huge_hour_is_in_plain_digits_and_a_huge_size_is_cut_to_the_terminal(self):
        # 20 tasks of 2**200 h building each over 25 lines live each: 2**202 h for every 100
        tasks = [run(f"wide-{n}", 1, first_review_lines=25, executor_seconds=2.0**200 * 3600)
                 for n in range(20)]
        tasks.append(run("wide-range", 1, first_review_lines=2 * 10**18))
        term = open_at(self, 300, size=(40, 50), tasks=tasks)
        shown = term.wait("1 of your 21 builds")
        self.assertIn(f"building{2**202}.0h", "".join(shown.split()))
        self.assertIn("\n  1–100  20 tasks\n", shown)   # whole, though the wide size is cut
        self.assertFalse(wider(term, 40))

    def test_usage_of_two_roles_on_priced_plans_reads_money_for_every_100_lines_live(self):
        open_used(self, 300).wait(drawn(over(with_usage(TABLE, "$3.69", last=""))))

    def test_a_plan_with_no_price_reads_a_dash(self):
        # ChatGPT Pro has no euro price, so 1–100's usage reads a dash even beside priced Max 20x
        open_used(self, 300, currency="EUR").wait(drawn(over(with_usage(TABLE, "-", last=""))))

    def test_the_folded_layout_names_usage(self):
        folded = [*FOLDED[:3], "  waiting 10.0 h  usage $3.69", *FOLDED[4:6], "  went live 0%"]
        term = open_used(self, 200, size=(40, 50))
        term.wait(drawn(folded, FOLDED_HEADING))
        self.assertFalse(wider(term, 40))


if __name__ == "__main__":
    unittest.main()
