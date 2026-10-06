"""Every feature switch on for everyone for two weeks is told, once a day while it is still
listed, to the newest open seat filed under its checkout, to take out of the code.

Offline: a temporary HOME whose ~/code/ACME names a fake features command in its AGENTS.md, a
script answering `list` from a JSON file beside it and logging each call; the open seats are
faked.  The told line is read from the seat's `ak tell` queue.
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
        """The switches each line waiting for that seat names, typed as the tick types them."""
        waiting = [message["line"].split("`")[1::2] for message in self.queued(name)]
        tell.write(config.seat_file("tell", name), [])
        return waiting

    def lists(self):
        try:
            return (self.fake / "calls.log").read_text().splitlines().count("list")
        except FileNotFoundError:
            return 0

    def test_every_proven_switch_goes_longest_first_to_the_newest_open_seat_on_its_project(self):
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
        self.assertIn("In ACME, these switches have been on for everyone two weeks or more",
                      message["line"])
        self.assertIn("Take each out of ACME's code", message["line"])
        self.assertEqual(tell.source(message["from"]), "ak")
        self.assertEqual(self.typed("acme-new"), [["older", "old", "unstamped"]])
        self.assertIn("ACME: proven switches older, old; on for everyone with no everyone_since "
                      "unstamped; told acme-new", self.logged)

    def test_a_list_without_everyone_since_is_told_to_give_it(self):
        self.seat("acme", self.acme, created=10)
        self.switches(*({**row(feature), "everyone_since": None} for feature in ("search", "uk")),
                      {key: value for key, value in row("hidden", everyone=False).items()
                       if key != "everyone_since"})
        self.hand()
        [message] = self.queued("acme")
        self.assertIn("ACME's switch list does not say since when these are on for everyone: "
                      "`search`, `uk`. Have its features list give each row an everyone_since",
                      message["line"])
        self.assertNotIn("proven:", message["line"])
        self.hand(NOW + retire.AGAIN)
        self.assertEqual(self.typed("acme"), [["search", "uk"]])

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
        self.assertEqual(self.typed("acme-gb"), [["region_gb", "vat_fee"]])
        self.assertEqual(self.typed("acme-help"), [["help_chat"]])
        self.assertEqual(self.typed("acme-new"), [["region_gb_rff"]])
        self.assertIn("ACME: proven switches help_chat, region_gb, region_gb_rff, vat_fee; "
                      "told acme-help, acme-gb, acme-new", self.logged)

    def test_told_again_a_day_later_while_one_is_still_listed(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("older", 60), row("old", 40))
        self.hand()
        self.assertEqual(self.typed("acme"), [["older", "old"]])
        self.hand(NOW + retire.EVERY)
        self.assertEqual((self.typed("acme"), self.lists()), ([], 1))
        self.switches(row("old", 40))
        self.hand(NOW + retire.AGAIN)
        self.assertEqual(self.typed("acme"), [["old"]])
        self.switches()
        self.hand(NOW + 2 * retire.AGAIN)
        self.assertEqual(self.typed("acme"), [])

    def test_a_line_still_waiting_is_not_queued_again(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("older", 60))
        self.hand()
        self.hand(NOW + retire.AGAIN)
        self.assertEqual(self.typed("acme"), [["older"]])

    def test_what_a_seat_was_told_stands_when_a_switch_is_turned_off(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 60), row("second", 40))
        self.hand()
        self.switches(row("first", everyone=False), row("second", 40))
        self.hand(NOW + retire.AGAIN)
        self.assertEqual(self.typed("acme"), [["first", "second"], ["second"]])

    def test_a_stamp_without_an_offset_is_utc(self):
        self.seat("acme", self.acme, created=10)
        self.switches({**row("unmarked", 60), "everyone_since": stamp(60).removesuffix("Z")})
        self.hand()
        self.assertEqual(self.typed("acme"), [["unmarked"]])

    def test_switches_longer_than_a_told_line_are_told_as_a_file(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("x" * 900, 90), row("new-search", 60))
        self.hand()
        [message] = self.queued("acme")
        self.assertIn(": ~/.agentkit/", message["line"])
        whole = Path(message["line"].split(": ")[-1].removesuffix(" says which, and where."))
        text = whole.expanduser().read_text()
        self.assertIn(f"In ACME, these switches", text)
        self.assertEqual(text.split("`")[1::2], ["x" * 900, "new-search"])

    def test_names_a_typed_line_would_change_are_told_as_a_file(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("search  panel", 40), row("new\tsearch", 30))
        self.hand()
        [message] = self.queued("acme")
        whole = Path(message["line"].split(": ")[-1].removesuffix(" says which, and where."))
        self.assertEqual(whole.expanduser().read_text().split("`")[1::2],
                         ["search  panel", "new\tsearch"])

    def test_a_record_that_is_not_one_costs_at_most_a_line_told_again(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        self.hand()
        self.assertEqual(self.typed("acme"), [["first"]])
        for broken in ("[]", "not json", '{"asked": "now"}'):
            with self.subTest(broken=broken):
                retire.path().write_text(broken)
                self.hand(NOW + retire.EVERY)
                self.assertEqual(self.typed("acme"), [["first"]])
                self.assertEqual(retire.read()[str(self.acme)], NOW + retire.EVERY)

    def test_a_recorded_time_that_is_not_past_counts_as_never(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        for at in ("1e309", "NaN", "1" + "0" * 400, str(NOW + 10 * retire.AGAIN)):
            for key in ("asked", str(self.acme)):
                with self.subTest(key=key, at=at):
                    retire.path().write_text(f'{{"{key}": {at}}}')
                    self.hand()
                    self.assertEqual(self.typed("acme"), [["first"]])

    def test_any_switch_the_menu_lists_is_told_and_alike_rows_break_nothing(self):
        other = self.project("OTHER", f"{sys.executable} {self.fake / 'features.py'}")
        self.seat("acme", self.acme, created=10)
        self.seat("other", other, created=20)
        self.switches(row(42, 40), {**row("twice", 60), "name": "one"},
                      {**row("twice", 60), "name": "two"}, ["not a row"], {"name": "no id"})
        self.hand()
        for name in ("acme", "other"):
            self.assertEqual(self.typed(name), [["twice", "twice", "42"]])

    def test_a_refused_line_is_tried_again_at_the_next_read(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("first", 40))
        with patch.object(tell, "queue", return_value="acme is closed"):
            self.hand()
        self.assertNotIn(str(self.acme), retire.read())
        self.assertIn("WARN ACME: proven switches first; not told: acme: acme is closed",
                      self.logged)
        self.hand(NOW + retire.EVERY)
        self.assertEqual(self.typed("acme"), [["first"]])

    def test_each_checkout_is_read_once_an_hour_for_the_seats_filed_under_it(self):
        other = self.project("OTHER", f"{sys.executable} {self.fake / 'features.py'}")
        self.seat("other", other, created=20)
        self.switches(row("older", 60))
        self.hand()
        self.hand(NOW + retire.EVERY - 1)
        self.assertEqual(self.lists(), 2)
        [message] = self.queued("other")
        self.assertIn("In OTHER, these switches", message["line"])
        self.assertIn("ACME: proven switches older; no open seat to tell", self.logged)

    def test_projects_listing_alike_keep_their_own_lists(self):
        self.switches()
        for name in ("ONE", "TWO"):
            checkout = self.project(name, f"{sys.executable} features.py")
            (checkout / "features.py").write_text(FAKE)
            (checkout / "features.json").write_text(json.dumps([row("new-search", 60)]))
            self.seat(name.lower(), checkout, created=10 if name == "ONE" else 20)
        self.hand()
        for name in ("ONE", "TWO"):
            [message] = self.queued(name.lower())
            self.assertIn(f"In {name}, these switches", message["line"])

    def test_the_seat_the_tick_runs_in_takes_ak_lines_too(self):
        self.seat("acme", self.acme, created=10)
        self.switches(row("older", 60))
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "acme"}):
            self.hand()
        self.assertEqual(self.typed("acme"), [["older"]])

    def test_without_an_open_seat_or_a_list_it_is_tried_again_the_next_hour(self):
        self.switches(row("older", 60))
        self.hand()
        self.assertIn("ACME: proven switches older; no open seat to tell", self.logged)
        self.seat("acme", self.acme, created=10)
        (self.fake / "refuse").write_text("")
        self.hand(NOW + retire.EVERY)
        self.assertEqual(self.queued("acme"), [])
        self.assertTrue(any(line.startswith("WARN ACME: its switches are unread")
                            and "no route to the live host" in line for line in self.logged))
        (self.fake / "refuse").unlink()
        self.hand(NOW + 2 * retire.EVERY)
        self.assertEqual(self.typed("acme"), [["older"]])

if __name__ == "__main__":
    unittest.main(verbosity=2)
