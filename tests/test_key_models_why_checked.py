"""⏎ on the models screen says, under a row's cost, how far off the week of each plan of the
provider the row is priced on has foretold, the owner's design of 5 Nov 2026: of each plan, as a
screen names it, how many of the last seven days `ak usage --json`'s `plan_checks` checked it
on, the points its week foretold for them against those its meter rose, and how far high or low
that is, of what it rose; a plan no day checked says so.

Black-box, as tests/test_key_models_why.py: the program `AK_BIN` names in a terminal, the row
priced by finished builds on its provider, and three logins' readings of their week and their
spend written as tests/test_key_week_checked.py writes them; judged by the screen.  Fails against
/bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, lines
from test_key_models_why import DRAWN, MODELS, boards
from test_key_role_cost_from_runs import NOW, History

HOUR, DAY = 3600, 86400
# two weeks' resets, as tests/test_key_week_checked.py reads them; every reading below is hours
# from a day's end
WEEK, LAST_WEEK = NOW + 3 * DAY, NOW - 4 * DAY
# each plan's line, the values' column 11 cells in
CHECKED = {100: ["Max's week, checked on 2 days: it foretold 18 points where its meter rose 12, "
                 "50% high",
                 "Pro's week, checked on 1 day: it foretold 10 points where its meter rose 25, "
                 "60% low",
                 "Team's week: no day checked yet"],
           40: ["Max's week, checked on 2", "days: it foretold 18 points",
                "where its meter rose 12, 50%", "high",
                "Pro's week, checked on 1 day:", "it foretold 10 points where",
                "its meter rose 25, 60% low",
                "Team's week: no day checked", "yet"]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsWhyChecked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n"
                                         "acme-max-5\tAcme Max 5\thigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")
        accounts = {"default": "Max", "second": "Pro", "third": "Team"}
        meter = {"meters": [{"name": "weekly", "used": 40, "window_secs": 7 * DAY,
                             "resets_at": WEEK}]}
        home.write(".agentkit/state/usage.json", {"providers": {
            "anthropic": {"accounts": dict.fromkeys(accounts, meter)}, "openai": meter}})
        home.write(".agentkit/state/logins.json", {"anthropic": {
            account: {"email": f"{account}@acme.test", "ends": None, "plan": plan,
                      "checked_at": NOW} for account, plan in accounts.items()}})
        home.write(".agentkit/state/boards.json", boards(DRAWN))
        # Acme Max 5 high builds, priced at what Acme Mid 5's builds on Anthropic took
        akconfig.write(home, MODELS, orchestrator="crux", workers=["max"], providers={
            "anthropic": {"mode": "subscription", "price": 1300, "accounts": list(accounts)},
            **{provider: {"mode": "subscription", "price": 1300}
               for provider in ("openai", "acme")}})
        cls.history = History(home)
        spent = lambda millions: [[("default", "acme-mid-5", (millions * 1e6, 0, 0, 0))]]
        cls.history.run(("mid", "high"), built=spent(.25))
        cls.history.run(("mid", "high"), "mid", ["high"], built=spent(.75), reviewed=spent(.5))
        # Max: five days ago 20 points for $4, so $20 a week; two days ago 10 for $3 at it,
        # foretold 15; today 2 for $0.70 at 30 points for $7 before it, foretold 3
        cls.read("default", "Max", (0, 138), (4, 132), (20, 126))
        cls.read("default", "Max", (0, 66), (3, 60), (10, 54))
        cls.read("default", "Max", (10, 18), (.7, 12), (12, 6))
        # Pro: five days ago 20 points for $4; a day ago 25 for $2 at it, foretold 10
        cls.read("second", "Pro", (0, 138), (4, 132), (20, 126))
        cls.read("second", "Pro", (0, 42), (2, 36), (25, 30))
        # Team: a day ago 15 points for $3, with no week before it
        cls.read("third", "Team", (0, 42), (3, 36), (15, 30))
        cls.history.save()

    @classmethod
    def read(cls, account, plan, began, bought, ended):
        """The login's week read `began` (used, hours ago) and `ended`, with a seat's row of
        `bought` (dollars, hours ago) between, a million input tokens a dollar."""
        rows = cls.history.rows
        for used, ago in (began, ended):
            rows["meter_readings"].append((
                "anthropic", account, "weekly", used,
                LAST_WEEK if NOW - ago * HOUR < LAST_WEEK else WEEK, 7 * DAY, NOW - ago * HOUR,
                "probe", plan))
        dollars, ago = bought
        rows["seat_usage"].append((f"claude:seat-{len(rows['seat_usage'])}", NOW - ago * HOUR,
                                   dollars * 1e6, account, "acme-mid-5", dollars * 1e6, 0, 0, 0))

    def cost(self, width):
        """The lines of the executor's why under `cost`, `r` on `c` in a window `width` cells
        wide."""
        term = Terminal(self.home, size=(width, 60), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait(" 94.8 ")        # the executor's quality: the answer priced, its row there
        term.keys("Down", "Enter")
        # drawn whole once its own key line, the last, stands under its heading
        shown = lines(term.wait(lambda screen: "\n  why " in screen and lines(
            screen.rstrip())[-1] == "  esc back").rstrip())
        block = shown[next(n for n, line in enumerate(shown) if line.startswith("  cost ")):]
        return block[:block.index("")]

    def test_each_plan_of_its_provider_says_how_far_off_its_week_foretold(self):
        for width, want in CHECKED.items():
            with self.subTest(width=width):
                block = self.cost(width)
                self.assertEqual(block[-len(want):], [" " * 11 + line for line in want], block)


if __name__ == "__main__":
    unittest.main()
