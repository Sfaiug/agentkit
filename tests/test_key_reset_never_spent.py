"""ak never spends a usage-limit reset itself, and a reset in hand is no usage left.

A ChatGPT subscription earns resets that put a spent week back to nothing used; only the owner
spends one, by hand.  ak reads how many each account holds, for the owner to see, and nothing
else: reading the meters, picking a seat's account and a run refused because every week is
spent each leave them where they are, and a held reset adds nothing to an account's headroom or
budget, so a spent week stays spent beside it.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, on a harness that is only its meter and logs every
verb it is asked (tests/fixtures/meters.py).
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# a spent week holding two resets, as `ak usage --json` reads an account
SPENT_HOLDING_TWO = {"resets": 2.0, "exhausted": True, "headroom": 0.0, "budget": 0.0}


def home_on(case, weeks, resets):
    """A Home whose `echo` model is on provider `test`, its accounts the weeks' keys, each
    week `used`% spent and holding the resets given (none unless named)."""
    case.home = Home()
    case.addClassCleanup(case.home.close)
    case.meter = meters.install(case.home, reset=True)
    for account, used in weeks.items():
        case.meter.week("test", account, used=used)
    for account, available in resets.items():
        case.meter.resets(account, available)
    echo = {"harness": "echo", "provider": "test", "model": "echo-1"}
    akconfig.write(case.home, {"echo": echo},
                   providers={"test": {"mode": "subscription", "accounts": list(weeks)}})


def facts(record):
    return {key: record[key] for key in SPENT_HOLDING_TWO}


def read(home, *args):
    done = home.ak(*args)
    assert done.code == 0, done.out + done.err
    return done.out


class NoneSpent:
    def test_the_count_is_read_for_every_account_and_no_reset_is_ever_asked_for(self):
        verbs = [verb for verb, *_ in self.meter.calls()]
        asked = {account for verb, _, account in self.meter.calls() if verb == "reset-status"}
        self.assertEqual(asked, set(self.accounts))
        self.assertNotIn("reset", verbs)


class ResetsInHand(NoneSpent, unittest.TestCase):
    accounts = ("shoal", "reef", "kelp")

    @classmethod
    def setUpClass(cls):
        home_on(cls, {"shoal": 100, "reef": 60, "kelp": 60}, {"shoal": 2, "reef": 2})
        cls.json = json.loads(read(cls.home, "usage", "--json"))["providers"]["test"]
        cls.text = read(cls.home, "usage")
        cls.seat = read(cls.home, "orch", "cr-seat", "--model", "echo", "--dry-run")

    def test_a_reset_in_hand_leaves_a_spent_week_spent(self):
        self.assertEqual(facts(self.json["accounts"]["shoal"]), SPENT_HOLDING_TWO)

    def test_a_reset_in_hand_adds_nothing_to_a_week_with_room(self):
        reef, kelp = self.json["accounts"]["reef"], self.json["accounts"]["kelp"]
        self.assertEqual((reef["resets"], kelp["resets"]), (2.0, 0.0))
        self.assertEqual(reef["headroom"], 0.4)
        self.assertEqual((reef["headroom"], reef["budget"]), (kelp["headroom"], kelp["budget"]))

    def test_ak_usage_shows_the_resets_each_account_holds(self):
        held = {label: meters.cell(self.text, label, "held")
                for label in ("test I", "test II", "test III")}
        self.assertEqual(held, {"test I": "2", "test II": "2", "test III": "0"})

    def test_a_new_seat_opens_on_a_week_with_room_rather_than_the_spent_one(self):
        account = re.match(r"env AGENTKIT_ACCOUNT=(\S*) ", self.seat.splitlines()[-1])
        self.assertIn(account and account[1], ("reef", "kelp"), self.seat)


class EveryWeekSpent(NoneSpent, unittest.TestCase):
    accounts = ("shoal", "reef")

    @classmethod
    def setUpClass(cls):
        home_on(cls, {"shoal": 100, "reef": 100}, {"shoal": 2, "reef": 2})
        rig = Rig(cls.home, "widgets")
        cls.refused = cls.home.ak("run", str(taskfile.write(cls.home, rig.path)), "--no-merge",
                                  timeout=300)
        cls.json = json.loads(read(cls.home, "usage", "--json"))
        cls.seat = read(cls.home, "orch", "cr-seat", "--model", "echo", "--dry-run")

    def test_a_run_with_every_week_spent_parks_with_its_resets_unspent(self):
        self.assertNotEqual(self.refused.code, 0, self.refused.out)
        state = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
        self.assertEqual(state["state"], "exhausted")
        self.assertNotIn("run", [verb for verb, *_ in self.meter.calls()])

    def test_resets_in_hand_leave_every_week_spent(self):
        test = self.json["providers"]["test"]
        self.assertTrue(test["exhausted"])
        for account in self.accounts:
            with self.subTest(account):
                self.assertEqual(facts(test["accounts"][account]), SPENT_HOLDING_TWO)
        self.assertEqual(self.json["pick_order"], [])


if __name__ == "__main__":
    unittest.main()
