"""`ak usage` reads each one-login subscription's meters through its harness, ranks the models
and names the review pair.

A provider that lists no accounts is one login: ak asks its harness for the usual login's
meters and keeps what it reported, a spent gate meter spending the provider.  A harness that
answers an error leaves that error, and its `auth` says whether the login works.  The pick
order ranks the models with room, the most budget first and an unknown one last, a spent
provider's left out, and `review` pairs the first of them with the first on another provider.
A second read within five minutes asks no harness and answers the same, the reading kept in
`~/.agentkit/state/usage.json`.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on
harnesses that are only their meters and log every verb they are asked
(tests/fixtures/meters.py).  Each class opens its own Home and runs only the command it judges.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

# each model's provider, listed in an order the pick does not keep
MODELS = {"bolt": "brine", "cask": "coral", "drum": "dune", "anvil": "acme", "easel": "acme"}
PROVIDERS = sorted({*MODELS.values()})
USED = {"acme": 40, "brine": 70, "dune": 100}    # each week's used%; coral's harness has none
ERROR = "unknown: no meter scripted"    # what the meter fixture answers where no week is set
REPORTED = ("name", "used", "resets_at", "window_secs")
# acme's two by the list between them, brine's less budget after, coral's unknown one last
ORDER = ["anvil", "easel", "bolt", "cask"]
PAIR = {"executor": "anvil", "reviewer": "bolt"}     # easel is on anvil's own provider
# the short headings `ak usage` prints where its full ones do not fit
HEADINGS = ("model(s)", "left", "holds", "month", "resets", "elapsed", "session", "held",
            "room", "budget", "outlook")


def home_on(case):
    """A Home whose models are on four one-login providers, their weeks as `USED` sets."""
    case.home = Home()
    case.addClassCleanup(case.home.close)
    case.meter = meters.install(case.home)
    for provider, used in USED.items():
        case.meter.week(provider, used=used)
    akconfig.write(case.home, {name: {"harness": "echo", "provider": provider}
                               for name, provider in MODELS.items()})


def ak(home, *args):
    done = home.ak(*args)
    assert done.code == 0, done.out + done.err
    return done.out


def answered(meter, provider):
    """What that provider's harness answered: the meters it reported, and its error."""
    if provider not in USED:
        return [], ERROR
    return [{"name": "weekly", "used": USED[provider], "resets_at": meter.resets_at,
             "window_secs": meters.WEEK}], None


def reading(record):
    """A provider's record, as far as it holds what its harness answered."""
    return [{key: meter[key] for key in REPORTED} for meter in record["meters"]], record["error"]


def steady(answer):
    """An answer less each provider's budget: what is left over the part of the window still to
    go, which the clock moves between two reads."""
    return {**answer, "providers": {name: {key: value for key, value in record.items()
                                           if key != "budget"}
                                    for name, record in answer["providers"].items()}}


class Json(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home_on(cls)
        cls.answer = json.loads(ak(cls.home, "usage", "--json"))

    def test_each_harness_is_asked_once_for_its_one_login(self):
        asked = [(provider, account) for verb, provider, account in self.meter.calls()
                 if verb == "usage"]
        self.assertEqual(sorted(asked), [(provider, "default") for provider in PROVIDERS])

    def test_each_record_holds_the_meters_its_harness_reported_and_whether_one_is_spent(self):
        for provider in PROVIDERS:
            with self.subTest(provider):
                record = self.answer["providers"][provider]
                self.assertEqual(reading(record), answered(self.meter, provider))
                spent = [meter["used"] >= 100 for meter in answered(self.meter, provider)[0]]
                self.assertEqual([meter["exhausted"] for meter in record["meters"]], spent)
                self.assertEqual(record["exhausted"], any(spent))

    def test_a_harness_answering_an_error_says_through_auth_whether_its_login_works(self):
        self.assertIs(self.answer["providers"]["coral"]["logged_in"], True)
        self.assertIn(("auth", "coral", "default"), self.meter.calls())

    def test_the_pick_order_ranks_the_models_with_room_and_leaves_the_spent_one_out(self):
        self.assertEqual(self.answer["pick_order"], ORDER)

    def test_review_names_the_pair_python_picks(self):
        self.assertEqual(self.answer["review"], {**PAIR, "self_reviewed": False})


class Cache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home_on(cls)
        cls.first = json.loads(ak(cls.home, "usage", "--json"))
        cls.asked = cls.meter.calls()
        cls.second = json.loads(ak(cls.home, "usage", "--json"))

    def test_a_second_read_asks_no_harness_again_and_answers_the_same(self):
        self.assertEqual(self.meter.calls(), self.asked)
        self.assertEqual(steady(self.second), steady(self.first))

    def test_the_state_file_holds_the_reading(self):
        held = json.loads((self.home.path / ".agentkit/state/usage.json").read_text())
        for provider in PROVIDERS:
            with self.subTest(provider):
                self.assertEqual(reading(held["providers"][provider]),
                                 answered(self.meter, provider))


class Text(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home_on(cls)
        cls.out = ak(cls.home, "usage")

    def test_each_provider_has_its_row(self):
        week = time.strftime("%a %H:%M", time.gmtime(self.meter.resets_at))   # a Home is UTC
        rows = {"acme": ("anvil, easel", "60%", "-", "-", week, "86%", "-", "0", "0.6",
                         "4.2 slack", "on track"),
                "brine": ("bolt", "30%", "-", "-", week, "86%", "-", "0", "0.3", "2.1 slack",
                          "on track"),
                "coral": ("cask", "-", "-", "-", "-", "-", "-", "0", "-", "unknown", "unknown"),
                "dune": ("drum", "0%", "-", "-", week, "86%", "-", "0", "0.0", "0.0 ahead",
                         "exhausted")}
        for provider, row in rows.items():
            with self.subTest(provider):
                self.assertEqual(tuple(meters.cell(self.out, provider, heading)
                                       for heading in HEADINGS), row)

    def test_the_pick_order_and_the_review_pair_have_their_lines(self):
        lines = self.out.splitlines()
        self.assertIn("pick order: " + ", ".join(ORDER), lines)
        self.assertIn(f"review: {PAIR['executor']} by {PAIR['reviewer']}", lines)


if __name__ == "__main__":
    unittest.main()
