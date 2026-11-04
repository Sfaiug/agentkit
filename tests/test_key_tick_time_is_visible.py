"""Where a tick's time goes is visible: in its log line by line, and in watch.json.

Cron appends a tick's output to ~/.agentkit/tmp/watch.log, and there every line the tick writes
starts with its date and time, so two lines say how long what lay between them took; a dry
run's lines, printed where it was run, do not.  A pass that took more than a second leaves one
line `<its name> took <seconds> s`, a GitHub pass too, and however the tick ends, an early
return at the GitHub gate included, watch.json's `tick` holds when it started and ended and the
slowest pass's name and seconds; a dry run writes none.  Here a merged run's `health:` and gh's
answer to who is logged in each sleep past a second, a seat whose record cannot be written has
the tick print a WARN to stderr, which cron appends to the log too, gh's own error holds a
blank line, and the line owed to a second seat, which the tick logs as it tells it, ends in a CR
and holds another.  Black-box: the program `AK_BIN` names ticks from outside by cron's line, through
tests/fixtures/akbin.py, on a project from gitrig.py, a seat from akseat.py and the GitHub of
fakegh.py.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home
from fixtures.akseat import Seat
from fixtures.fakegh import LOGGED_OUT, OFFLINE, GitHub
from fixtures.gitrig import Rig

SLEEP = 1.5
STAMP = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d"     # a log line's date and time: the Home's TZ is UTC
LINE = re.compile(f"({STAMP}) (.*)")
TOOK = re.compile(r"([a-z]+(?: [a-z]+){0,2}) took (\d+\.\d) s")
RUN = "20261020-1200-fix-api"


def at(stamp):
    return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def took(lines):
    """Each pass a line says took over a second, with its seconds, in the order said."""
    found = [TOOK.fullmatch(LINE.fullmatch(line)[2]) for line in lines]
    return [(said[1], float(said[2])) for said in found if said]


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class TickTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        # a break past its hours is a stall the audit seat would open for; that is its own key
        config = home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        rig = Rig(home, "app", files={"AGENTS.md": f"---\nhealth: sleep {SLEEP}\n---\n"})
        cls.gh = GitHub(home)
        cls.gh.check(rig.head(), "ci")
        (home.bin / "gh").rename(home.bin / "fakegh")
        home.fake("gh", f'#!/bin/sh\n[ "$*" = "api user" ] && sleep {SLEEP}\n'
                        f'exec {shlex.quote(str(home.bin / "fakegh"))} "$@"\n')
        now = time.time()
        home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "state": "pass", "verdict": "PASS", "merged": True,
            "finished_at": now - 600, "started_at": now - 1200, "repo": str(rig.path),
            "pr": "https://github.com/acme/app/pull/7", "merge_sha": rig.head(),
            "health": {"command": f"sleep {SLEEP}"}})
        Seat(home, "acme", screen="claude-working-pane.txt")
        (home.path / ".agentkit/state/seat-acme.tmp").mkdir()
        Seat(home, "beta")
        home.write(".agentkit/state/seat-beta.json",
                   {"owed_lines": [{"id": "1", "line": "first\rsecond\r"}]})
        cls.log = home.write(".agentkit/tmp/watch.log", "")
        cls.gh.reply("api --paginate search/issues -X GET",
                     err="network unavailable\n\nplease retry\n", code=1)
        cls.lines, cls.record, cls.before, cls.after = cls.tick()
        cls.gh.restore()

    @classmethod
    def tick(cls):
        """The lines one tick by cron's line added to watch.log, watch.json's `tick` after it,
        and the clock before and after it."""
        written, before = cls.log.stat().st_size, time.time()
        done = cls.home.tick(cron=True)
        after = time.time()
        assert done.code == 0, cls.log.read_text()[-2000:]
        lines = cls.log.read_bytes()[written:].decode().splitlines()
        watch = json.loads((cls.home.path / ".agentkit/state/watch.json").read_text())
        return lines, watch.get("tick"), before, after

    def assert_ended_then(self, record, before, after):
        self.assertEqual(sorted(record), ["ended_at", "slowest", "started_at"], record)
        self.assertTrue(before <= record["started_at"] <= record["ended_at"] <= after, record)

    def test_every_line_in_the_log_starts_with_when_it_was_written(self):
        said = []
        for line in self.lines:
            stamped = LINE.fullmatch(line)
            self.assertTrue(stamped, line)
            self.assertTrue(int(self.before) <= at(stamped[1]) <= self.after, line)
            said.append(stamped[2])
        self.assertIn("seat-acme.tmp", "\n".join(said))
        self.assertIn("network unavailable\n\nplease retry", "\n".join(said))

    def test_a_cr_ends_its_line_and_the_lf_print_writes_after_it_starts_none(self):
        self.assertRegex(self.log.read_bytes(),
                         f"{STAMP} told beta: first\r{STAMP} second\r\n".encode())

    def test_each_pass_past_a_second_leaves_one_line_with_its_name_and_seconds(self):
        said = took(self.lines)
        names = [name for name, _ in said]
        self.assertEqual(len(names), len(set(names)), said)
        for name in ("merge checks", "github user"):
            with self.subTest(name):
                self.assertGreaterEqual(dict(said).get(name, 0), SLEEP, said)

    def test_watch_json_keeps_when_the_tick_ran_and_its_slowest_pass(self):
        self.assert_ended_then(self.record, self.before, self.after)
        slowest, said = self.record["slowest"], dict(took(self.lines))
        self.assertEqual(sorted(slowest), ["pass", "seconds"], slowest)
        self.assertEqual(said.get(slowest["pass"]), slowest["seconds"], (slowest, said))
        self.assertEqual(slowest["seconds"], max(said.values()))

    def test_a_tick_ending_at_the_github_gate_keeps_its_record_too(self):
        for said, code in ((OFFLINE, 1), (LOGGED_OUT, 4)):
            with self.subTest(said=said):
                self.gh.reply("", err=said, code=code)
                try:
                    lines, record, before, after = self.tick()
                finally:
                    self.gh.restore()
                self.assert_ended_then(record, before, after)
                self.assertGreaterEqual(dict(took(lines)).get("github user", 0), SLEEP, lines)
                self.assertGreaterEqual(record["slowest"]["seconds"], SLEEP)

    def test_a_dry_run_prints_its_lines_bare_and_writes_no_record(self):
        state = self.home.path / ".agentkit/state/watch.json"
        kept = state.read_bytes()
        done = self.home.ak("watch", "--dry-run")
        self.assertEqual((done.code, done.err), (0, ""), done.out)
        lines = done.out.splitlines()
        self.assertTrue(lines[0].startswith("lock "), lines)
        self.assertEqual([line for line in lines if re.match(STAMP, line)], [])
        self.assertEqual(state.read_bytes(), kept)


if __name__ == "__main__":
    unittest.main()
