"""Each seat runs at its own efforts, and changing the defaults leaves live seats alone.

A seat's record holds its models' effort keys under `efforts`, and its runs run at them, their
receipts saying so; a step on a seat's `c` writes that record, one on a fresh window's `c`
config.toml.  A record from before runs at its models' entries until one of them changes.
Black-box: `AK_BIN` on a gitrig.py project, akseat.py seats, an akterm.py terminal and
fakeadapter.py harnesses, judged by the effort each turn is handed, the records and config.toml.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from fixtures.gitrig import Rig


def run_in(test, seat, title):
    """`ak run` of a new task in `seat`: its receipt, and the effort each Claude turn got."""
    home, fake = test.home, test.fakes["claude"]
    before, turns = set(taskfile.runs(home)), len(fake.runs())
    done = home.ak("run", str(taskfile.write(home, test.rig.path, title)), "--no-merge",
                   env={"AGENTKIT_SESSION": seat}, timeout=300)
    test.assertEqual(done.code, 0, done.out + done.err)
    [run_dir] = set(taskfile.runs(home)) - before
    return (json.loads((run_dir / "run.json").read_text()),
            {run["argv"][1] for run in fake.runs()[turns:]})


class TwoSeatsOnOneModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        for effort in ("high", "max"):
            Seat(cls.home, f"acme-{effort}", cwd=cls.rig.path, alive=False, planned=True,
                 record={"reviewers": ["astra"], "efforts": {"opus": {"effort": effort}}})

    def test_each_seat_s_run_builds_at_that_seat_s_effort(self):
        for effort in ("high", "max"):
            with self.subTest(effort=effort):
                receipt, handed = run_in(self, f"acme-{effort}", f"Build at {effort}")
                self.assertEqual(handed, {effort})
                self.assertEqual(receipt["efforts"]["opus"], {"effort": effort})


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class StepsOnC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        cls.seat = Seat(cls.home, "atoll-own", model="fable",
                        record={"reviewers": ["astra"], "efforts": {"fable": {"effort": "high"}}})

    def setUp(self):
        self.config = akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        self.record = self.home.path / ".agentkit/state/session-atoll-own.json"
        self.home.write(".agentkit/state/session-atoll-own.json", self.seat.record)

    def efforts(self):
        # the menu writes other fields of a live seat's record as it reads it
        return json.loads(self.record.read_text())["efforts"]

    def step_fable(self, env=None):
        """Enter on Fable's effort on `c` in the menu `env` opens: config, efforts before."""
        term = Terminal(self.home, *(("attach", "--overlay") if env else ()), size=(100, 30),
                        env={"NO_COLOR": "1", **(env or {})})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("c config")
        term.keys("c")
        term.wait("› Fable 5.1")
        files = (self.config.read_bytes(), self.efforts())
        term.keys("Right", "Right", "Right", "Enter")      # onto the effort, and a step
        deadline = time.monotonic() + 30
        while files == (self.config.read_bytes(), self.efforts()):
            self.assertLess(time.monotonic(), deadline, "the step was never saved")
            time.sleep(0.05)
        return files

    def test_a_step_on_a_seat_s_c_writes_its_record_and_not_config_toml(self):
        config, _ = self.step_fable({"AGENTKIT_SESSION": "atoll-own"})
        self.assertEqual(self.efforts(), {"fable": {"effort": "xhigh"}})
        self.assertEqual(self.config.read_bytes(), config)

    def test_a_step_on_new_seats_c_writes_config_toml_and_no_record(self):
        _, efforts = self.step_fable()
        self.assertEqual(akconfig.read(self.home)["models"]["fable"]["effort"], "max")
        self.assertEqual(self.efforts(), efforts)

    def test_a_seat_from_before_keeps_its_entry_s_effort_once_the_entry_changes(self):
        Seat(self.home, "atoll-old", model="fable", cwd=self.rig.path, alive=False,
             planned=True, record={"reviewers": ["astra"]})
        self.assertEqual(run_in(self, "atoll-old", "Build before")[1], {"xhigh"})
        self.step_fable()
        self.assertEqual(akconfig.read(self.home)["models"]["fable"]["effort"], "max")
        self.assertEqual(run_in(self, "atoll-old", "Build after")[1], {"xhigh"})


if __name__ == "__main__":
    unittest.main()
