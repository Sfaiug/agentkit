"""A pass over every seat reads each thing once (`look.one_look`), and only a pass keeps anything.

In-process, counting what a pass asks the disk for: no black-box check can tell that apart under a
host's noise.
"""

import builtins
from collections import Counter
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import (config, handback, look, menu, notify, open_runs, orch, parsed, record,
                      status, watch)

LIVE = ["acme-api", "acme-cli", "acme-web"]
GONE = "acme-gone"
PAST = [f"acme-past-{n}" for n in range(27)]
POINTERS = {f"acme-was-{n}": PAST[n] for n in range(3)}
WEEK = 7 * 86400
LINE = ".merge-acme.lock"
OPEN = "acme-landing"
REAL_SESSIONS = orch.sessions
ROWS = "".join(f"{name}\\t/acme\\t1\\t0\\t1\\n" for name in LIVE)
TMUX = f'#!/bin/sh\ncase "$*" in *list-sessions*) printf "{ROWS}";; esac\n'


def written_long_ago(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    then = time.time_ns() - WEEK * 10**9
    os.utime(path, ns=(then, then))


class APassReadsEachThingOnce(Sandbox):
    def setUp(self):
        super().setUp()
        tmux = self.root / "bin" / "tmux"
        tmux.parent.mkdir()
        tmux.write_text(TMUX)
        tmux.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ,
                                            {"PATH": f"{tmux.parent}:{os.environ['PATH']}"}))
        self.stack.enter_context(patch.object(orch, "sessions", REAL_SESSIONS))
        self.stack.enter_context(patch.object(menu, "_RUN_RECORDS", None))
        self.addCleanup(lambda: menu._RUN_RECORDS and menu._RUN_RECORDS.close())
        (config.HOME / config.CONFIG_NAME).write_text(
            (config.REPO / config.DEFAULT_CONFIG_NAME).read_text())
        self.cfg = config.load()
        seat = {"orchestrator": self.cfg["defaults"]["orchestrator"], "workers": [],
                "repo": None, "filed": True, "cwd": "/acme", "created": 1}
        for name in [*LIVE, GONE, *PAST]:
            written_long_ago(config.session_path(name), seat)
        for name, leads in POINTERS.items():
            written_long_ago(config.session_path(name), {"renamed": leads})
        for name in [*LIVE, GONE]:
            notify.record(name, "needs", "Which one?")
        names = [*PAST, *POINTERS]
        for n in range(300):
            written_long_ago(config.RUNS / f"acme-run-{n}" / "run.json",
                             {"run_id": f"acme-run-{n}", "state": "pass", "verdict": "PASS",
                              "merged": True, "launched_session": names[n % len(names)]})
        written_long_ago(config.RUNS / OPEN / "run.json",
                         {"run_id": OPEN, "state": "waiting", "launched_session": LIVE[0],
                          "target": "main", "waiting_on": {"line": LINE, "joined": 1}})
        written_long_ago(watch.state_path(), {"tick": 1})
        for _ in range(2):         # the first read's own writes settle too, and `parsed` keeps all
            time.sleep(parsed.FRESH / 1e9 + 0.1)
            self.found, self.records, _groups = menu.rows(self.cfg)

    @contextmanager
    def counted(self):
        """What is asked of the disk meanwhile: (stats, opens), by path."""
        stats, opens, stat, opened = Counter(), Counter(), os.stat, io.open

        def stating(path, *args, **kwargs):
            stats[str(path)] += 1
            return stat(path, *args, **kwargs)

        def opening(path, *args, **kwargs):
            opens[str(path)] += 1
            return opened(path, *args, **kwargs)

        with patch.object(os, "stat", stating), patch.object(io, "open", opening), \
                patch.object(builtins, "open", opening):
            yield stats, opens

    def look_pass(self, groups=None):
        """One pass as `Live._look` makes it, the next read it asks for left out."""
        live = menu.Live(self.cfg)
        self.addCleanup(os.close, live.reader)
        self.addCleanup(os.close, live.writer)
        live.passing.acquire()
        with patch.object(menu.Live, "meet"), patch.object(menu.Live, "ask"), \
                patch.object(menu, "v5o_groups", groups or menu.v5o_groups):
            live._look(self.found, self.records)

    def assert_each_asked_once(self, stats, opens):
        for name in [*PAST, *POINTERS]:
            self.assertLessEqual(stats[str(config.session_path(name))], 2, name)
        for path, most in ((watch.state_path(), 1), (config.HOME / config.CONFIG_NAME, 1),
                           *((config.notify_path(name), 0) for name in [*LIVE, GONE])):
            self.assertLessEqual(opens[str(path)], most, path)
        for adapter in (config.REPO / "adapters").glob("*.toml"):
            self.assertLessEqual(stats[str(adapter)], 1, adapter)

    def test_a_read_and_a_look_ask_for_each_thing_once(self):
        with self.counted() as (stats, opens):
            menu.rows(self.cfg)
        self.assert_each_asked_once(stats, opens)
        with self.counted() as (stats, opens):
            self.look_pass()
        self.assert_each_asked_once(stats, opens)

    def test_a_look_asks_for_the_open_runs_alone_and_a_seat_still_reads_its_place(self):
        real, placed = menu.v5o_groups, []

        def groups(*args, **kwargs):
            real(*args, **kwargs)
            placed.append(status.parked_line(record.read_state(config.RUNS / OPEN)))

        with self.counted() as (stats, _):
            self.look_pass(groups)
        self.assertLessEqual({Path(path).parent.name for path in stats
                              if path.endswith("/run.json")}, {OPEN})
        self.assertEqual(placed, ["waiting · 1st in line to land on main"])

    def test_a_look_with_no_read_behind_it_reads_the_runs_itself(self):
        seen, census = [], menu._RUN_RECORDS
        self.addCleanup(census.close)
        with patch.object(menu, "_RUN_RECORDS", None):
            self.look_pass(lambda *_a, **_k: seen.extend(record.runs()))
        self.assertEqual(len(seen), 301)
        with look.one_look():      # a reader lends nothing before its first read
            open_runs.Reader().lend()
            self.assertEqual(len(record.runs()), 301)

    def test_outside_a_pass_nothing_is_kept(self):
        self.assertEqual(config.resolve_session(PAST[9]), PAST[9])
        config.rename_session(PAST[9], "acme-moved")
        self.assertEqual(config.resolve_session(PAST[9]), "acme-moved")
        self.assertNotIn("acme-new", config.session_records())
        written_long_ago(config.session_path("acme-new"), {"orchestrator": "acme", "workers": []})
        self.assertIn("acme-new", config.session_records())
        first = config.session_records()
        first.clear()
        self.assertIn(LIVE[0], config.session_records())

    def test_in_a_pass_each_caller_has_its_own_dict_and_a_write_shows_by_the_next(self):
        with look.one_look():
            first, second = config.session_records(), config.session_records()
            self.assertIs(first[LIVE[0]], second[LIVE[0]])
            first.clear()
            self.assertIn(LIVE[0], second)
            config.update_session(LIVE[0], repo="/acme")
            self.assertIsNone(config.session_records()[LIVE[0]]["repo"])
        self.assertEqual(config.session_records()[LIVE[0]]["repo"], "/acme")

    def test_a_pass_opened_after_a_change_reads_it(self):
        with look.one_look():
            self.assertEqual(config.resolve_session(PAST[9]), PAST[9])
            self.assertEqual(notify.last(LIVE[0])["text"], "Which one?")
            self.assertNotIn("GitHub", watch.session_state(LIVE[0], cfg=self.cfg)["reason"])
            notify.record(LIVE[0], "needs", "Which other one?")     # in a pass: never missed
            self.assertEqual(notify.last(LIVE[0])["text"], "Which other one?")
        config.rename_session(PAST[9], "acme-moved")
        notify.record(LIVE[0], "needs", "Which last one?")
        watch.state_path().write_text(json.dumps({"tick": 2, "gh_out": {"at": 1}}))
        with look.one_look():
            self.assertEqual(config.resolve_session(PAST[9]), "acme-moved")
            self.assertEqual(notify.last(LIVE[0])["text"], "Which last one?")
            self.assertIn("GitHub", watch.session_state(LIVE[0], cfg=self.cfg)["reason"])

    def test_a_notice_answered_leaves_what_every_reader_shares_as_it_was(self):
        shared, other = notify.last(LIVE[0]), notify.last(LIVE[1])
        self.assertIs(notify.last(LIVE[0]), shared)
        before = dict(shared), dict(other)
        notify.answered(LIVE[0], time.time_ns() / 1e9)
        notify.opened(LIVE[1], lambda: "pane")
        self.assertEqual((shared, other), before)

    def test_a_raised_answer_is_not_kept(self):
        broken = config.session_path(PAST[9])
        broken.write_text("{")
        with look.one_look():
            for _ in range(2):
                with self.assertRaises(config.Error):
                    config.resolve_session(PAST[9])
            broken.write_text(json.dumps({"renamed": PAST[10]}))
            self.assertEqual(config.resolve_session(PAST[9]), PAST[10])

    def test_a_writer_under_a_lock_decides_on_the_disk_as_it_is(self):
        with look.one_look():
            self.assertEqual(config.resolve_session(PAST[9]), PAST[9])
            config.session_records()
            config.update_session(PAST[10], repo="/acme", filed=True)
            self.assertEqual(handback.join_session_project(PAST[10], []), "/acme")
            config.rename_session(PAST[9], "acme-moved")
            with notify.session_lock(PAST[9]) as held:
                self.assertEqual(held, "acme-moved")


if __name__ == "__main__":
    unittest.main()
