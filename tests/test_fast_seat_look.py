"""A seat's look is fast: ak's own tmux calls skip the seat guard, and a pass over the runs
parses only the run.json files that changed.

A look runs from a seat's hook, so it inherits the seat's environment and PATH, where `tmux` is
the guard's shim: each call of ak's own paid for a Python start.  ak's calls run the first tmux
on PATH that is not the shim.  `menu.run_records` keeps what it read in one file under ak's
state, each row under its run.json's stat, and reads a record again only when that changed.

Offline: a sandbox HOME, fake tmux binaries that write down which of them ran, and runs written
there; what was parsed is counted at its run.json's read.
"""

import os
import sqlite3
from contextlib import closing
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox, parses
from agentkit import config, guard, menu, orch, parsed, record

TMUX = '#!/bin/sh\necho "{who} $*" >>"{log}"\nexit "${{ACME_TMUX_EXIT:-0}}"\n'


class OwnTmux(Sandbox):
    def setUp(self):
        super().setUp()
        self.log = self.root / "tmux-calls"
        self.dirs = {"shim": guard.shim_dir(), "real": self.root / "real",
                     "ahead": self.root / "ahead"}
        for who, folder in self.dirs.items():
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "tmux").write_text(TMUX.format(who=who, log=self.log))
            (folder / "tmux").chmod(0o755)
        # a seat's own environment, as a hook-started look inherits it
        self.stack.enter_context(patch.dict(os.environ, {config.SESSION_ENV: "acme"}))
        os.environ.pop("AK_RUN_ROLE", None)
        self.path("shim", "real")

    def path(self, *names):
        os.environ["PATH"] = os.pathsep.join(
            [*(str(self.dirs[name]) for name in names), os.environ["PATH"]])

    def ran(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_a_call_from_a_seat_runs_the_real_tmux_never_the_shim(self):
        self.assertEqual(orch.tmux_out("list-sessions", socket="acme-test"), (0, ""))
        orch.tmux_version()
        self.assertEqual(self.ran(), ["real -L acme-test list-sessions", "real -V"])

    def test_a_tmux_ahead_of_the_shim_is_the_one_used(self):
        self.path("ahead", "shim", "real")
        orch.tmux_out("list-sessions", socket="acme-test")
        self.assertEqual(self.ran(), ["ahead -L acme-test list-sessions"])

    def test_a_failed_call_no_scope_was_made_for_is_not_run_again(self):
        # with no user manager the command is not wrapped, so its failure is tmux's own answer
        with patch.object(orch, "user_manager", return_value=False), \
                patch.dict(os.environ, {"ACME_TMUX_EXIT": "1"}):
            rc, _ = orch.tmux_out("new-session", socket="acme-test", unit="agentkit-seat-acme")
        self.assertEqual(rc, 1)
        self.assertEqual(self.ran(), ["real -L acme-test new-session"])


class RunRecords(Sandbox):
    def setUp(self):
        super().setUp()
        # every run here was written long before: a pass keeps what it parses (`parsed`)
        self.stack.enter_context(patch.object(parsed, "FRESH", 0))

    def write(self, name, **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {"run_id": name, "state": "pass", **extra})
        return directory

    def today(self):
        """What a pass that reads every run.json returns."""
        return [(run_dir, state) for run_dir in record.run_dirs()
                for state in [record.read_state(run_dir)]
                if state is not None and not state.get("unattended") and not menu.smoke_run(state)]

    def parsed(self):
        expected = self.today()
        with parses() as names:
            found = menu.run_records()
        self.assertEqual(found, expected)
        return sorted(names)

    def test_only_a_changed_or_new_run_is_parsed_again(self):
        acme = self.write("20260101-0900-acme")
        fix = self.write("20260101-0901-fix-api", state="running")
        worker = self.write("20260101-0902-worker", unattended=True)
        smoke = self.write("20260101-0903-smoke", task=str(config.TMP / "smoke-1" / "task.md"))
        self.assertEqual(self.parsed(), sorted(d.name for d in (acme, fix, worker, smoke)))
        self.assertTrue((config.STATE / menu.RUN_RECORDS).is_file())
        self.assertEqual(self.parsed(), [])       # nothing changed: nothing parsed

        state = record.read_state(fix)
        state["state"] = "fail"
        record.save_state(fix, state)
        docs = self.write("20260101-0904-docs")
        self.assertEqual(self.parsed(), [fix.name, docs.name])
        self.assertEqual(self.parsed(), [])

    def test_a_kept_run_whose_repo_now_resolves_into_a_smoke_sandbox_is_left_out(self):
        # which runs are the suite's is asked of the paths on every pass, not of the record alone
        (self.root / "acme").mkdir()
        (config.TMP / "smoke-1" / "acme").mkdir(parents=True)
        repo = self.root / "repo"
        repo.symlink_to(self.root / "acme")
        acme = self.write("20260101-0900-acme", repo=str(repo))
        self.assertEqual(self.parsed(), [acme.name])
        repo.unlink()
        repo.symlink_to(config.TMP / "smoke-1" / "acme")
        self.assertEqual(self.parsed(), [])       # left out, and no record parsed

    def test_a_removed_run_leaves_the_kept_file(self):
        acme, fix = self.write("20260101-0900-acme"), self.write("20260101-0901-fix-api")
        self.parsed()
        (fix / "run.json").unlink()
        fix.rmdir()
        self.assertEqual(self.parsed(), [])
        with closing(sqlite3.connect(config.STATE / menu.RUN_RECORDS)) as db:
            self.assertEqual(list(db.execute("SELECT name FROM records")), [(acme.name,)])


if __name__ == "__main__":
    unittest.main()
