"""Doctor reports each gate's last hold from history, even after its run was collected."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import AK, REPO, Home

NOW = 1_800_000_000
DAY = 86400
CLOCK = """
import fcntl, os, sys, time
from pathlib import Path
if sys.argv[:1] == [{ak!r}]:
    sys.path[:0] = [{repo!r}, {tests!r}]
    from fixtures.clock import Clock
    from agentkit import config, history, record, watch
    for module in (history, watch):
        module.time = Clock(time.sleep)
        module.time.time = lambda: {now}
    record.process_active = lambda state: state.get("pid") == os.getpid()
    seed = Path({seed!r})
    if seed.exists():
        exec(seed.read_text())
        seed.unlink()
"""


class DoctorGatesLine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        self.home.write(".agentkit/state/watch.json", {"tick": {
            "started_at": NOW - 20, "ended_at": NOW - 10,
            "slowest": {"pass": "dead loops", "seconds": 1}}})
        clock = self.home.write("fakes/sitecustomize.py", CLOCK.format(
            ak=AK, repo=str(Path(AK).resolve().parents[1]), tests=str(REPO / "tests"),
            now=NOW, seed=str(self.home.path / "fakes/seed.py")))
        self.env = {"PYTHONPATH": str(clock.parent)}

    def doctor(self, seed=""):
        if seed:
            self.home.write("fakes/seed.py", seed)
        done = self.home.ak("doctor", env=self.env)
        self.assertEqual(done.code, 0, done.out + done.err)
        lines = [line for line in done.out.splitlines() if line.startswith("gates  ")]
        self.assertEqual(len(lines), 1, done.out)
        return lines[0]

    def test_memory_last_held_three_days_ago_and_suite_turns_hold_now(self):
        self.home.write(".agentkit/runs/fix-api/run.json", {
            "state": "pass", "slot_wait_kind": "memory", "reported": True})
        line = self.doctor(f"""
history.start_run("fix-api", repo="acme", started_at={NOW - 4 * DAY})
history.add_wait("fix-api", "slot", 30, at={NOW - 3 * DAY})
history.finish_run("fix-api", final_state="pass", finished_at={NOW - 3 * DAY})
(config.RUNS / "fix-api/run.json").unlink()
history.start_run("fix-ui", repo="acme", started_at={NOW - 60})
history.add_wait("fix-ui", "suite", 15, at={NOW - 5})
directory = config.RUNS / "fix-ui"
directory.mkdir()
record.save_state(directory, {{"run_id": "fix-ui", "state": "running", "pid": os.getpid(),
    "gate_turn": {{"pid": os.getpid(), "since": {NOW - 20}, "of": "acme"}}}})
""")
        self.assertIn("memory 3 days idle", line)
        self.assertIn("last held 2027-01-12 08:00", line)
        self.assertIn("suite turns holding now", line)
        self.assertIn("admission never held", line)

    def test_before_any_history_all_three_gates_never_held(self):
        self.assertEqual(self.doctor(), "gates  admission never held · suite turns never held · memory never held")
        self.assertFalse((self.home.path / ".agentkit/history.db").exists())

    def test_a_lander_wait_counts_as_suite_turns(self):
        line = self.doctor(f"""
history.start_run("fix-api", repo="acme", started_at={NOW - 2 * DAY})
history.add_wait("fix-api", "lander", 15, at={NOW - DAY})
history.finish_run("fix-api", final_state="pass", finished_at={NOW - DAY})
""")
        self.assertIn("suite turns 1 day idle", line)
        self.assertIn("admission never held", line)
        self.assertIn("memory never held", line)

    def test_a_finished_wait_at_the_clock_is_idle(self):
        line = self.doctor(f"""
history.start_run("fix-api", repo="acme", started_at={NOW - 60})
history.add_wait("fix-api", "suite", 15, at={NOW})
history.finish_run("fix-api", final_state="pass", finished_at={NOW})
""")
        self.assertIn("suite turns 0 days idle", line)

    def test_current_slot_waits_name_the_gate_holding_them(self):
        for kind, gate in (("count", "admission"), ("load", "admission"),
                           ("memory", "memory"), ("unit memory", "memory")):
            with self.subTest(kind=kind):
                line = self.doctor(f"""
directory = config.RUNS / "fix-api"
directory.mkdir(parents=True, exist_ok=True)
record.save_state(directory, {{"run_id": "fix-api", "state": "queued", "pid": os.getpid(),
    "slot_waiting": True, "slot_wait_kind": {kind!r}}})
""")
                self.assertIn(f"{gate} holding now", line)

    def test_a_line_checkers_locked_wait_is_live_until_it_leaves(self):
        line = self.doctor("""
config.RUNS.mkdir(parents=True, exist_ok=True)
held = (config.RUNS / ".landing-wait-fixture").open("w")
fcntl.flock(held, fcntl.LOCK_EX)
held.write("{}")
held.flush()
""")
        self.assertIn("suite turns holding now", line)
        self.assertIn("suite turns never held", self.doctor())
        self.assertTrue((self.home.path / ".agentkit/runs/.landing-wait-fixture").exists())


if __name__ == "__main__":
    unittest.main()
