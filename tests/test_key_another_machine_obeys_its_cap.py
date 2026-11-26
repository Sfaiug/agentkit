"""A machine with `[machines."NAME"] max_runs` runs at most that many model turns at once: a turn
that would be one more is turned away and runs here, and the next goes to the machine once the
first has ended; with no cap it takes both at once. A suite's pieces are neither counted nor
capped, and a cap that is not a whole number of 1 or more is refused.

Black-box, as tests/test_key_a_turn_runs_on_a_machine.py is, on tests/fixtures/akmachine.py with
four CPUs so CPU room is not what turns a turn away.
"""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

WHERE = 'echo "${container:-here}" >"${AK_HAND_IN%/*}/where"'
REVIEW = {"sh": WHERE, "final": "Handed in.", "hand_in": [["done"]]}
DONE = {"sh": f"{WHERE}; echo left >left.txt", "final": "## Summary\nedited", "hand_in": [["done"]]}


def wait_for(predicate, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class AnotherMachineObeysItsCap(unittest.TestCase):
    def setup_home(self, cap=None):
        """A Home with one 4-CPU Linux helper (`acme-linux`), optionally capped at `cap` turns."""
        home = Home()
        self.addCleanup(home.close)
        files = {"AGENTS.md": "---\nhealth: none\ntests: true\n---\n# repo\n",
                 "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"}
        first = Rig(home, "widgets", files=files)
        second = Rig(home, "gadgets", files=files)
        machine_table = '[machines.acme-linux]\nwork = ["turns", "tests"]\n'
        if cap is not None:
            machine_table += f"max_runs = {cap}\n"
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                       extra=machine_table)
        machine = akmachine.install(home, cpus=4)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        return home, machine, first, second

    def run_pair(self, cap):
        """Start one turn on `acme-linux` and hold it while a second run executes, then release it.
        Returns (first_turns, second_turns, suite_containers_during_first)."""
        home, machine, first, second = self.setup_home(cap=cap)
        sync = home.root / "adapters"
        sync.mkdir(exist_ok=True)
        started, release = sync / "started", sync / "release"
        hold = {
            "sh": (f"{WHERE}; : >{shlex.quote(str(started))}; "
                   f"while [ ! -e {shlex.quote(str(release))} ]; do sleep 0.05; done; "
                   "echo left >left.txt"),
            "final": "## Summary\nedited",
            "hand_in": [["done"]],
        }
        fakeadapter.install(home, claude=[hold, DONE], codex=REVIEW)
        task1 = taskfile.write(home, first.path, title="First task", done_when=("test -f left.txt",))
        task2 = taskfile.write(home, second.path, title="Second task",
                               done_when=("test -f left.txt",))
        env = {"AK_HOST_READINGS": akmachine.CROWDED}
        with ThreadPoolExecutor(max_workers=1) as pool:
            run1 = pool.submit(home.ak, "run", str(task1), "--no-merge", env=env, timeout=300)
            try:
                self.assertTrue(wait_for(lambda: started.exists() or run1.done()),
                                "first turn did not start")
                self.assertFalse(run1.done(), "first run ended before release")
                run2 = home.ak("run", str(task2), "--no-merge", env=env, timeout=300)
                suites_while_held = [p.name for p in (machine / "docker/roots").glob("*")
                                     if not p.name.endswith("-turn")]
            finally:
                release.touch()
            done1 = run1.result()
        self.assertEqual(done1.code, 0, done1.out + done1.err)
        self.assertEqual(run2.code, 0, run2.out + run2.err)
        by_title = {}
        for run in taskfile.runs(home):
            state = json.loads((run / "run.json").read_text())
            self.assertEqual(state["state"], "pass", state)
            by_title[state["title"]] = [path.read_text().strip()
                                        for path in sorted(run.rglob("where"))]
        return by_title["First task"], by_title["Second task"], suites_while_held

    def test_a_machine_capped_at_one_turns_the_next_away_and_takes_it_once_ended(self):
        first, second, suites = self.run_pair(cap=1)
        # First task's executor ran on the machine, then its reviewer ran on the machine once
        # the executor ended; the second task's turns while the first ran were turned away here.
        self.assertEqual(first, ["docker", "docker"])
        self.assertEqual(second, ["here", "here"])
        # The second task's done-when check (a suite) was not capped while the turn ran there.
        self.assertTrue(suites)

    def test_with_no_cap_the_machine_takes_both_turns_at_once(self):
        first, second, _ = self.run_pair(cap=None)
        self.assertEqual(first, ["docker", "docker"])
        self.assertEqual(second, ["docker", "docker"])

    def test_a_running_suite_piece_is_not_counted_toward_the_turn_cap(self):
        home, machine, first, _ = self.setup_home(cap=1)
        fakeadapter.install(home, claude=DONE, codex=REVIEW)
        (machine / "docker/containers/ak-suite-1-4").write_text(f"{1024 * 1048576}\n")
        task = taskfile.write(home, first.path, title="Beside suite", done_when=("test -f left.txt",))
        done = home.ak("run", str(task), "--no-merge", env={"AK_HOST_READINGS": akmachine.CROWDED},
                       timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        places = [path.read_text().strip() for path in sorted(taskfile.only_run(home).rglob("where"))]
        self.assertEqual(places, ["docker", "docker"])

    def test_bad_max_runs_values_are_refused(self):
        home = Home()
        self.addCleanup(home.close)
        for bad in ("0", "-1", "1.5", '"1"', "true", "false"):
            with self.subTest(max_runs=bad):
                akconfig.write(home, ["opus"],
                               extra=f"[machines.acme-linux]\nmax_runs = {bad}\n")
                done = home.ak("models", "--json")
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertIn("[machines.acme-linux].max_runs", done.err)


if __name__ == "__main__":
    unittest.main()
