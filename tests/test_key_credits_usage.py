"""Credits an account still holds count as usage left, ranked after every window still open.

A subscription whose week is spent but which holds credits (ChatGPT's, or any provider that
reports a balance) is not spent: `ak usage` says how many are left, work and new seats still go
to it, and only after every account and model with a window left, the usual login included,
because the subscription is paid for and credits cost money.  With none left a spent week stays
spent.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
on a harness that is only its meter (tests/fixtures/meters.py).
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

ECHO = {"harness": "echo", "provider": "test", "model": "echo-1"}
SPENT = (100, {})


def home_on(cleanup, weeks, *, models=None):
    """A Home whose models (`echo` on provider `test` unless given) read the weeks given:
    {(provider, account): (used, extras)}; `test` lists its accounts when it has several."""
    home = Home()
    cleanup(home.close)
    meter = meters.install(home)
    for (provider, account), (used, extra) in weeks.items():
        meter.week(provider, account, used=used, **extra)
    listed = [account for provider, account in weeks if provider == "test"]
    akconfig.write(home, models or {"echo": ECHO}, providers={
        "test": {"mode": "subscription", **({"accounts": listed} if len(listed) > 1 else {})}})
    return home


def usage(home):
    done = home.ak("usage", "--json")
    assert done.code == 0, done.err
    return json.loads(done.out)


def shown(home):
    done = home.ak("usage")
    assert done.code == 0, done.err
    return done.out


def seat(home, *model):
    """What a dry run of a new seat prints, its last line the command the seat's pane runs."""
    done = home.ak("orch", "cr-seat", *model, "--dry-run")
    assert done.code == 0, done.out + done.err
    return done.out.splitlines()


class SpentWeekWithCredits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = home_on(cls.addClassCleanup, {("test", "shoal"): SPENT,
                                             ("test", "reef"): (100, {"credits": 12})})
        cls.json, cls.text, cls.seat = usage(home), shown(home), seat(home, "--model", "echo")

    def test_the_account_holding_credits_is_not_spent_and_neither_is_its_provider(self):
        test = self.json["providers"]["test"]
        self.assertEqual((test["exhausted"], test["on_credits"], test["account"]),
                         (False, True, "reef"))
        reef, shoal = test["accounts"]["reef"], test["accounts"]["shoal"]
        self.assertEqual((reef["credits"], reef["on_credits"], reef["exhausted"]),
                         (12, True, False))
        self.assertEqual((shoal["on_credits"], shoal["exhausted"]), (False, True))
        self.assertEqual(self.json["pick_order"], ["echo"])

    def test_ak_usage_says_how_many_are_left_and_that_its_row_is_on_credits(self):
        self.assertIn("test II: 12 credits left", self.text.splitlines())
        self.assertEqual(meters.cell(self.text, "test II", "outlook"), "on credits")
        self.assertEqual(meters.cell(self.text, "test I", "outlook"), "exhausted")

    def test_a_new_seat_opens_on_the_account_holding_credits(self):
        self.assertTrue(self.seat[-1].startswith("env AGENTKIT_ACCOUNT=reef "), self.seat)


class NoCreditsLeft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = home_on(cls.addClassCleanup, {("test", "shoal"): SPENT,
                                             ("test", "reef"): (100, {"credits": 0})})
        cls.json, cls.text, cls.seat = usage(home), shown(home), seat(home, "--model", "echo")

    def test_a_spent_week_with_no_credits_stays_spent(self):
        test = self.json["providers"]["test"]
        self.assertEqual((test["exhausted"], test["on_credits"]), (True, False))
        self.assertEqual(test["accounts"]["reef"]["exhausted"], True)
        self.assertEqual(self.json["pick_order"], [])
        self.assertNotIn("credit", self.text)
        self.assertEqual(meters.cell(self.text, "test II", "outlook"), "exhausted")

    def test_a_new_seat_then_opens_on_the_first_account(self):
        self.assertTrue(self.seat[-1].startswith("env AGENTKIT_ACCOUNT=shoal "), self.seat)


class CreditsGoAfterEveryWindow(unittest.TestCase):
    def test_the_usual_login_with_room_goes_before_an_account_on_credits(self):
        home = home_on(self.addCleanup, {("test", "default"): (60, {}),
                                         ("test", "reef"): (100, {"credits": 12})})
        test = usage(home)["providers"]["test"]
        self.assertEqual((test["account"], test["on_credits"]), ("default", False))
        self.assertEqual(test["accounts"]["reef"]["on_credits"], True)
        self.assertIn("test II: 12 credits left", shown(home).splitlines())
        # the usual login is the one no account is named for
        self.assertTrue(seat(home, "--model", "echo")[-1].startswith("env AGENTKIT_ACCOUNT= "))

    def test_a_model_with_any_window_left_goes_before_one_on_credits(self):
        models = {"echo": ECHO, "ripple": {**ECHO, "provider": "dune", "model": "echo-2"}}
        for dune, order in ((97, ["ripple", "echo"]), (100, ["echo"])):
            with self.subTest(dune_used=dune):
                home = home_on(self.addCleanup, {("test", "default"): (100, {"credits": 12}),
                                                 ("dune", "default"): (dune, {})},
                               models=models)
                self.assertEqual(usage(home)["pick_order"], order)
                # the default orchestrator is passed over, saying why, while ripple has room
                said = next(line for line in seat(home) if line.startswith("orch: "))
                self.assertTrue(said.startswith(f"orch: {order[0]} ("), said)
                self.assertIn("12 credits left", said)


class CreditsInTheirOwnUnit(unittest.TestCase):
    def test_the_note_says_one_credit_money_or_no_bound(self):
        for credits, note in (({"credits": 1}, "test II: 1 credit left"),
                              ({"credits": 12.4, "currency": "USD"},
                               "test II: $12.40 credits left"),
                              ({"credits": "unlimited"}, "test II: unlimited credits")):
            with self.subTest(credits=credits):
                home = home_on(self.addCleanup, {("test", "shoal"): SPENT,
                                                 ("test", "reef"): (100, credits)})
                self.assertIn(note, shown(home).splitlines())
                self.assertEqual(usage(home)["providers"]["test"]["exhausted"], False)


if __name__ == "__main__":
    unittest.main()
