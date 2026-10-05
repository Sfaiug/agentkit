"""A feature switch on for everyone for two weeks is handed to a seat on its project to take out
of the code: the longest-proven one, one at a time until it leaves the list, once per repository.

Offline: a temporary HOME whose ~/code/ACME is a real git repository naming a fake features
command in its AGENTS.md, a script answering `list` from a JSON file beside it and logging each
call; the open seats are faked.  The handed line is read from the seat's `ak tell` queue.
"""

from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, harness, orch, retire, tell

DAY = 86400
NOW = 1_800_000_000.0
FAKE = r"""
import json, sys
from pathlib import Path
here = Path(__file__).parent
with open(here / "calls.log", "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
if (here / "refuse").exists():
    print("no route to the live host", file=sys.stderr)
    sys.exit(1)
print((here / "features.json").read_text())
"""


def stamp(days_ago):
    at = datetime.fromtimestamp(NOW - days_ago * DAY, timezone.utc)
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def row(feature, days_ago=None, everyone=True):
    return {"id": feature, "name": feature, "you": True, "everyone": everyone,
            "you_switchable": True,
            "everyone_since": stamp(days_ago) if days_ago is not None and everyone else None}


class Retire(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-retire-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN": "",
            "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AK_NOTIFY_SINK": "dry-run"}))
        for name in ("HOME", "STATE", "RUNS", "WT", "WORK", "TMP", "SECRETS", "ENV"):
            stack.enter_context(patch.object(config, name, self.root / ".agentkit" / name.lower()))
        stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        config.ensure_dirs()
        self.cfg = config.load()
        self.fake = self.root / "fake"
        self.fake.mkdir()
        (self.fake / "features.py").write_text(FAKE)
        self.acme = self.project("ACME", features=True)
        self.seats = []
        stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [
            dict(seat) for seat in self.seats]))
        self.logged = []

    def project(self, name, features):
        checkout = config.CODE / name
        checkout.mkdir(parents=True)
        front = f"features: {sys.executable} {self.fake / 'features.py'}\n" if features else ""
        (checkout / "AGENTS.md").write_text(f"---\nusers: real\n{front}---\n\n# {name}\n")
        for args in (["init", "-q", "-b", "main"], ["add", "AGENTS.md"],
                     ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
            subprocess.run(["git", "-C", str(checkout), *args], check=True)
        return checkout

    def seat(self, name, checkout, created, **closed):
        config.save_session(self.cfg, name, "opus", ["astra"], {
            "cwd": str(checkout), "conversation": "thread", "id_source": harness.LAUNCHER})
        config.update_session(name, repo=str(checkout) if checkout else None)
        self.seats.append({"name": name, "created": created, "legacy": False, **closed})

    def switches(self, *rows):
        (self.fake / "features.json").write_text(json.dumps(list(rows)))

    def hand(self, at=NOW):
        retire.hand(self.logged.append, now=at)

    def queued(self, name):
        return tell.read(config.seat_file("tell", name))

    def lists(self):
        try:
            return (self.fake / "calls.log").read_text().splitlines().count("list")
        except FileNotFoundError:
            return 0

    def test_the_longest_proven_switch_goes_to_the_newest_open_seat_on_its_project(self):
        self.seat("acme-old", self.acme, created=10)
        self.seat("acme-new", self.acme, created=30)
        self.seat("acme-gone", self.acme, created=50, exited=True)
        other = self.project("OTHER", features=False)
        self.seat("other", other, created=90)
        self.switches(row("fresh", 13), row("hidden", everyone=False), row("old", 40),
                      row("older", 60), {**row("unstamped"), "everyone_since": None})
        self.hand()
        self.assertEqual(self.queued("acme-old") + self.queued("other"), [])
        [message] = self.queued("acme-new")
        self.assertIn("In ACME, the `older` switch has been on for everyone since", message["line"])
        self.assertIn("Take it out of ACME's code", message["line"])
        self.assertEqual(tell.source(message["from"]), "ak")
        self.assertIn("ACME: switch older is proven; handed to acme-new", self.logged)

    def test_one_at_a_time_until_it_leaves_the_list_then_the_next(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("older", 60), row("old", 40))
        self.hand()
        self.hand(NOW + 2 * retire.EVERY)
        self.assertEqual(len(self.queued("acme")), 1)
        self.switches(row("old", 40))
        self.hand(NOW + 3 * retire.EVERY)
        lines = [message["line"] for message in self.queued("acme")]
        self.assertEqual(len(lines), 2)
        self.assertIn("`old` switch", lines[1])

    def test_one_still_listed_a_day_after_is_handed_again(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("older", 60))
        self.hand()
        self.hand(NOW + retire.AGAIN - 1)
        self.assertEqual(len(self.queued("acme")), 1)
        self.hand(NOW + retire.AGAIN + retire.EVERY)
        self.assertEqual([("`older` switch" in m["line"]) for m in self.queued("acme")],
                         [True, True])

    def test_the_switch_in_hand_is_handed_again_before_an_older_one_listed_since(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        self.hand()
        self.switches(row("first", 40), row("newer-listed", 60))
        self.hand(NOW + retire.AGAIN)
        self.switches(row("newer-listed", 60))
        self.hand(NOW + retire.AGAIN + retire.EVERY)
        self.assertEqual([message["line"].split("`")[1] for message in self.queued("acme")],
                         ["first", "first", "newer-listed"])

    def test_one_turned_off_after_it_was_handed_stays_in_hand_until_it_leaves_the_list(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 60), row("second", 40))
        self.hand()
        self.switches(row("first", everyone=False), row("second", 40))
        self.hand(NOW + retire.EVERY)
        self.hand(NOW + retire.AGAIN)
        self.switches(row("second", 40))
        self.hand(NOW + retire.AGAIN + retire.EVERY)
        lines = [message["line"] for message in self.queued("acme")]
        self.assertEqual([line.split("`")[1] for line in lines], ["first", "first", "second"])
        self.assertEqual(lines[0], lines[1])

    def test_an_unread_record_hands_nothing(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        self.hand()
        self.switches(row("first", 40), row("newer-listed", 60))
        retire.path().write_text("[]")
        with self.assertRaises(ValueError):
            self.hand(NOW + retire.AGAIN)
        self.assertEqual(len(self.queued("acme")), 1)

    def test_a_stamp_without_an_offset_is_utc_and_a_line_too_long_is_not_handed(self):
        self.seat("acme", self.acme, created=10)
        unmarked = {**row("unmarked", 60), "everyone_since": stamp(60).removesuffix("Z")}
        self.switches(unmarked, row("x" * 900, 90))
        self.hand()
        self.assertTrue(any(line.startswith(f"WARN ACME: switch {'x' * 900} was not handed: ")
                            and "more than a composer shows whole" in line
                            for line in self.logged))
        self.assertEqual(self.queued("acme"), [])
        self.switches(unmarked)
        self.hand(NOW + retire.EVERY)
        [message] = self.queued("acme")
        self.assertIn("`unmarked` switch", message["line"])

    def test_a_record_that_cannot_be_written_hands_nothing(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        replace = Path.replace

        def refused(source, target):
            if Path(target) == retire.path():
                raise PermissionError("read-only")
            return replace(source, target)

        with patch.object(Path, "replace", refused), self.assertRaises(PermissionError):
            self.hand()
        self.assertEqual(self.queued("acme"), [])

    def test_a_refused_line_leaves_nothing_in_hand(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        with patch.object(tell, "queue", return_value="acme is closed"):
            self.hand()
        self.assertNotIn("handed", retire.read()[str(self.acme)])
        self.assertIn("WARN ACME: switch first was not handed: acme is closed", self.logged)

    def test_the_lists_are_read_once_an_hour_and_once_per_repository(self):
        subprocess.run(["git", "-C", str(self.acme), "worktree", "add", "-q",
                        str(config.CODE / "ACME-wt"), "-b", "wt"], check=True)
        self.seat("acme-wt", config.CODE / "ACME-wt", created=10)
        self.switches(row("older", 60))
        self.hand()
        self.hand(NOW + retire.EVERY - 1)
        self.assertEqual(self.lists(), 1)
        self.assertEqual(len(self.queued("acme-wt")), 1)

    def test_nothing_is_handed_without_an_open_seat_or_a_list(self):
        self.switches(row("older", 60))
        self.hand()
        self.assertIn("ACME: switch older is proven; no open seat to hand it to", self.logged)
        self.seat("acme", self.acme, created=10)
        (self.fake / "refuse").write_text("")
        self.hand(NOW + retire.EVERY)
        self.assertEqual(self.queued("acme"), [])
        self.assertTrue(any(line.startswith("WARN ACME: its switches are unread")
                            and "no route to the live host" in line for line in self.logged))
        (self.fake / "refuse").unlink()
        self.hand(NOW + 2 * retire.EVERY)
        self.assertEqual(len(self.queued("acme")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
