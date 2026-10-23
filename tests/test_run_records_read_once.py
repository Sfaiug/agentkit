"""Offline run listings: one cache load, only changed records, bounded concurrent writes."""

from collections import Counter
from contextlib import closing
import json
import multiprocessing
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, menu, record


def write(directory, **extra):
    directory.mkdir(parents=True, exist_ok=True)
    state = {"run_id": directory.name, "state": "pass", "repo": "acme",
             "detail": {"steps": ["finished"], "text": "x" * 4096}, **extra}
    temporary = directory / "run.tmp"
    temporary.write_text(json.dumps(state))
    temporary.replace(directory / "run.json")


def full():
    return [(directory, state) for directory in record.run_dirs()
            for state in [record.read_state(directory)]
            if state is not None and not state.get("unattended") and not menu.smoke_run(state)]


def written():
    # SQLite writes through C, past Python's file wrappers. Count bytes handed to write(2),
    # including on tmpfs, rather than timing the filesystem or counting SQL statements.
    return int(dict(line.split(": ", 1) for line in
                    Path("/proc/self/io").read_text().splitlines())["wchar"])


def reader(root, pipe):
    config.RUNS, config.STATE, config.TMP = (Path(root) / name for name in ("runs", "state", "tmp"))
    try:
        while pipe.recv() == "read":
            with patch.object(record, "read_state", wraps=record.read_state) as read:
                before = written()
                found = menu.run_records()
                size = written() - before
            pipe.send(([(directory.name, state) for directory, state in found],
                       [call.args[0].name for call in read.call_args_list], size))
    finally:
        if menu._RUN_RECORDS is not None:
            menu._RUN_RECORDS.close()
        pipe.close()


class RunRecords(Sandbox):
    def runs(self, count):
        for i in range(count):
            write(config.RUNS / f"finished-{i:04}")
        live = config.RUNS / "live"
        write(live, state="running")
        return live

    def test_repeated_calls_open_the_cache_and_each_record_at_most_once(self):
        live = self.runs(320)
        expected, opened, real_open = full(), Counter(), Path.open
        connections, connect, queries = [], sqlite3.connect, []

        def opening(path, mode="r", *args, **kwargs):
            if mode == "r":
                opened[path] += 1
            return real_open(path, mode, *args, **kwargs)

        def connecting(*args, **kwargs):
            db = connect(*args, **kwargs)
            db.set_trace_callback(queries.append)
            connections.append(db)
            return db

        with patch.object(Path, "open", opening), patch.object(sqlite3, "connect", connecting):
            for _ in range(12):
                self.assertEqual(menu.run_records(), expected)
            self.assertEqual(len(connections), 1)
            self.assertEqual(opened, Counter({directory / "run.json": 1
                                             for directory, _ in expected}))
        opened.clear()
        write(live, state="running", round=2)
        expected = full()
        with patch.object(Path, "open", opening), patch.object(sqlite3, "connect", connecting):
            for _ in range(12):
                self.assertEqual(menu.run_records(), expected)
        self.assertEqual(opened, Counter({live / "run.json": 1}))
        self.assertEqual(len(connections), 1)
        self.assertEqual(sum(query.startswith("SELECT ") for query in queries), 1)

    def test_one_update_writes_a_bounded_amount_as_history_grows(self):
        live = self.runs(4)
        menu.run_records()
        sizes = []
        for count in (4, 320):
            self.runs(count)
            menu.run_records()
            write(live, state="running", round=2)
            before = written()
            found = menu.run_records()
            sizes.append(written() - before)
            self.assertEqual(found, full())
        self.assertGreater(sizes[0], 0)
        self.assertLess(max(sizes), 65536, sizes)
        self.assertLessEqual(sizes[1], sizes[0] + 16384, sizes)

    def test_processes_read_complete_rows_while_another_writer_holds_the_cache(self):
        live = self.runs(80)
        menu.run_records()
        context = multiprocessing.get_context("spawn")
        workers = []
        try:
            for _ in range(2):
                parent, child = context.Pipe()
                process = context.Process(target=reader, args=(str(self.root), child))
                process.start()
                child.close()
                workers.append((process, parent))
            with closing(sqlite3.connect(config.STATE / menu.RUN_RECORDS)) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE records SET value = value WHERE name = 'live'")
                for _, pipe in workers:
                    pipe.send("read")
                expected = [(directory.name, state) for directory, state in full()]
                for _, pipe in workers:
                    self.assertTrue(pipe.poll(30), "reader did not return under a writer's lock")
                    found, reads, size = pipe.recv()
                    self.assertEqual(found, expected)
                    self.assertEqual(reads, [])    # a fresh process reused the disk cache
                    self.assertLess(size, 65536)
                write(live, state="running", round=2)
                for _, pipe in workers:
                    pipe.send("read")
                expected = [(directory.name, state) for directory, state in full()]
                for _, pipe in workers:
                    self.assertTrue(pipe.poll(30))
                    found, reads, size = pipe.recv()
                    self.assertEqual(found, expected)
                    self.assertEqual(reads, ["live"])
                    self.assertLess(size, 65536)
                db.rollback()
            # Both readers missed their cache write under the lock. Another process still
            # finds the changed record by stat; no cache entry can conceal a disk change.
            self.assertEqual(menu.run_records(), full())
            write(live, state="pass", round=3)
            for _, pipe in workers:
                pipe.send("read")
            expected = [(directory.name, state) for directory, state in full()]
            for _, pipe in workers:
                self.assertTrue(pipe.poll(30))
                found, reads, size = pipe.recv()
                self.assertEqual(found, expected)
                self.assertEqual(reads, ["live"])
                self.assertLess(size, 65536)
            with closing(sqlite3.connect(config.STATE / menu.RUN_RECORDS)) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
        finally:
            for process, pipe in workers:
                try:
                    pipe.send("stop")
                except (BrokenPipeError, OSError):
                    pass
                process.join(10)
                if process.is_alive():
                    process.terminate()
                    process.join(10)
                pipe.close()
            self.assertEqual([process.exitcode for process, _ in workers], [0, 0])

    def test_unchanged_records_are_reused_and_updates_replace_only_the_changed_snapshot(self):
        live = self.runs(80)
        first = dict(menu.run_records())
        for _ in range(12):
            for directory, state in menu.run_records():
                self.assertIs(state, first[directory])
        write(live, state="pass", detail={"steps": ["landed"]})
        current = dict(menu.run_records())
        self.assertEqual(current, dict(full()))
        self.assertIsNot(current[live], first[live])
        self.assertEqual(first[live]["state"], "running")
        self.assertEqual(first[live]["detail"]["steps"], ["finished"])
        for directory in first.keys() - {live}:
            self.assertIs(current[directory], first[directory])

    def test_additions_removals_and_bad_records_match_disk(self):
        live = self.runs(3)
        self.assertEqual(menu.run_records(), full())
        write(config.RUNS / "new", unattended=True)
        (config.RUNS / "finished-0000" / "run.json").unlink()
        (live / "run.json").write_text('{"state":')
        self.assertEqual(menu.run_records(), full())
        write(live, state="running")
        self.assertEqual(menu.run_records(), full())

    def test_the_cache_before_the_database_is_removed(self):
        self.runs(3)
        old = [config.STATE / name for name in
               ("run-records.jsonl", "run-records.lock", "run-records.tmp")]
        for path in old:
            path.write_text("[]\n")
        self.assertEqual(menu.run_records(), full())
        self.assertEqual([path for path in old if path.exists()], [])
        self.assertTrue((config.STATE / menu.RUN_RECORDS).exists())

    def test_cache_failure_does_not_prevent_process_local_reuse(self):
        self.runs(20)
        with patch.object(sqlite3, "connect", side_effect=sqlite3.OperationalError("locked")):
            self.assertEqual(menu.run_records(), full())
        with patch.object(record, "read_state", wraps=record.read_state) as read:
            menu.run_records()
        read.assert_not_called()

    def test_uncached_reads_leave_persistent_caches_untouched(self):
        live = self.runs(3)
        for warm in (False, True):
            with self.subTest(warm=warm):
                if warm:
                    menu.run_records()
                for name in ("run-records.jsonl", "run-records.lock", "run-records.tmp"):
                    (config.STATE / name).write_text("[]\n")
                write(live, state="running", round=2 if warm else 1)
                before = {path.name: path.read_bytes() for path in config.STATE.iterdir()
                          if path.is_file()}
                self.assertEqual(menu.run_records(cache=False), full())
                self.assertEqual({path.name: path.read_bytes() for path in config.STATE.iterdir()
                                  if path.is_file()}, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
