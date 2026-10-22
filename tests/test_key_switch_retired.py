"""A feature switch on for everyone for two weeks becomes a plan line, to take it out of the code.

This is how a project's `features:` switches get cleaned up: the tick reads the switch list of
each checkout whose AGENTS.md names one, and every switch the list shows on for everyone for 14
days or more is proven, so a seat filed under that project gets an open plan line to remove it,
checked by the list itself: it ticks once the project's deploy stops listing the switch.  A
switch on for everyone whose row gives no `everyone_since` gets a line asking for the date.  The
line goes to the newest seat whose open plan already names the switch, else to the newest seat
at work; a seat at rest is never given one, nor is a seat on another project, and a switch with
no seat to go to waits for a later read.  Black-box: the program `AK_BIN` names runs `ak watch`
and `ak plan` from outside through tests/fixtures/akbin.py, before seats of
tests/fixtures/akseat.py; this test fails against `/bin/false`.
"""

import json
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

DAY = 86400
WORKING, AT_REST = "claude-working-pane.txt", "claude-prompt-pane.txt"


def since(days):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * DAY))


class Project:
    """A checkout under ~/code whose AGENTS.md names a switch list kept outside it, as a deploy
    keeps one: `show` sets what the list answers."""

    def __init__(self, home, name="widgets"):
        self.home, self.list = home, home.root / "deploy" / f"{name}.json"
        tool = home.root / "deploy" / f"{name}-features"
        tool.parent.mkdir(exist_ok=True)
        tool.write_text(f'#!/bin/sh\n[ "$1" = list ] && exec cat {self.list}\nexit 2\n')
        tool.chmod(0o755)
        self.rig = Rig(home, name, files={"AGENTS.md": f"---\nfeatures: {tool}\n---\n# {name}\n"})

    def show(self, *rows):
        self.list.write_text(json.dumps(list(rows)))

    def seat(self, name, screen, *, older=False):
        """A seat filed under the project; `older` opened before one that is not."""
        record = {"repo": str(self.rig.path), "created": int(time.time()) - (900 if older else 600)}
        return Seat(self.home, name, screen=screen, cwd=self.rig.path, record=record)


def plan(home, name):
    """The seat's plan lines, [] before it has one."""
    path = home.path / ".agentkit" / "state" / f"plan-{name}.md"
    return [line for line in path.read_text().splitlines() if line] if path.is_file() else []


def naming(lines, switch):
    word = re.compile(rf"(?<![\w-]){re.escape(switch)}(?![\w-])")
    return [line for line in lines if word.search(line)]


def tick(home):
    done = home.tick()
    assert done.code == 0, done.out + done.err
    return done


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ProvenSwitches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        cls.project = project = Project(home)
        project.show({"id": "fast-search", "everyone": True, "everyone_since": since(15)},
                     {"id": "dark-mode", "everyone": True, "everyone_since": since(13)},
                     {"id": "beta-pay", "everyone": False, "everyone_since": None},
                     {"id": "old-cart", "everyone": True})
        project.seat("acme", WORKING, older=True)
        project.seat("beta", AT_REST)
        other = Rig(home, "gadgets")
        Seat(home, "gamma", screen=WORKING, cwd=other.path, record={"repo": str(other.path)})
        tick(home)
        cls.planned = {name: plan(home, name) for name in ("acme", "beta", "gamma")}
        # the deploy no longer lists it, so the code no longer reads it
        project.show({"id": "old-cart", "everyone": True})
        cls.looked = home.ak("plan", env={"AGENTKIT_SESSION": "acme"})
        cls.after = plan(home, "acme")

    def test_a_switch_on_for_everyone_two_weeks_is_an_open_line_in_the_seat_at_work(self):
        line, = naming(self.planned["acme"], "fast-search")
        self.assertTrue(line.startswith("- [ ] "), line)
        self.assertIn("widgets", line)

    def test_one_on_for_everyone_with_no_date_gets_a_line_asking_for_its_everyone_since(self):
        line, = naming(self.planned["acme"], "old-cart")
        self.assertTrue(line.startswith("- [ ] "), line)
        self.assertIn("everyone_since", line)

    def test_a_switch_on_for_under_two_weeks_or_off_for_everyone_is_not_planned(self):
        for lines in self.planned.values():
            self.assertEqual(naming(lines, "dark-mode") + naming(lines, "beta-pay"), [], lines)
        self.assertEqual(len(self.planned["acme"]), 2, self.planned["acme"])

    def test_a_newer_seat_at_rest_and_a_seat_on_another_project_are_given_none(self):
        self.assertEqual((self.planned["beta"], self.planned["gamma"]), ([], []))

    def test_the_line_ticks_itself_once_the_list_no_longer_shows_the_switch(self):
        self.assertEqual(self.looked.code, 0, self.looked.out + self.looked.err)
        line, = naming(self.after, "fast-search")
        self.assertTrue(line.startswith("- [x] "), line)
        line, = naming(self.after, "old-cart")
        self.assertTrue(line.startswith("- [ ] "), line)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class SwitchInHand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        project = Project(home)
        project.show({"id": "fast-search", "everyone": True, "everyone_since": since(20)})
        project.seat("acme", WORKING)
        project.seat("beta", AT_REST, older=True)
        cls.added = home.ak("plan", "add", "the fast-search switch is gone from the search page",
                            "--check", "test -f search-cleaned.txt",
                            env={"AGENTKIT_SESSION": "beta"})
        tick(home)
        cls.planned = {name: plan(home, name) for name in ("acme", "beta")}

    def test_the_seat_whose_open_plan_names_the_switch_takes_it_even_at_rest(self):
        self.assertEqual(self.added.code, 0, self.added.out + self.added.err)
        self.assertEqual(len(naming(self.planned["beta"], "fast-search")), 2, self.planned)
        self.assertEqual(self.planned["acme"], [])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class NoSeatAtWork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        project = Project(home)
        project.show({"id": "fast-search", "everyone": True, "everyone_since": since(20)})
        seat = project.seat("acme", AT_REST)
        tick(home)
        cls.at_rest = plan(home, "acme")
        seat.show(WORKING)
        # the lists are read hourly: the note of the last read is gone, as an hour on
        (home.path / ".agentkit" / "state" / "retire.json").unlink()
        tick(home)
        cls.at_work = plan(home, "acme")

    def test_a_seat_at_rest_is_never_given_one(self):
        self.assertEqual(self.at_rest, [])

    def test_the_switch_waits_for_a_later_read_and_goes_to_the_seat_once_it_is_at_work(self):
        line, = naming(self.at_work, "fast-search")
        self.assertTrue(line.startswith("- [ ] "), line)


if __name__ == "__main__":
    unittest.main()
