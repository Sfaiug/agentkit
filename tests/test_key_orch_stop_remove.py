"""`ak orch stop` closes a seat and keeps it; stopping the closed seat again removes it.

The first stop ends the seat's tmux session and writes the owner's stop mark into its seat file,
ending any wait on usage, and keeps its record, its plan and every other file of its own but its
card: its row stays, idle, and its number reopens the conversation where it stopped.  A second
stop removes every file of the seat's own but its locks, the pointers a rename left at old names
and their files too, and leaves only the stop mark, which a hand-back of the seat's runs reads;
then the name answers to nothing.  A record whose session tmux already lost stops the same two
ways.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
its seat a real tmux session from tests/fixtures/akseat.py, and this test fails against
`/bin/false`.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

STATE = ".agentkit/state"
# Every kind of file ak keeps for a seat, as `<kind>-<seat>.<ext>`, but its verification lock.
KINDS = {"log": "txt", "session": "json", "notify": "json", "card": "json", "seat": "json",
         "hook": "json", "plan": "md", "stop": "json", "title": "json", "input": "jsonl",
         "rulebook": "md", "rules": "md", "change": "md", "held": "md", "launch": "sh",
         "refused": "txt", "tell": "json"}


def names(home):
    return {path.name for path in (home.path / STATE).iterdir()}


def seat_file(home, name):
    return json.loads((home.path / STATE / f"seat-{name}.json").read_text())


def stopped(home, name):
    """Stop the seat once, and when the stop mark may say it was."""
    before = time.time()
    done = home.ak("orch", "stop", name)
    # a whole second either way: a build may keep the stamp in whole seconds
    return done, (before - 1, time.time() + 1)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FirstStop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        Seat(cls.home, "acme")
        cls.home.write(f"{STATE}/plan-acme.md", "- [ ] ship the fix\n")
        cls.stop, cls.window = stopped(cls.home, "acme")
        cls.mark = seat_file(cls.home, "acme")

    def test_it_says_the_seat_stopped_and_its_number_reopens_it(self):
        self.assertEqual(self.stop.code, 0, self.stop.err)
        self.assertEqual(self.stop.out, "stopped acme; its number reopens it\n")

    def test_its_tmux_session_is_gone(self):
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=acme").code, 0)

    def test_its_seat_file_says_the_owner_closed_it_then(self):
        self.assertIs(self.mark.get("closed_by_owner"), True)
        self.assertIsInstance(self.mark.get("stopped_at"), (int, float))
        low, high = self.window
        self.assertTrue(low <= self.mark["stopped_at"] <= high, self.mark)

    def test_its_record_and_plan_stay_to_reopen_it(self):
        record = json.loads((self.home.path / STATE / "session-acme.json").read_text())
        self.assertEqual(record.get("conversation"), "conv-acme")
        self.assertIn("plan-acme.md", names(self.home))

    def test_its_row_stays_and_reads_idle(self):
        listed = self.home.ak("orch", "list")
        self.assertEqual(listed.code, 0, listed.err)
        rows = [line for line in listed.out.splitlines() if line.split()[:1] == ["acme"]]
        self.assertEqual(len(rows), 1, listed.out)
        self.assertIn("○ idle", rows[0])

    def test_why_says_the_owner_closed_it_and_how_to_reopen_it(self):
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.err)
        self.assertRegex(why.out, r"(?m)^\s*reason:\s+session closed by the owner: "
                                  r"press 1 to reopen")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SecondStop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        Seat(cls.home, "acme")
        cls.home.write(f"{STATE}/plan-acme.md", "- [ ] ship the fix\n")
        cls.home.write(f"{STATE}/hook-acme.json", {"event": "Stop"})
        first, _ = stopped(cls.home, "acme")
        assert first.code == 0, first.err
        cls.mark = seat_file(cls.home, "acme")
        cls.stop = cls.home.ak("orch", "stop", "acme")

    def test_it_says_the_seat_was_removed(self):
        self.assertEqual(self.stop.code, 0, self.stop.err)
        self.assertEqual(self.stop.out, "removed acme\n")

    def test_its_record_plan_and_hook_are_gone(self):
        left = names(self.home)
        for name in ("session-acme.json", "plan-acme.md", "hook-acme.json"):
            self.assertNotIn(name, left)

    def test_its_seat_file_keeps_only_the_first_stops_mark(self):
        self.assertEqual(seat_file(self.home, "acme"),
                         {"stopped_at": self.mark["stopped_at"], "closed_by_owner": True,
                          "session": "acme"})

    def test_the_list_has_no_seat_left(self):
        listed = self.home.ak("orch", "list")
        self.assertEqual(listed.code, 0, listed.err)
        self.assertTrue(listed.out.startswith("no orchestrator session;"), listed.out)

    def test_a_third_stop_finds_no_seat_by_that_name(self):
        done = self.home.ak("orch", "stop", "acme")
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual(done.err, "ak orch: no orchestrator session 'acme' (running: none)\n")

    def test_a_stop_takes_exactly_one_name(self):
        for args in ((), ("acme", "beta")):
            with self.subTest(args=args):
                done = self.home.ak("orch", "stop", *args)
                self.assertEqual(done.code, 2, done.out)
                self.assertEqual(done.err, "ak orch: usage: ak orch stop <name>\n")


class RecordOnlySeat(unittest.TestCase):
    """beta is a record tmux no longer holds, with one file of every kind; gamma is the pointer
    a rename from gamma to beta left; atoll-beta is another seat whose name ends in beta's."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "beta", alive=False)
        Seat(home, "atoll-beta", alive=False)
        now = time.time()
        for kind, ext in KINDS.items():
            if kind != "session":
                home.write(f"{STATE}/{kind}-beta.{ext}", "{}\n" if "json" in ext else kind)
        home.write(f"{STATE}/seat-beta.json", {
            "usage_wait": {"reason": "acme out of usage", "until": now + 3600, "since": now,
                           "continue": False},
            "usage_refusal": "acme out of usage"})
        home.write(f"{STATE}/session-gamma.json", {"renamed": "beta"})
        home.write(f"{STATE}/plan-gamma.md", "- [ ] ship the fix\n")
        home.write(f"{STATE}/notify-beta.lock", "")
        home.write(f"{STATE}/hook-atoll-beta.json", {"event": "Stop"})
        cls.before = names(home)
        cls.first, cls.window = stopped(home, "beta")
        cls.after_first, cls.mark = names(home), seat_file(home, "beta")
        cls.second = home.ak("orch", "stop", "beta")
        cls.after_second, cls.left = names(home), seat_file(home, "beta")

    def test_a_first_stop_closes_it_and_takes_only_its_card(self):
        self.assertEqual(self.first.code, 0, self.first.err)
        self.assertEqual(self.first.out, "stopped beta; its number reopens it\n")
        self.assertEqual(self.before - self.after_first, {"card-beta.json"})

    def test_the_first_stops_mark_ends_its_wait_on_usage(self):
        self.assertIs(self.mark.get("closed_by_owner"), True)
        low, high = self.window
        self.assertTrue(low <= self.mark.get("stopped_at", 0) <= high, self.mark)
        self.assertIsNone(self.mark.get("usage_wait"))
        self.assertIsNone(self.mark.get("usage_refusal"))
        self.assertEqual(self.mark.get("session"), "beta")

    def test_a_second_stop_takes_every_file_of_its_own_but_its_locks(self):
        self.assertEqual(self.second.code, 0, self.second.err)
        self.assertEqual(self.second.out, "removed beta\n")
        own = {f"{kind}-beta" for kind in KINDS}
        kept = {name for name in self.after_second if name.rpartition(".")[0] in own}
        # a writer may hold a lock or wait on it; which locks a build keeps beside is its own
        self.assertEqual({name for name in kept if not name.endswith(".lock")},
                         {"seat-beta.json"})
        self.assertIn("notify-beta.lock", kept)

    def test_a_second_stop_takes_the_pointer_a_rename_left_and_its_files(self):
        self.assertFalse({"session-gamma.json", "plan-gamma.md"} & self.after_second)

    def test_the_seat_file_keeps_only_the_first_stops_mark(self):
        self.assertEqual(self.left, {"stopped_at": self.mark["stopped_at"],
                                     "closed_by_owner": True, "session": "beta"})

    def test_a_seat_whose_name_ends_in_its_name_keeps_its_files(self):
        self.assertLessEqual({"session-atoll-beta.json", "hook-atoll-beta.json"},
                             self.after_second)


if __name__ == "__main__":
    unittest.main()
