"""A read of the main screen works out what every run says from its open runs alone, and the look
after it from nothing.

Each read folded every run three times -- the replacements by title and branch, each seat's runs and
the silent ones -- and the look after it again, over 5,000 runs of which 40 to 90 could change.  A
run at rest changes only at a full read, so its fold is kept until then.  Offline: a temporary HOME,
fake run records, no tmux.
"""

from pathlib import Path
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, open_runs, orch, parsed, transitions  # noqa: E402

ENDED, OPEN = 6000, 10
SEATS = ["acme-api", "acme-web", "acme-ops", "acme-new", "acme-www"]   # listed, each filed under acme
WEEK = 7 * 86400
NOW = time.time_ns() // 10**9    # the real clock: `open_runs` dates a record by its file


def write(name, ago=0, **state):
    directory = config.RUNS / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "run.json"
    path.write_text(json.dumps({"run_id": name, "repo": "acme", **state}))
    if ago:
        os.utime(path, (NOW - ago, NOW - ago))
    return directory


def ended(n, **state):
    """The nth run long over: from one of a few seats, a past one or none, a few merged under
    titles they share, a few relaunched `from:` a branch, finishing three to a second."""
    seat = ("acme-api", "acme-web", "acme-old", f"past-{n % 40}", None)[n % 5]
    return write(f"r{n:05}", WEEK, **{
        "state": "pass", "launched_session": seat, "finished_at": NOW - WEEK + n // 3,
        "title": f"Fix {n % 50}", "merged": n % 7 == 0,
        **({"from": f"ak/fix-{n % 30}"} if n % 11 == 0 else {}), **state})


def going(n, name=None, **state):
    """The nth open run, the even ones silent for two hours."""
    seat = ("acme-api", "acme-web", "acme-old", "acme-new")[n % 4]
    return write(name or f"s{n:02}", 2 * 3600 if n % 2 == 0 else 0, **{
        "state": "running", "launched_session": seat, "started_at": NOW - 2 * 3600 + n,
        "title": f"Fix {n}", **({"from": f"ak/fix-{n}"} if n % 3 == 0 else {}), **state})


class ReadFoldsOnlyTheOpenRuns(Sandbox):
    def setUp(self):
        super().setUp()
        for patched in (patch.object(parsed, "FRESH", 0),            # every record kept as read
                        patch.object(open_runs, "SHARE", 1e-9),      # full reads CEILING apart
                        patch.object(menu.time, "time", return_value=NOW),
                        patch.object(orch, "listing",
                                     side_effect=lambda: [{"name": name, "repo": "acme"} for name in SEATS])):
            self.stack.enter_context(patched)
        clock, self.shift = time.monotonic, 0
        self.stack.enter_context(patch.object(open_runs.time, "monotonic",
                                              lambda: clock() + self.shift))
        config.session_path("acme-old").write_text(json.dumps({"renamed": "acme-ops"}))
        for n in range(ENDED):
            ended(n)
        for n in range(OPEN):
            going(n)
        self.read()                                       # the first read, a full one

    def read(self):
        found, records, groups = menu.rows(self.cfg)
        self.found, self.records, self.groups = found, records, groups
        return records

    def full(self):
        self.shift += open_runs.CEILING + 1
        return self.read()

    def counted(self):
        """How often each fold is asked of a run from now on."""
        calls = {"launched_session": 0, "silent_for_run": 0, "supersession_index": 0}

        def wrap(module, name):
            real = getattr(module, name)

            def counting(*args, **kwargs):
                calls[name] += 1
                return real(*args, **kwargs)
            return patch.object(module, name, counting)

        def indexing(states):
            states = list(states)
            calls["supersession_index"] += len(states)
            return index(states)
        index = transitions.supersession_index
        self.stack.enter_context(wrap(transitions, "launched_session"))
        self.stack.enter_context(wrap(menu, "silent_for_run"))
        self.stack.enter_context(patch.object(transitions, "supersession_index", indexing))
        return calls

    def assert_whole(self):
        """What the read worked out is what folding every one of its runs works out."""
        records = self.records
        silent = {run_dir.name: age for run_dir, state in records
                  for age in [menu.silent_for_run(run_dir, state, now=NOW)] if age}
        self.assertEqual(menu.FOLDS.of(records, NOW), (
            transitions.supersession_index(records), transitions.runs_by_seat(records), silent))
        self.assertEqual(self.groups, menu.v5o_groups(self.cfg, self.found, list(records),
                                                      look=False))

    def test_1_a_read_folds_each_open_run_once(self):
        calls = self.counted()
        # merged under a title runs at rest share, then a read with nothing changed
        going(1, state="pass", merged=True, title="Fix 0", finished_at=NOW)
        for _ in range(2):
            self.assertEqual(len(self.read()), ENDED + OPEN)
            for fold, asked in calls.items():
                self.assertLessEqual(asked, OPEN, f"a read asks {fold} of the runs at rest")
                calls[fold] = 0

    def test_2_what_a_read_works_out_is_what_folding_every_run_does(self):
        given = menu.FOLDS.of(self.records, NOW)
        before = ({key: list(entries) for key, entries in given[0].items()},
                  {seat: list(runs) for seat, runs in given[1].items()}, dict(given[2]))
        cases = {
            "nothing changed": lambda: None,
            "one open run changed": lambda: going(1, step="reviewer"),
            "one open run ended": lambda: going(2, state="pass", finished_at=NOW, merged=True),
            "and came to rest": lambda: os.utime(config.RUNS / "s02/run.json",
                                                 (NOW - WEEK, NOW - WEEK)),
            "at a full read": self.full,
            # listed between two runs at rest, merged as one of them was and finishing with it
            "a new run": lambda: going(OPEN, "r02799b", state="pass", merged=True, title="Fix 0",
                                       finished_at=NOW - WEEK + 2800 // 3,
                                       launched_session="acme-api"),
            "a run that merged an older run's title": lambda: going(
                3, state="pass", merged=True, title="Fix 0", finished_at=NOW - WEEK),
            "a seat renamed": lambda: config.session_path("acme-web").write_text(
                json.dumps({"renamed": "acme-www"})),
        }
        for case, change in cases.items():
            with self.subTest(case):
                change()
                self.read()
                self.assert_whole()
        self.assertIn("acme-www", menu.FOLDS.of(self.records, NOW)[1])
        self.assertEqual(before, given, "a read's answers changed after")

    def test_3_the_look_after_a_read_folds_nothing(self):
        going(1, step="reviewer")
        self.read()
        calls = self.counted()
        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        live.read_from = self.found, self.records
        live.passing.acquire()
        live._look(self.found, self.records)
        self.assertEqual(calls, {"launched_session": 0, "silent_for_run": 0,
                                 "supersession_index": 0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
