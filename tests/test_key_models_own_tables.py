"""`ak models` prints under its boards a line on the team now and a table a role of `own`, as
`--json` gives it (tests/test_key_models_json_own_rows.py): the team now's tasks, those that went
live and per task live the hours they spent and of them waiting; then each role's rows in
`own`'s order, those in use marked, each with its tasks, the share that went live, its role's own
numbers, per task live every hour its tasks spent, and per task live what its model took of its
plans in that role over all its tasks, in money and as a share of a week (the share alone where a
plan it took points of has no price, a dash where it holds no points): a builder's share that
passed its first review and reviews per task, a reviewer's issues per task and the share of them
it took back (false alarms, a dash where it counts none).  A row of fewer than 20 tasks shows its
tasks alone, one with none live neither hours nor usage.  A model is named as every screen names
it at its effort, plain whatever its label holds, by the name its runs kept once no longer
configured or where its label drawn plain is empty.  All three tables print, a history of one
role's former model alone too, the names, tasks and went live standing under each other; where a
table's columns pass the edge every row folds, no column headed: its model's line, then each
number it shows after its column's name, indented, no line passing the edge and no word that fits
cut.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, the
tasks and their reviews written into the Home's history.db as
tests/test_key_models_json_counts_tasks_by_team.py writes them, what they took as
tests/test_key_models_json_run_usage.py writes it; judged by the output and exit code.  Fails
against /bin/false.
"""

from contextlib import closing
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, boards
from test_key_models_json_counts_tasks_by_team import FAILED, history, run
from test_key_models_json_run_usage import TABLES
from test_key_models_json_week_meters import DAY, HOUR, NOW, THEN

# The team now: nova orchestrating at high, bolt building at max, crux reviewing at medium,
# crux's label holding a terminal style, then one left open that, drawn with its effort, would
# take the effort's first letter; echo configured but in no role, its label a style alone
MODELS = {"nova": {"harness": "claude", "label": "Acme Nova 7 Plus"},
          "bolt": {"harness": "codex", "model": "bolt-3", "effort": "max"},
          "crux": {"harness": "codex", "model": "crux-2", "effort": "medium",
                   "label": "\x1b[1mCrux 2\x1b["},
          "echo": {"harness": "codex", "label": "\x1b[2m"}}
# (name, tasks, of them live, the team): the team now's; the same with nova's effort not
# recorded; gale, no longer configured, building; and echo reviewing.  Each task is one run of
# 2.75 hours, one of them waiting.
TEAMS = [("now", 24, 18, {}), ("unrecorded", 20, 5, {"orchestrator_effort": None}),
         ("gale", 19, 10, {"executor": "gale", "executor_effort": "high"}),
         ("echo", 30, 0, {"reviewer": "echo"})]
NOVA = "Acme Nova 7 Plus"
HEADS = {"ORCHESTRATOR": "tasks  went live  per task live  usage per task live",
         "BUILDER": ("tasks  went live  passed 1st review  reviews per task  per task live"
                     "  usage per task live"),
         "REVIEWER": ("tasks  went live  issues per task  false alarms  per task live"
                      "  usage per task live")}
# The team now: the first two teams, 23 of 44 live, 121 hours, 44 of them waiting
TEAM = ["Your team now: 23 of 44 tasks went live,", "5.3 h per task live, 1.9 h of it waiting"]
# The widest page ak draws, on which the three tables fit as columns
WIDE = 120
OWN = [" ".join(TEAM), "",
       f"ORCHESTRATOR{' ' * 13}{HEADS['ORCHESTRATOR']}",
       f"● {NOVA} high     24        75%          3.7 h                    -",
       f"○ {NOVA}          20        25%         11.0 h                    -",
       "",
       f"BUILDER{' ' * 18}{HEADS['BUILDER']}",
       f"■ Bolt 3 max{' ' * 16}44        52%                36%               2.1          5.3 h"
       f"{' ' * 20}-",
       f"□ gale high{' ' * 17}19",
       "",
       f"REVIEWER{' ' * 17}{HEADS['REVIEWER']}",
       f"■ Crux 2[ medium{' ' * 12}44        52%              2.2            0%          5.3 h"
       f"{' ' * 20}-",
       f"□ echo medium{' ' * 15}30         0%              4.0            0%"]
# On 40 cells every row folds: its model's line, then each number it shows after its column's
# name, two to a line where they fit
FOLDED = [*TEAM, "", "ORCHESTRATOR", f"● {NOVA} high",
          "  tasks 24  went live 75%", "  per task live 3.7 h", "  usage per task live -",
          f"○ {NOVA}",
          "  tasks 20  went live 25%", "  per task live 11.0 h", "  usage per task live -",
          "", "BUILDER", "■ Bolt 3 max",
          "  tasks 44  went live 52%", "  passed 1st review 36%", "  reviews per task 2.1",
          "  per task live 5.3 h", "  usage per task live -",
          "□ gale high", "  tasks 19",
          "", "REVIEWER", "■ Crux 2[ medium",
          "  tasks 44  went live 52%", "  issues per task 2.2  false alarms 0%",
          "  per task live 5.3 h", "  usage per task live -",
          "□ echo medium",
          "  tasks 30  went live 0%", "  issues per task 4.0  false alarms 0%"]


def reviews(run_id, n, live):
    """Task `n`'s reviews: a live one's first passes but every fourth's; a failed first finds two
    issues, then one more round passes where the task went live, two fail one each where not."""
    if live and n % 4:
        return [(run_id, 1, "medium")]
    return [(run_id, 1, "medium", "FAIL", 2), *([(run_id, 2, "medium")] if live else [
        (run_id, 2, "medium", "FAIL", 1), (run_id, 3, "medium", "FAIL", 1)])]


def home_of(teams, reviewed=reviews, findings=None):
    """A Home of MODELS, the team now [defaults], whose history holds `teams`' tasks, each
    reviewed as `reviewed` reviews it, and `findings` (history's)."""
    home = Home()
    fakeadapter.install(home, claude="pass", codex="pass")
    akconfig.write(home, MODELS, orchestrator="nova", workers=["bolt"], reviewers=["crux"])
    home.write(".agentkit/state/boards.json", boards())
    runs = [run(f"fix-{name}-{n}", n / 24, **fields, **({} if n < live else FAILED))
            for name, tasks, live, fields in teams for n in range(tasks)]
    history(home, runs, [review for name, tasks, live, _ in teams for n in range(tasks)
                         for review in reviewed(f"fix-{name}-{n}", n, n < live)], findings)
    return home


def used_home():
    """A Home of MODELS whose team now's 20 tasks all went live, having taken, on plans priced as
    tests/test_key_models_json_money.py prices them and recorded as
    tests/test_key_models_json_run_usage.py records them: nova orchestrating 10 points of Max 20x
    ($200, 180 euros), bolt building 3 of ChatGPT's Pro ($200, no euro price) and 4 of its $500
    plan, crux reviewing none."""
    home = home_of([("now", 20, 20, {})])
    logins = {"anthropic": ["default"], "openai": ["default", "second"]}
    week = {"name": "weekly", "used": 50, "window_secs": 7 * DAY, "resets_at": NOW + DAY}
    home.write(".agentkit/state/usage.json", {"fetched_at": NOW, "providers": {
        provider: {"accounts": {account: {"meters": [week]} for account in accounts}}
        for provider, accounts in logins.items()}})
    rows = {"meter_readings": [
        (provider, account, "weekly", used, THEN + DAY, 7 * DAY, THEN - ago * HOUR, "probe",
         plan, None)
        for provider, account, plan, rose in (("anthropic", "default", "max 20x", 10),
                                              ("openai", "default", "pro", 3),
                                              ("openai", "second", "promax", 4))
        for ago, used in ((50, 0), (40, rose))],
        "seat_usage": [("claude:event-0", THEN - 45 * HOUR, 100_000, "default", "nova-7", "nova",
                        "high")],
        "turn_usage": []}
    for account in logins["openai"]:
        turn = home.path / f".agentkit/runs/fix-now-0/round-1/executor-{account}"
        turn.mkdir(parents=True)
        (turn / "harness").write_text("codex")
        rows["turn_usage"].append(("fix-now-0", "executor", str(turn), account, "bolt-3",
                                   THEN - 45 * HOUR, 100_000, 0, 0, 0))
    with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
        for table, items in rows.items():
            db.execute(f"CREATE TABLE {table} ({TABLES[table]})")
            db.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(items[0]))})", items)
    return home


class ModelsOwnTables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home, cls.used = home_of(TEAMS), used_home()
        cls.addClassCleanup(cls.home.close)
        cls.addClassCleanup(cls.used.close)

    def own(self, columns, home=None):
        """What `ak models` prints on `columns` cells from its line on the team now on, every
        line it prints as wide as the terminal at most and none holding a terminal style."""
        done = (home or self.home).ak("models", env={**ENV, "COLUMNS": str(columns)})
        self.assertEqual(done.code, 0, done.err)
        shown = done.out.splitlines()
        self.assertEqual([line for line in shown if len(line) > columns], [], columns)
        self.assertNotIn("\x1b", done.out)
        return shown[next(n for n, line in enumerate(shown) if line.startswith("Your team now")):]

    def took(self, currency="USD"):
        """Each row in use's usage per task live in `self.used`, wide, in `currency`, by its
        model's name's first word."""
        akconfig.write(self.used, MODELS, orchestrator="nova", workers=["bolt"],
                       reviewers=["crux"], settings={"money": {"currency": currency}},
                       providers={"anthropic": {"mode": "subscription", "accounts": ["default"]},
                                  "openai": {"mode": "subscription",
                                             "accounts": ["default", "second"]}})
        return {line.split()[1]: line.split("2.8 h")[1].strip()
                for line in self.own(WIDE, self.used) if line.startswith(("●", "■"))}

    def test_on_a_wide_page_each_role_s_rows_stand_under_their_headings(self):
        shown = self.own(WIDE)
        self.assertEqual(shown, OWN)
        # each table's own columns after the name, tasks and went live, which stand under each
        # other in all three
        self.assertEqual({line.index("went live") for line in shown
                          if line.startswith(tuple(HEADS))}, {32})

    def test_on_40_cells_each_number_follows_its_model_s_line_with_its_name(self):
        self.assertEqual(self.own(40), FOLDED)
        # narrower, a name too wide wraps at its words, and a line's indent gives way before
        # its number is parted from its name
        shown = self.own(22)
        at = shown.index("ORCHESTRATOR")
        self.assertEqual(shown[at:at + 4], ["ORCHESTRATOR", "● Acme Nova 7 Plus", "  high",
                                            "  tasks 24"])
        at = shown.index("BUILDER")
        self.assertEqual(shown[at:at + 5], ["BUILDER", "■ Bolt 3 max", "  tasks 44",
                                            "  went live 52%", " passed 1st review 36%"])

    def test_false_alarms_are_the_share_of_a_reviewer_s_issues_it_took_back(self):
        # crux's 20 tasks each fail once on 2 issues, of the 40 one conceded, one dropped and
        # one upheld; echo's 20 pass at once on none
        def reviewed(run_id, n, live):
            return ([(run_id, 1, "medium", "FAIL", 2), (run_id, 2, "medium")]
                    if run_id.startswith("fix-now") else [(run_id, 1, "medium")])
        findings = [("fix-now-0", "conceded"), ("fix-now-1", "dropped"), ("fix-now-2", "upheld")]
        with home_of([("now", 20, 20, {}), ("echo", 20, 20, {"reviewer": "echo"})], reviewed,
                     findings) as home:
            shown = self.own(WIDE, home)
        self.assertEqual(shown[shown.index(OWN[10]):], [
            OWN[10],
            f"■ Crux 2[ medium{' ' * 12}20       100%              2.0            5%"
            f"          2.8 h{' ' * 20}-",
            f"□ echo medium{' ' * 15}20       100%              0.0             -"
            f"          2.8 h{' ' * 20}-"])

    def test_a_history_of_a_former_builder_alone_prints_all_three_tables(self):
        with home_of(TEAMS[2:3]) as home:
            self.assertEqual(self.own(WIDE, home), [
                "Your team now has no task yet", "",
                OWN[2], f"● {NOVA} high      0", "",
                OWN[6], f"■ Bolt 3 max{' ' * 17}0", OWN[8], "",
                OWN[10], f"■ Crux 2[ medium{' ' * 13}0"])

    def test_a_builder_s_two_priced_plans_read_their_money_and_shares_summed(self):
        # bolt: (3 points * $200 + 4 * $500) / 20 tasks / 100 * 12 / 52, and 7 / 20 points,
        # exactly 0.35, which no float holds
        self.assertEqual(self.took(), {"Acme": "$0.23 · 0.5% of a week",
                                       "Bolt": "$0.30 · 0.4% of a week", "Crux": "-"})

    def test_a_plan_with_no_price_leaves_the_share_alone(self):
        self.assertEqual(self.took("EUR")["Bolt"], "0.4% of a week")

    def test_euros_read_with_the_euro_sign(self):
        self.assertEqual(self.took("EUR")["Acme"], "€0.21 · 0.5% of a week")

if __name__ == "__main__":
    unittest.main()
