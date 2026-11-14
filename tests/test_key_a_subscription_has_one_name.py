"""A subscription is named the same on the ak screen, in `ak usage` and in a page.

The owner (10 Nov 2026): "We want ak to feel like one app."  A subscription is named by its
provider -- its own `name` in config.toml, else its company's, else its key capitalised -- with
a roman numeral when there are several (`Claude II`), never by its key or its account; `ak usage
--json` keeps the keys, for a program to read.
Black-box: the program `AK_BIN` names ticks, prints `ak usage` and draws its menu in a person's
terminal (tests/fixtures/akterm.py), from outside, over two Claude subscriptions and a provider
`acme` that config.toml names `Acme Plan`, their harnesses faked (tests/fixtures/fakeadapter.py),
pages landing in tests/fixtures/sink.py.  This test fails against `/bin/false`.
"""

import json
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, meters
from fixtures.akbin import REAL_TMUX, boxable, Home
from fixtures.akterm import SERVER, Terminal
from fixtures.sink import Sink

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
NAMES = ["Claude I", "Claude II", "Acme Plan"]
WEEK = 604800


def login(ends):
    return json.dumps({"email": None, "ends": ends, "plan": None})


def table(out):
    """The first column of each line `ak usage` printed, where its table's header puts it."""
    lines = out.splitlines()
    head = next(line for line in lines if line.startswith("provider "))
    width = re.match(r"provider\s+", head).end()
    return [line[:width].strip() for line in lines[lines.index(head) + 1:]]


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class OneName(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        reading = json.dumps({"meters": [{"name": "weekly", "used": 40, "window_secs": WEEK,
                                          "resets_at": int(time.time()) + 3 * 86400}]})
        for fake, ends in ((fakes["claude"], None), (fakes["codex"], int(time.time()) + 2 * 86400)):
            fake.answer("login-end", login(ends))
            fake.answer("usage", reading)
        akconfig.write(self.home, {"fable": "claude",
                                   "anvil": {"harness": "codex", "provider": "acme"}},
                       providers={"anthropic": {"mode": "subscription",
                                                "accounts": ["default", "second"]},
                                  "acme": {"mode": "subscription", "name": "Acme Plan"}})
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def test_every_place_names_a_subscription_as_the_screens_do(self):
        self.assertEqual(self.sink.pages(), ["🙋 Needs you · Acme Plan login"])

        done = self.home.ak("usage")
        self.assertEqual(done.code, 0, done.out + done.err)
        rows = table(done.out)
        self.assertEqual(sorted(rows[:3]), sorted(NAMES))
        self.assertEqual([row for row in rows if row in ("anthropic", "acme")], [])

        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        providers = json.loads(done.out)["providers"]
        self.assertEqual(sorted(providers), ["acme", "anthropic"])
        self.assertEqual(sorted(providers["anthropic"]["accounts"]), ["default", "second"])

        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        screen = term.wait(lambda screen: MAIN_KEYS in screen and "Acme Plan" in screen)
        grid = re.findall(r"(\S+(?: \S+)*)  +[━╸─]+  \d+% left", screen)
        self.assertEqual(sorted(grid), sorted(NAMES))


class WideName(unittest.TestCase):
    def test_a_name_of_wide_characters_stays_whole_where_it_fits(self):
        with Home() as home:
            reading = meters.install(home)
            for account in ("default", "second"):
                reading.week("acme", account, used=40)
            akconfig.write(home, {"anvil": {"harness": "echo", "provider": "acme"}},
                           providers={"acme": {"mode": "subscription", "name": "Ａｃｍｅ",
                                               "accounts": ["default", "second"]}})
            home.env["COLUMNS"] = "200"
            done = home.ak("usage")
            self.assertEqual(done.code, 0, done.out + done.err)
            # a wide character takes two cells, so a row's name is read up to its model's column
            self.assertEqual(re.findall(r"(?m)^(\S.*?) +anvil +\d+% ", done.out),
                             ["Ａｃｍｅ I", "Ａｃｍｅ II"])


if __name__ == "__main__":
    unittest.main()
