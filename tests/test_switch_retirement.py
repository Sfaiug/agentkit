"""A feature switch on for everyone for two weeks is handed to a seat on its project to take out
of the code: the longest-proven one, one at a time until it leaves the list, per checkout.

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
        self.acme = self.project("ACME", f"{sys.executable} {self.fake / 'features.py'}")
        self.seats = []
        stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [
            dict(seat) for seat in self.seats]))
        self.logged = []

    def project(self, name, features):
        checkout = config.CODE / name
        checkout.mkdir(parents=True)
        front = f"features: {features}\n" if features else ""
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

    def typed(self, name):
        """The switches of the lines waiting for that seat, typed as the tick types them."""
        waiting = [message["line"].split("`")[1] for message in self.queued(name)]
        tell.write(config.seat_file("tell", name), [])
        return waiting

    def lists(self):
        try:
            return (self.fake / "calls.log").read_text().splitlines().count("list")
        except FileNotFoundError:
            return 0

    def test_the_longest_proven_switch_goes_to_the_newest_open_seat_on_its_project(self):
        self.seat("acme-old", self.acme, created=10)
        self.seat("acme-new", self.acme, created=30)
        self.seat("acme-gone", self.acme, created=50, exited=True)
        other = self.project("OTHER", None)
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
        self.assertEqual(self.typed("acme"), ["older"])
        self.hand(NOW + 2 * retire.EVERY)
        self.assertEqual(self.typed("acme"), [])
        self.switches(row("old", 40))
        self.hand(NOW + 3 * retire.EVERY)
        self.assertEqual(self.typed("acme"), ["old"])

    def test_one_still_listed_a_day_after_is_handed_again_in_place_of_a_waiting_copy(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("older", 60))
        self.hand()
        self.assertEqual(self.typed("acme"), ["older"])
        self.hand(NOW + retire.AGAIN - 1)
        self.assertEqual(self.queued("acme"), [])
        self.hand(NOW + retire.AGAIN + retire.EVERY)
        self.hand(NOW + 2 * retire.AGAIN + 2 * retire.EVERY)
        self.assertEqual(self.typed("acme"), ["older"])

    def test_the_switch_in_hand_is_handed_again_before_an_older_one_listed_since(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        self.hand()
        handed = self.typed("acme")
        self.switches(row("first", 40), row("newer-listed", 60))
        self.hand(NOW + retire.AGAIN)
        handed += self.typed("acme")
        self.switches(row("newer-listed", 60))
        self.hand(NOW + retire.AGAIN + retire.EVERY)
        self.assertEqual(handed + self.typed("acme"), ["first", "first", "newer-listed"])

    def test_one_turned_off_is_proven_no_longer_its_waiting_line_taken_back(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 60), row("second", 40))
        self.hand()
        self.switches(row("first", everyone=False), row("second", 40))
        self.hand(NOW + retire.EVERY)
        self.assertEqual(self.typed("acme"), ["second"])
        self.assertEqual(retire.read()[str(self.acme)]["id"], "second")

    def test_one_of_that_id_on_for_everyone_anew_is_another_switch(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("search", 60))
        self.hand()
        self.switches(row("search", 1))
        self.hand(NOW + retire.AGAIN + retire.EVERY)
        self.assertEqual(self.queued("acme"), [])
        self.assertEqual(set(retire.read()), {"asked"})

    def test_a_checkout_replaced_at_its_path_hands_its_own_switches(self):
        self.seat("acme-old", self.acme, created=10)
        self.switches(row("new-search", 60))
        self.hand()
        self.acme.rename(self.root / "old-acme")
        self.acme = self.project("ACME", f"{sys.executable} {self.fake / 'features.py'}")
        self.seats.clear()
        self.seat("acme-new", self.acme, created=20)
        self.switches(row("new-search", everyone=False), row("other-switch", 40))
        self.hand(NOW + retire.AGAIN + retire.EVERY)
        self.assertEqual(self.typed("acme-old"), [])
        self.assertEqual(self.typed("acme-new"), ["other-switch"])

    def test_a_line_that_cannot_be_taken_back_keeps_its_switch_in_hand(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 60), row("second", 40))
        self.hand()
        self.switches(row("first", everyone=False), row("second", 40))
        with patch.object(tell, "withdraw", return_value="acme's message queue cannot be read"):
            self.hand(NOW + retire.EVERY)
        self.assertEqual(self.typed("acme"), ["first"])
        self.assertEqual(retire.read()[str(self.acme)]["id"], "first")
        self.assertIn("WARN ACME: switch first is no longer proven, but its line may still wait: "
                      "acme's message queue cannot be read", self.logged)

    def test_an_unread_record_hands_nothing(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        self.hand()
        self.switches(row("first", 40), row("newer-listed", 60))
        retire.path().write_text("[]")
        with self.assertRaises(ValueError):
            self.hand(NOW + retire.AGAIN)
        self.assertEqual(len(self.queued("acme")), 1)

    def test_a_stamp_without_an_offset_is_utc(self):
        self.seat("acme", self.acme, created=10)
        self.switches({**row("unmarked", 60), "everyone_since": stamp(60).removesuffix("Z")})
        self.hand()
        [message] = self.queued("acme")
        self.assertIn("`unmarked` switch", message["line"])

    def test_a_hand_off_longer_than_a_told_line_is_handed_as_a_file(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("x" * 900, 90), row("new-search", 60))
        self.hand()
        [message] = self.queued("acme")
        self.assertIn(": ~/.agentkit/", message["line"])
        whole = Path(message["line"].split(": ")[-1].removesuffix(" says which, and where."))
        self.assertIn(f"In ACME, the `{'x' * 900}` switch", whole.expanduser().read_text())

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
        self.assertEqual(set(retire.read()), {"asked"})
        self.assertIn("WARN ACME: switch first was not handed: acme is closed", self.logged)

    def test_each_checkout_is_read_once_an_hour_for_the_seats_filed_under_it(self):
        other = self.project("OTHER", f"{sys.executable} {self.fake / 'features.py'}")
        self.seat("other", other, created=20)
        self.switches(row("older", 60))
        self.hand()
        self.hand(NOW + retire.EVERY - 1)
        self.assertEqual(self.lists(), 2)
        [message] = self.queued("other")
        self.assertIn("In OTHER, the `older` switch", message["line"])
        self.assertIn("ACME: switch older is proven; no open seat to hand it to", self.logged)
    def test_projects_listing_alike_keep_their_own_lists(self):
        self.switches()
        for name in ("ONE", "TWO"):
            checkout = self.project(name, f"{sys.executable} features.py")
            (checkout / "features.py").write_text(FAKE)
            (checkout / "features.json").write_text(json.dumps([row("new-search", 60)]))
            self.seat(name.lower(), checkout, created=10 if name == "ONE" else 20)
        self.hand()
        self.assertEqual([message["line"][:40] for message in self.queued("one")],
                         ["[from ak, not the owner] In ONE, the `ne"])
        self.assertEqual([message["line"][:40] for message in self.queued("two")],
                         ["[from ak, not the owner] In TWO, the `ne"])

    def test_git_plays_no_part(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        head = self.acme / ".git" / "HEAD"
        head.rename(head.with_name("HEAD-unread"))
        self.hand()
        self.assertEqual([message["line"].split("`")[1] for message in self.queued("acme")],
                         ["first"])
    def test_the_seat_the_tick_runs_in_takes_ak_lines_too(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("older", 60))
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "acme"}):
            self.hand()
        self.assertEqual(len(self.queued("acme")), 1)

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
