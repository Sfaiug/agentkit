"""A read costs the open runs it looks at: the 6,000 at rest add one listing of plain strings, and
a record that did not change has its paths resolved only at a full read.

In-process, for what no black-box check can see, as tests/test_run_records_read_once.py is; the
screen-level bound is tests/test_key_runs_at_rest_cost_an_open_screen_little.py.  A cost is
`time.thread_time`, against the same thread doing what a read used to, so a slow host raises both.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, menu, open_runs, parsed

RUNS = 6000
OPEN = 5
WEEK = 7 * 86400


def write(directory, *, ago=0, **extra):
    """A run's record naming paths of its own, written `ago` seconds ago."""
    directory.mkdir(parents=True, exist_ok=True)
    state = {"run_id": directory.name, "state": "pass", "repo": str(directory / "repo"),
             "task": str(directory / "task.md"), **extra}
    temporary = directory / "run.tmp"
    temporary.write_text(json.dumps(state))
    temporary.replace(directory / "run.json")
    if ago:
        written = time.time() - ago
        os.utime(directory / "run.json", (written, written))


def read():
    return menu.run_records(rest_may_lag=True)


def fresh():
    """What a reader that has seen nothing finds."""
    return open_runs.Reader().read(menu.attended, lambda *_: None)


def later(reads=1):
    """Past the next full read, for `reads` of them."""
    clock = open_runs.time.monotonic
    return patch.object(open_runs.time, "monotonic",
                        lambda: clock() + reads * (open_runs.CEILING + 1))


@contextmanager
def resolving():
    """The paths `os.path.realpath` is asked of meanwhile."""
    real, paths = os.path.realpath, []

    def counting(path, **kw):
        paths.append(path)
        return real(path, **kw)

    with patch.object(os.path, "realpath", counting):
        yield paths


class ReadOfTheOpenRuns(Sandbox):
    def setUp(self):
        super().setUp()
        # Every run here was written long before, so `parsed` keeps it and it is at rest; full
        # reads wait for `later`, however long this host took over the first.
        self.stack.enter_context(patch.object(parsed, "FRESH", 0))
        self.stack.enter_context(patch.object(open_runs, "SHARE", 1e-9))
        for n in range(RUNS):
            write(config.RUNS / f"rest-{n:04}", ago=WEEK)
        self.open = [config.RUNS / f"open-{n}" for n in range(OPEN)]
        for directory in self.open:
            write(directory, ago=WEEK, state="running")
        self.first = read()

    def moved(self, change):
        """`change` to the directory of runs, its stat changed for certain: two changes inside
        one tick of the filesystem's clock can leave it reading the same, as `parsed` says."""
        change()
        info = os.stat(config.RUNS)
        os.utime(config.RUNS, ns=(info.st_atime_ns, info.st_mtime_ns + 1))

    def test_a_lock_file_costs_a_listing_of_strings(self):
        names = [str(directory) for directory, _ in self.first]
        # as a read did: new Paths against those of the last list, which have been compared before
        kept = [Path(name) for name in names]
        self.assertEqual(kept, [Path(name) for name in names])
        reads, yardsticks = [], []
        for n in range(3):
            self.moved((config.RUNS / f"merge-{n}.lock").touch)
            began = time.thread_time()
            found = read()
            reads.append(time.thread_time() - began)
            self.assertIs(found, self.first)
            began = time.thread_time()
            listed = [Path(name) for name in names]
            same = listed == kept
            yardsticks.append(time.thread_time() - began)
            self.assertTrue(same)
        self.assertLess(min(reads) * 3, min(yardsticks), (reads, yardsticks))

    def test_only_a_changed_record_or_a_full_read_resolves_paths(self):
        with resolving() as paths:
            for _ in range(3):
                read()
        self.assertEqual(paths, [])

        changed = self.open[0]
        write(changed, ago=WEEK, state="running", round=2)
        with resolving() as paths:
            self.assertEqual(dict(read())[changed]["round"], 2)
        # and the sandbox they are held against, once for the read
        self.assertLessEqual(set(paths), {str(changed / "repo"), str(changed / "task.md"),
                                          config.TMP})
        self.assertIn(str(changed / "task.md"), paths)

        with resolving() as paths, later():
            read()
        for directory in (config.RUNS / "rest-0000", config.RUNS / f"rest-{RUNS - 1}", changed):
            self.assertIn(str(directory / "task.md"), paths)
            self.assertIn(str(directory / "repo"), paths)
        self.assertGreaterEqual(len(paths), 2 * (RUNS + OPEN))

    def test_a_symlink_that_moved_shows_by_the_next_full_read(self):
        smoke = config.TMP / "smoke-acme"
        smoke.mkdir(parents=True)
        link, directory = self.root / "link", self.open[0]
        link.symlink_to(self.root)
        write(directory, ago=WEEK, state="running", repo=str(link))
        self.assertIn(directory, dict(read()))
        link.unlink()
        link.symlink_to(smoke)
        self.assertIn(directory, dict(read()))        # no record changed: as it found it
        with later():
            self.assertNotIn(directory, dict(read()))

    def test_plainly_asked_every_run_is_looked_at_and_every_path_resolved(self):
        with resolving() as paths:
            found = menu.run_records()
        self.assertEqual(found, self.first)
        self.assertGreaterEqual(len(paths), 2 * (RUNS + OPEN))

    def test_the_answer_is_a_fresh_readers(self):
        new = config.RUNS / "new"
        lock = config.RUNS / "merge.lock"
        steps = {"a new directory": lambda: write(new),
                 "a directory removed": lambda: shutil.rmtree(new),
                 "a directory at rest removed": lambda: shutil.rmtree(config.RUNS / "rest-0007"),
                 "a lock file added": lock.touch,
                 "a lock file removed": lock.unlink}
        before, last = list(self.first), self.first
        for name, step in steps.items():
            with self.subTest(name):
                self.moved(step)
                found = read()
                self.assertEqual(found, fresh())
                self.assertTrue(all(isinstance(directory, Path) for directory, _ in found))
                if "lock" in name:
                    self.assertIs(found, last)
                self.assertIs(read(), found)          # nothing changed: the same object
                last = found
        self.assertEqual(self.first, before)          # never changed in place

    def test_a_directory_keeps_its_path_while_listed(self):
        before = {directory.name: directory for directory, _ in self.first}
        self.moved(lambda: write(config.RUNS / "new"))
        for directory, _ in read():
            if directory.name != "new":
                self.assertIs(directory, before[directory.name])

    def test_save_is_told_what_it_was(self):
        reader, told = open_runs.Reader(), []
        save = lambda looked, went: told.append((list(looked), went))
        reader.read(menu.attended, save)
        self.assertEqual(sorted(run.name for run in told[-1][0]),
                         sorted(directory.name for directory, _ in self.first))
        self.assertIsNone(told[-1][1])                # a full read: every run was looked at
        gone = self.open[1]
        self.moved(lambda: shutil.rmtree(gone))
        reader.read(menu.attended, save)
        self.assertEqual(sorted(run.name for run in told[-1][0]),
                         sorted(directory.name for directory in self.open if directory != gone))
        self.assertEqual(told[-1][1], [gone.name])


if __name__ == "__main__":
    unittest.main(verbosity=2)
