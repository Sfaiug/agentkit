"""Every feature switch on for everyone for two weeks becomes, once a day while it is still
listed, an open line in the plan of the newest open seat filed under its checkout, to take out
of the code; the line's check is the project's own switch list, which fails while the list still
shows the switch.  Nothing is typed into a seat.

Offline: a temporary HOME whose ~/code/ACME names a fake features command in its AGENTS.md, a
script answering `list` from a JSON file beside it and logging each call, a bare repository as
each project's origin; the open seats are faked.
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
from agentkit import config, harness, orch, plan, retire

DAY = 86400
NOW = 1_800_000_000.0
FAKE = r"""
import json, os, sys
from pathlib import Path
here = Path(__file__).parent
with open(here / "calls.log", "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\t" + os.getcwd() + "\n")
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
        """A checkout under ~/code with a bare origin, since a plan line's check is proven on the
        project's default branch as fetched from there."""
        checkout = config.CODE / name
        checkout.mkdir(parents=True)
        front = f"features: {features}\n" if features else ""
        (checkout / "AGENTS.md").write_text(f"---\nusers: real\n{front}---\n\n# {name}\n")
        origin = self.root / "remotes" / f"{name}.git"
        origin.parent.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        for args in (["init", "-q", "-b", "main"], ["add", "AGENTS.md"],
                     ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"],
                     ["remote", "add", "origin", str(origin)], ["push", "-q", "-u", "origin", "main"]):
            subprocess.run(["git", "-C", str(checkout), *args], check=True,
                           capture_output=True)
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

    def lines(self, name):
        """The switches the open lines of that seat's plan name, in the plan's order."""
        found = []
        for line in plan.open_lines(name):
            what = plan.LINE.match(line.strip())["what"]
            if "'s switch list gives " in what:
                found.append(what.split("'s switch list gives ")[1].split(" ")[0])
            elif "'s switch " in what:
                found.append(what.split("'s switch ")[1].split(" ")[0])
            else:
                found.append(what)
        return found

    def lists(self):
        """How often the tick read a list: in a checkout under ~/code, where a line's check,
        proven in a throwaway checkout of the default branch, never runs."""
        try:
            calls = (self.fake / "calls.log").read_text().splitlines()
        except FileNotFoundError:
            return 0
        return sum(1 for call in calls if call.split("\t")[0] == "list"
                   and call.split("\t")[-1].startswith(str(config.CODE)))

    def test_every_proven_switch_goes_longest_first_to_the_newest_open_seat_on_its_project(self):
        self.seat("acme-old", self.acme, created=10)
        self.seat("acme-new", self.acme, created=30)
        self.seat("acme-gone", self.acme, created=50, exited=True)
        other = self.project("OTHER", None)
        self.seat("other", other, created=90)
        self.switches(row("fresh", 13), row("hidden", everyone=False), row("old", 40),
                      row("older", 60), {**row("unstamped"), "everyone_since": None})
        self.hand()
        self.assertEqual(self.lines("acme-old") + self.lines("other"), [])
        self.assertEqual(self.lines("acme-new"), ["older", "old", "unstamped"])
        [proven] = [line for line in plan.open_lines("acme-new") if " older " in line]
        self.assertIn("ACME's switch older is out of the code: on for everyone since", proven)
        self.assertIn("so proven, and everyone keeps the feature for good", proven)
        self.assertIn("/ACME#", proven)
        self.assertIn("ACME: proven switches older, old; on for everyone with no everyone_since "
                      "unstamped; planned in acme-new", self.logged)

    def test_a_list_without_everyone_since_gets_a_line_asking_for_it(self):
        self.seat("acme", self.acme, created=10)
        self.switches(*({**row(feature), "everyone_since": None} for feature in ("search", "uk")),
                      {key: value for key, value in row("hidden", everyone=False).items()
                       if key != "everyone_since"})
        self.hand()
        self.assertEqual(self.lines("acme"), ["search", "uk"])
        [line] = [line for line in plan.open_lines("acme") if " search " in line]
        self.assertIn("ACME's switch list gives search an everyone_since", line)
        self.assertNotIn("out of the code", line)

    def test_a_switch_an_open_plan_names_goes_to_that_seat(self):
        self.seat("acme-gb", self.acme, created=10)
        self.seat("acme-help", self.acme, created=20)
        self.seat("acme-new", self.acme, created=30)
        written = " · check: `true` · ACME · written 2026-10-06 12:00"
        config.plan_path("acme-gb").write_text(
            f"- [ ] Proven switches region_gb, vat_fee are gone from the code{written}\n"
            f"- [x] help_chat copy reviewed · your eye · ACME · written 2026-10-06 12:00"
            " · done your yes 2026-10-06 13:00\n")
        config.plan_path("acme-help").write_text(
            f"- [ ] The help_chat switch is gone{written}\n")
        self.switches(row("help_chat", 120), row("region_gb", 110),
                      row("region_gb_rff", 100), row("vat_fee", 50))
        self.hand()
        self.assertEqual(self.lines("acme-gb")[1:], ["region_gb", "vat_fee"])
        self.assertEqual(self.lines("acme-help")[1:], ["help_chat"])
        self.assertEqual(self.lines("acme-new"), ["region_gb_rff"])
        self.assertIn("ACME: proven switches help_chat, region_gb, region_gb_rff, vat_fee; "
                      "planned in acme-help, acme-gb, acme-new", self.logged)

    def test_a_line_is_written_once_and_the_list_is_read_again_a_day_later(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("older", 60), row("old", 40))
        self.hand()
        self.assertEqual(self.lines("acme"), ["older", "old"])
        self.hand(NOW + retire.EVERY)
        self.assertEqual((self.lines("acme"), self.lists()), (["older", "old"], 1))
        self.switches(row("old", 40))
        self.hand(NOW + retire.AGAIN)
        self.assertEqual((self.lines("acme"), self.lists()), (["older", "old"], 2))
        self.switches(row("old", 40), row("newer", 30))
        self.hand(NOW + 2 * retire.AGAIN)
        self.assertEqual(self.lines("acme"), ["older", "old", "newer"])

    def test_the_check_fails_while_the_list_shows_the_switch_and_passes_once_it_is_gone(self):
        command = f"{sys.executable} {self.fake / 'features.py'}"
        proven, unproven = retire.check(command, row("older", 60), True), retire.check(
            command, {**row("unstamped"), "everyone_since": None}, False)
        self.switches(row("older", 60), {**row("unstamped"), "everyone_since": None})
        self.assertEqual(subprocess.run(["bash", "-c", proven]).returncode, 1)
        self.assertEqual(subprocess.run(["bash", "-c", unproven]).returncode, 1)
        self.switches(row("unstamped", 3))
        self.assertEqual(subprocess.run(["bash", "-c", proven]).returncode, 0)
        self.assertEqual(subprocess.run(["bash", "-c", unproven]).returncode, 0)
        # ... and a row off for everyone, or gone, has nothing left to prove: the line ticks
        self.switches({**row("unstamped", everyone=False), "everyone_since": None})
        self.assertEqual(subprocess.run(["bash", "-c", unproven]).returncode, 0)
        self.switches()
        self.assertEqual(subprocess.run(["bash", "-c", unproven]).returncode, 0)
        # ... and a check that already passes on the default branch is no line: the switch
        # is gone from the list between the read and the write
        self.seat("acme", self.acme, created=10)
        self.switches(row("older", 60))
        with patch.object(retire, "check", return_value="true"):
            self.hand()
        self.assertEqual(self.lines("acme"), [])
        self.assertTrue(any(line.startswith("WARN ACME: proven switches older; not planned: acme: "
                                            "older: this check already passes")
                            for line in self.logged), self.logged)
        self.assertNotIn(str(self.acme), retire.read())

    def test_what_a_plan_line_says_stands_when_a_switch_is_turned_off(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 60), row("second", 40))
        self.hand()
        self.switches(row("first", everyone=False), row("second", 40))
        self.hand(NOW + retire.AGAIN)
        self.assertEqual(self.lines("acme"), ["first", "second"])

    def test_a_stamp_without_an_offset_is_utc(self):
        self.seat("acme", self.acme, created=10)
        self.switches({**row("unmarked", 60), "everyone_since": stamp(60).removesuffix("Z")})
        self.hand()
        self.assertEqual(self.lines("acme"), ["unmarked"])

    def test_a_record_that_is_not_one_costs_at_most_a_list_read_again(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        self.hand()
        self.assertEqual(self.lines("acme"), ["first"])
        for broken in ("[]", "not json", '{"asked": "now"}'):
            with self.subTest(broken=broken):
                retire.path().write_text(broken)
                self.hand(NOW + retire.EVERY)
                self.assertEqual(self.lines("acme"), ["first"])
                self.assertEqual(retire.read()[str(self.acme)], NOW + retire.EVERY)

    def test_a_recorded_time_that_is_not_past_counts_as_never(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        for at in ("1e309", "NaN", "1" + "0" * 400, str(NOW + 10 * retire.AGAIN)):
            for key in ("asked", str(self.acme)):
                with self.subTest(key=key, at=at):
                    retire.path().write_text(f'{{"{key}": {at}}}')
                    self.hand()
                    self.assertEqual(self.lines("acme"), ["first"])

    def test_any_switch_the_menu_lists_gets_a_line_and_alike_rows_break_nothing(self):
        other = self.project("OTHER", f"{sys.executable} {self.fake / 'features.py'}")
        self.seat("acme", self.acme, created=10)
        self.seat("other", other, created=20)
        self.switches(row(42, 40), {**row("twice", 60), "name": "one"},
                      {**row("twice", 60), "name": "two"}, ["not a row"], {"name": "no id"})
        self.hand()
        for name in ("acme", "other"):
            self.assertEqual(self.lines(name), ["twice", "42"])

    def test_a_refused_line_is_tried_again_at_the_next_read(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        with patch.object(plan, "add", side_effect=config.Error("acme is closed")):
            self.hand()
        self.assertNotIn(str(self.acme), retire.read())
        self.assertIn("WARN ACME: proven switches first; not planned: acme: first: acme is closed",
                      self.logged)
        self.hand(NOW + retire.EVERY)
        self.assertEqual(self.lines("acme"), ["first"])

    def test_each_checkout_is_read_once_an_hour_for_the_seats_filed_under_it(self):
        other = self.project("OTHER", f"{sys.executable} {self.fake / 'features.py'}")
        self.seat("other", other, created=20)
        self.switches(row("older", 60))
        self.hand()
        self.hand(NOW + retire.EVERY - 1)
        self.assertEqual(self.lists(), 2)
        self.assertEqual(self.lines("other"), ["older"])
        self.assertIn("ACME: proven switches older; no open seat to plan it in", self.logged)

    def test_projects_listing_alike_keep_their_own_lists(self):
        self.switches()
        for name in ("ONE", "TWO"):
            checkout = self.project(name, f"{sys.executable} features.py")
            (checkout / "features.py").write_text(FAKE)
            (checkout / "features.json").write_text(json.dumps([row("new-search", 60)]))
            self.seat(name.lower(), checkout, created=10 if name == "ONE" else 20)
        self.hand()
        for name in ("ONE", "TWO"):
            [line] = plan.open_lines(name.lower())
            self.assertIn(f"{name}'s switch new-search is out of the code", line)
            self.assertIn(f"/{name}#", line)

    def test_the_seat_the_tick_runs_in_gets_its_lines_too(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("older", 60))
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "acme"}):
            self.hand()
        self.assertEqual(self.lines("acme"), ["older"])

    def test_without_an_open_seat_or_a_list_it_is_tried_again_the_next_hour(self):
        self.switches(row("older", 60))
        self.hand()
        self.assertIn("ACME: proven switches older; no open seat to plan it in", self.logged)
        self.seat("acme", self.acme, created=10)
        (self.fake / "refuse").write_text("")
        self.hand(NOW + retire.EVERY)
        self.assertEqual(self.lines("acme"), [])
        self.assertTrue(any(line.startswith("WARN ACME: its switches are unread")
                            and "no route to the live host" in line for line in self.logged))
        (self.fake / "refuse").unlink()
        self.hand(NOW + 2 * retire.EVERY)
        self.assertEqual(self.lines("acme"), ["older"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
