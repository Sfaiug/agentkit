"""A restart of the host is no death of a run.

A restart of the host ends every run's loop, and a loop that is gone and was started under
another boot than the host's now is one a restart ended.  The tick resumes it at once, however
many restarts came before and however close together, and its ending counts towards neither the
third death within an hour that parks a run nor the ten minutes after a resume, so the run's
seat is told nothing; `ak run status` names the ending as the host's restart.  A loop that dies
while the host stays up counts as it always did.  Each case holds whether the tick notices the
ending first or `ak run status` does.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, on run records whose loop is a process the test started and
reaped, so it is certainly gone; between ticks the test plays the resume the tick ordered taking
the record over, under a boot the next restart ends.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

FIRSTS = ("tick", "status")     # who notices the loop's ending first
BOOT = Path("/proc/sys/kernel/random/boot_id").read_text().strip()    # the host's boot now
# The boot each case's loop is started under, one tick after another: a boot other than the
# host's now is one a restart has ended since.
BOOTS = {"restarts": ["acme-boot-1", "acme-boot-2", "acme-boot-3"],
         "restarts-then-death": ["acme-boot-1", "acme-boot-2", BOOT],
         "deaths": [BOOT],
         "parked": ["acme-boot-1"]}
SEATED = ("restarts", "parked")     # cases whose run a seat launched


def record(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def gone_pid():
    """A process that ran and was reaped: its pid names no process now."""
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AHostRestartNeverParksARun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        now = time.time()
        cls.runs, cls.seats = {}, {}
        for first in FIRSTS:
            # Three restarts of the host within minutes, each ending the loop the last one's
            # resume started; after two of them, a loop that dies by itself.
            cls.write("restarts", first)
            cls.write("restarts-then-death", first)
            # Two deaths of its own within the hour, and a third while the host stays up.
            cls.write("deaths", first, [{"at": now - 1200, "resumed_at": now - 1200},
                                        {"at": now - 900, "resumed_at": now - 900}])
            # The tick parked the run at its third death within the hour, its seat resumed it,
            # and the host restarted.
            cls.write("parked", first, [{"at": now - 1500, "resumed_at": now - 1500},
                                        {"at": now - 1200, "resumed_at": now - 1200},
                                        {"at": now - 900, "parked": True}])
        cls.done = []
        for step in range(max(map(len, BOOTS.values()))):
            stepped = [name for name, run in cls.runs.items() if step < len(run["boots"])]
            for name in stepped:
                cls.loop(cls.runs[name], cls.runs[name]["boots"][step])
            cls.done += [home.ak("run", "status", cls.runs[name]["dir"].name)
                         for name in stepped if name.endswith("-status")]
            cls.done.append(home.tick())
            for name in stepped:
                cls.runs[name]["after"].append(record(cls.runs[name]["dir"]))
        cls.shown = {first: home.ak("run", "status", cls.runs[f"restarts-{first}"]["dir"].name)
                     for first in FIRSTS}

    @classmethod
    def write(cls, case, first, deaths=()):
        name = f"{case}-{first}"
        run_id = f"20261110-2017-{name}"
        worktree = cls.home.path / ".agentkit/wt" / run_id
        worktree.mkdir(parents=True)
        deaths = [{"pid": gone_pid(), "reason": "loop process gone", **death} for death in deaths]
        seat = {}
        if case in SEATED:
            cls.seats[name] = Seat(cls.home, f"acme-{name}")
            seat = {"launched_session": f"acme-{name}"}
        cls.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "title": name, "state": "running", "started_at": time.time() - 6000,
            "step": "executor", "rounds": 3, "worktree": str(worktree), "deaths": deaths, **seat})
        cls.runs[name] = {"dir": cls.home.path / ".agentkit/runs" / run_id, "deaths": deaths,
                          "boots": BOOTS[case], "pids": [], "after": []}

    @classmethod
    def loop(cls, run, boot):
        """A loop of the run, started under `boot` and gone: as the resume the tick ordered, or
        the run's seat, left the record once it took the record over."""
        state = record(run["dir"])
        for key in ("stall_resume_at", "resume_after"):
            state.pop(key, None)
        pid = gone_pid()
        state.update(state="running", pid=pid,
                     process_identity={"boot": boot, "ticks": 0, "started_at": time.time()})
        (run["dir"] / "run.json").write_text(json.dumps(state, indent=1))
        run["pids"].append(pid)

    def told(self, name):
        """The tick's lines about the run: resumed, waiting, parked."""
        run_id = self.runs[name]["dir"].name
        try:
            lines = (self.runs[name]["dir"] / "log.txt").read_text().splitlines()
        except FileNotFoundError:
            return []
        return [line.split("] ", 1)[1] for line in lines
                if any(f"{verb} {run_id}: " in line
                       for verb in ("resumed", "waiting to resume", "parked"))]

    def assert_resumed(self, name, step, *, restart):
        run = self.runs[name]
        state = run["after"][step]
        self.assertEqual(state["state"], "running")
        self.assertNotIn("resume_after", state, "no ten-minute wait")
        ending = state["deaths"][-1]
        self.assertEqual(ending["pid"], run["pids"][step])
        self.assertEqual(bool(ending.get("restart")), restart, ending)
        self.assertGreaterEqual(ending["resumed_at"], ending["at"])
        self.assertFalse(ending.get("parked"))

    def test_every_command_exits_zero(self):
        for done in [*self.done, *self.shown.values()]:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_three_restarts_within_minutes_each_resume_the_run_and_never_park_it(self):
        for first in FIRSTS:
            name = f"restarts-{first}"
            for step in range(3):
                with self.subTest(first=first, step=step):
                    self.assertEqual(len(self.runs[name]["after"][step]["deaths"]), step + 1)
                    self.assert_resumed(name, step, restart=True)
            with self.subTest(first=first):
                told = self.told(name)
                self.assertEqual(len(told), 3, told)
                for line in told:
                    self.assertTrue(line.startswith(f"resumed {self.runs[name]['dir'].name}: "
                                                    "the host restarted ("), line)
                self.assertEqual(self.seats[name].lines(), [])

    def test_status_names_each_ending_as_the_hosts_restart(self):
        for first in FIRSTS:
            with self.subTest(first=first):
                lines = self.shown[first].out.splitlines()
                self.assertEqual(len([line for line in lines if line.startswith("  host restart ")]),
                                 3, lines)
                self.assertEqual([line for line in lines if line.startswith("  death ")], [])

    def test_three_deaths_within_an_hour_while_the_host_stays_up_park_the_run(self):
        for first in FIRSTS:
            with self.subTest(first=first):
                run = self.runs[f"deaths-{first}"]
                state = run["after"][0]
                self.assertEqual(state["state"], "interrupted")
                self.assertEqual(state["deaths"][:2], run["deaths"])
                self.assertEqual(len(state["deaths"]), 3, state["deaths"])
                third = state["deaths"][2]
                self.assertEqual((third["pid"], third.get("parked")), (run["pids"][0], True))
                self.assertFalse(third.get("restart"))
                told = self.told(f"deaths-{first}")
                self.assertEqual(len(told), 1, told)
                self.assertTrue(told[0].startswith(f"parked {run['dir'].name}: loop died ("), told)
                self.assertTrue(told[0].endswith("; third death within an hour"), told)

    def test_after_two_restarts_a_death_of_its_own_is_resumed_at_once(self):
        for first in FIRSTS:
            with self.subTest(first=first):
                name = f"restarts-then-death-{first}"
                deaths = self.runs[name]["after"][2]["deaths"]
                self.assertEqual([bool(death.get("restart")) for death in deaths],
                                 [True, True, False])
                self.assert_resumed(name, 2, restart=False)
                told = self.told(name)
                self.assertEqual(len(told), 3, told)
                self.assertTrue(told[2].startswith(f"resumed {self.runs[name]['dir'].name}: "
                                                   "loop died ("), told)

    def test_a_parked_run_its_seat_resumed_is_resumed_after_a_restart(self):
        for first in FIRSTS:
            with self.subTest(first=first):
                name = f"parked-{first}"
                state = self.runs[name]["after"][0]
                self.assertEqual(state["deaths"][:3], self.runs[name]["deaths"])
                self.assertEqual(len(state["deaths"]), 4, state["deaths"])
                self.assert_resumed(name, 0, restart=True)
                self.assertEqual(self.seats[name].lines(), [])


if __name__ == "__main__":
    unittest.main()
