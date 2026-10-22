"""A tick that finds gh logged out writes it down and skips GitHub; no other gh failure does.

Every `ak watch` tick asks GitHub who is logged in before its pull-request passes.  A gh that
says it is logged out is a failure only the owner can fix, so the tick records `gh_out` in
watch.json, when and which seats it holds up, for the menu to say so, and asks GitHub nothing
more; the next tick gh answers clears it.  An outage, or no gh on PATH at all, is no login to
fix: the tick skips the same passes and records nothing, and a logged-out record an earlier
tick made stands until gh answers again.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, against the scripted gh of tests/fixtures/fakegh.py.
"""

import json
import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.fakegh import LOGGED_OUT, OFFLINE, GitHub


def login_probe(call):
    """Asking GitHub who is logged in, the one thing a tick asks before it knows."""
    return call[:1] == ["auth"] or call[:2] == ["api", "user"]


def tick(home, env=None):
    """One tick: how it ended, the gh calls it made and the watch.json it left."""
    asked = len(home.calls("gh"))
    done = home.ak("watch", env=env)
    watch = json.loads((home.path / ".agentkit/state/watch.json").read_text())
    return done, home.calls("gh")[asked:], watch


def without_gh(home):
    """A PATH holding every program the Home's own does, except gh."""
    farm = home.root / "no-gh"
    farm.mkdir()
    for directory in map(Path, home.env["PATH"].split(os.pathsep)):
        for program in sorted(directory.iterdir()) if directory.is_dir() else ():
            link = farm / program.name
            if program.name != "gh" and not os.path.lexists(link):
                link.symlink_to(program)
    return str(farm)


class LoggedOut(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        GitHub(cls.home).reply("", err=LOGGED_OUT, code=4)
        cls.before = time.time()
        cls.out, cls.out_calls, watch = tick(cls.home)
        cls.after = time.time()
        cls.recorded = watch.get("gh_out")
        GitHub(cls.home).reply("", err=OFFLINE, code=1)
        cls.outage, cls.outage_calls, watch = tick(cls.home)
        cls.during = watch.get("gh_out")
        GitHub(cls.home)
        cls.back, cls.back_calls, cls.back_watch = tick(cls.home)

    def test_a_logged_out_tick_records_when_and_that_it_holds_up_no_seat(self):
        self.assertEqual(self.out.code, 0, self.out.err)
        self.assertEqual(sorted(self.recorded or {}), ["at", "seats"], self.recorded)
        self.assertEqual(self.recorded["seats"], [])
        self.assertTrue(self.before <= self.recorded["at"] <= self.after, self.recorded)

    def test_a_logged_out_tick_asks_github_nothing_past_the_login(self):
        self.assertTrue(self.out_calls, "the tick never asked gh who is logged in")
        self.assertTrue(all(map(login_probe, self.out_calls)), self.out_calls)

    def test_an_outage_after_it_leaves_the_record_as_it_was(self):
        self.assertEqual(self.outage.code, 0, self.outage.err)
        self.assertEqual(self.during, self.recorded)
        self.assertTrue(all(map(login_probe, self.outage_calls)), self.outage_calls)

    def test_the_next_tick_gh_answers_clears_it_and_goes_on_to_pull_requests(self):
        self.assertEqual(self.back.code, 0, self.back.err)
        self.assertNotIn("gh_out", self.back_watch)
        self.assertFalse(all(map(login_probe, self.back_calls)), self.back_calls)


class Unavailable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # a Home each: a logout one of them wrongly recorded would stand through the other
        offline, missing = Home(), Home()
        cls.addClassCleanup(offline.close)
        cls.addClassCleanup(missing.close)
        GitHub(offline).reply("", err=OFFLINE, code=1)
        cls.offline, cls.offline_calls, cls.offline_watch = tick(offline)
        GitHub(missing)
        cls.missing, cls.missing_calls, cls.missing_watch = tick(
            missing, {"PATH": without_gh(missing)})

    def test_an_outage_skips_github_and_records_no_logout(self):
        self.assertEqual(self.offline.code, 0, self.offline.err)
        self.assertNotIn("gh_out", self.offline_watch)
        self.assertTrue(self.offline_calls, "the tick never asked gh who is logged in")
        self.assertTrue(all(map(login_probe, self.offline_calls)), self.offline_calls)

    def test_no_gh_on_path_records_no_logout_either(self):
        self.assertEqual(self.missing.code, 0, self.missing.err)
        self.assertEqual(self.missing_calls, [])     # the Home's gh was out of reach
        self.assertNotIn("gh_out", self.missing_watch)


if __name__ == "__main__":
    unittest.main()
