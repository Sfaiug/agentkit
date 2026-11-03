"""A screen's read decides again only the seats whose inputs changed, and every seat once its row is
`open_runs.CEILING` old: each read decided all of a host's 68 seats, the largest part of the read's CPU, though
almost every row was the one before.  In-process, on a temporary HOME with a fake tmux, counting
the seats a read decides by the two things deciding one asks."""

import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, menu, notify, open_runs, orch, record, watch

LIVE = ["acme-api", "acme-cli", "acme-web"]
GONE = [f"acme-past-{n:02}" for n in range(60)]
REAL_SESSIONS = orch.sessions
RUNNING = GONE[9]          # its run is open, so every read reads its record
ROWS = "".join(f"{name}\\t/acme\\t1\\t0\\t1\\n" for name in LIVE)
TMUX = f'#!/bin/sh\ncase "$*" in *list-sessions*) printf "{ROWS}";; esac\n'
PLAN = "- [x] Fix it · check: `true` · acme\n- [ ] Ship it · check: `false` · acme\n"


def written_long_ago(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    then = time.time_ns() - 7 * 86400 * 10**9      # the real clock: a sandbox fixes time.time
    os.utime(path, ns=(then, then))


class AReadDecidesOnlyTheSeatsThatChanged(Sandbox):
    def setUp(self):
        super().setUp()
        (self.root / "tmux").write_text(TMUX)
        (self.root / "tmux").chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{self.root}:{os.environ['PATH']}"}))
        self.stack.enter_context(patch.object(orch, "sessions", REAL_SESSIONS))
        self.stack.enter_context(patch.object(menu, "_RUN_RECORDS", None))
        self.addCleanup(lambda: menu._RUN_RECORDS and menu._RUN_RECORDS.close())
        orchestrator = self.cfg["defaults"]["orchestrator"]
        for n, name in enumerate([*LIVE, *GONE]):
            written_long_ago(config.session_path(name), {
                "orchestrator": orchestrator, "workers": [], "repo": None, "filed": True,
                "cwd": "/acme", "created": 1 + n, "conversation": f"conv-{name}",
                "id_source": "launcher", "resumable": True})
            written_long_ago(config.plan_path(name), PLAN)
            written_long_ago(config.RUNS / f"run-{name}" / "run.json", {
                "run_id": f"run-{name}", "launched_session": name, "state": "pass",
                "verdict": "PASS", "merged": True, "started_at": 8000, "finished_at": 8500})
        self.run = config.RUNS / f"run-{RUNNING}"
        record.save_state(self.run, {**record.read_state(self.run), "state": "running",
                                     "step": "executor", "finished_at": None})
        self.kept = {}
        self.decided()
        self.assertEqual(len(self.listed), len(LIVE) + len(GONE))

    def decided(self):
        """The seats this screen's next read decides, by name, its rows checked against a read
        from scratch."""
        names, state, progress = set(), watch.session_state, menu.seat_progress

        def deciding(real):
            return lambda name, *args, **kwargs: (names.add(name), real(name, *args, **kwargs))[1]

        with patch.object(watch, "session_state", deciding(state)), \
                patch.object(menu, "seat_progress", deciding(progress)):
            found, _, groups = menu.rows(self.cfg, self.kept)
        self.listed = {seat["name"] for seat in found}
        self.assertEqual(groups, menu.rows(self.cfg, {})[2], "a kept row is not the one decided")
        return names

    def test_a_read_decides_only_the_seat_whose_input_changed(self):
        self.assertEqual(self.decided(), set())
        config.update_session(GONE[5], session_title="Fix the API")
        self.assertEqual(self.decided(), {GONE[5]})
        notify.record(GONE[7], "needs", "Which one?")
        self.assertEqual(self.decided(), {GONE[7]})
        record.save_state(self.run, {**record.read_state(self.run), "step": "reviewer"})
        self.assertEqual(self.decided(), {RUNNING})
        self.assertEqual(self.decided(), set())

    def test_a_row_ceiling_old_is_decided_again(self):
        later = time.monotonic() + open_runs.CEILING
        with patch.object(time, "monotonic", return_value=later):
            self.assertEqual(self.decided(), self.listed)
            self.assertEqual(self.decided(), set())

    def test_a_rename_shows_on_the_next_read(self):
        config.rename_session(GONE[11], "acme-moved")
        self.assertEqual(self.decided(), {"acme-moved"})
        self.assertIn("acme-moved", self.listed)
        self.assertNotIn(GONE[11], self.listed)


if __name__ == "__main__":
    unittest.main()
