"""A read of the runs for the menu's frame does no work whose answer it already has: a running
run whose record or log was written within the hour is not walked through for its newest file,
the sandbox and each path a run names are resolved once a pass, and the seat many runs name is
followed through its renames once.

The owner's report (18 Oct 2026): ak still took well over a second to its first frame.  With a
few thousand runs, each read resolved the sandbox again for every run, walked every file of
every busy run, and read the record of the seat a run named once for each run.  Offline: a
temporary HOME, the clock and the files' times chosen; nothing walks a real run.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, handback, menu, orch, record, watch  # noqa: E402

NOW = 100000


def run(name, at, **state):
    """A running run whose every file was last written at `at`."""
    directory = config.RUNS / name
    directory.mkdir(parents=True)
    record.save_state(directory, {"run_id": name, "state": "running", **state})
    (directory / "log.txt").write_text("step\n")
    for path in directory.iterdir():
        os.utime(path, (at, at))
    return directory


class SkipsKnownWork(Sandbox):
    def test_a_busy_run_is_not_walked_and_a_quiet_one_still_says_how_long(self):
        busy, quiet = run("busy", NOW - 60), run("quiet", NOW - 2 * 3600)
        walks = self.stack.enter_context(patch.object(watch, "run_last_write",
                                                      wraps=watch.run_last_write))
        self.assertIsNone(menu.silent_for_run(busy, record.read_state(busy), now=NOW))
        self.assertEqual(menu.silent_for_run(quiet, record.read_state(quiet), now=NOW), "2h")
        self.assertEqual([call.args[0].name for call in walks.call_args_list], ["quiet"])

    def test_the_sandbox_and_each_path_resolve_once_a_pass(self):
        states = [{"task": str(config.RUNS / f"run-{n}" / "task.md"), "repo": "/c/acme"}
                  for n in range(20)]
        smoke = {"task": str(config.TMP / "smoke-1" / "task.md")}
        (config.TMP / "other").mkdir(parents=True)
        (config.TMP / "smoke-2").symlink_to(config.TMP / "other")
        beside = {"task": str(config.TMP / "smoke-2" / "task.md")}  # resolves to `other`
        resolve = self.stack.enter_context(patch.object(menu.os.path, "realpath",
                                                        wraps=os.path.realpath))
        resolved = {}
        self.assertEqual([menu.smoke_run(state, resolved) for state in [*states, smoke, beside]],
                         [False] * 20 + [True, False])
        self.assertEqual(resolve.call_count, 1 + 20 + 1 + 2)    # the sandbox, then each path

    def test_a_link_that_loops_in_the_sandbox_names_no_run_of_the_suite_s(self):
        (config.TMP / "smoke-3").mkdir(parents=True)
        (config.TMP / "smoke-3" / "loop").symlink_to("loop")
        self.assertFalse(menu.smoke_run({"task": str(config.TMP / "smoke-3" / "loop"),
                                         "repo": "/c/acme"}))

    def test_a_parent_step_cannot_erase_a_loop_in_an_owner_s_task_link(self):
        smoke = config.TMP / "smoke-3"
        smoke.mkdir(parents=True)
        (smoke / "task.md").write_text("# acme\n")
        (smoke / "loop").symlink_to("loop")
        target = str(smoke / "loop") + "/../task.md"
        task = self.root / "task.md"
        task.symlink_to(target)
        for value in (target, str(task), "~/task.md"):
            for key in ("task", "repo"):
                with self.subTest(path=value, key=key):
                    self.assertFalse(menu.smoke_run({key: value}))

    def test_filing_follows_each_seat_s_renames_once(self):
        runs = [{"launched_session": name, "repo": "/c/acme"}
                for name in ("acme-api", "acme-docs") * 15]
        follows = self.stack.enter_context(patch.object(config, "resolve_session",
                                                        wraps=config.resolve_session))
        self.stack.enter_context(patch.object(handback, "session_vote", return_value=False))
        orch.file_projectless([{"name": "acme-api"}], runs)
        self.assertEqual(sorted(call.args[0] for call in follows.call_args_list),
                         ["acme-api", "acme-docs"])


if __name__ == "__main__":
    unittest.main()
