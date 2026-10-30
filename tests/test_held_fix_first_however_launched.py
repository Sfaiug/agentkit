"""The seat told of a red that holds the install has one first place however its fix launches.

While the install lacks the held commit, the seat's earliest agentkit run launched since it was
told that has not ended goes first: admitted as `--first` is (`gate.slot_order`) and ahead in
the landing line of every member that joined without one (`land.line`).  A launch refused as
another run on its PR has not ended takes nothing; once the place's run is stopped, parked or
fails, the seat's next run has it, and a run started again after a park keeps it.  An
unreadable record or session gives no place, and once the install moves there is none.
Black-box: the seat `acme` launches through `bin/ak run` in a Home of tests/fixtures/akbin.py,
on the agentkit of gitrig.py and the GitHub of fakegh.py, with no slot free so each run waits
queued; ak's own code, run in that Home, hands the red back and reads the order.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

sys.path.insert(0, str(REPO))
from agentkit import record as run_record  # noqa: E402

OFFLINE = {"https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
           "GIT_ALLOW_PROTOCOL": "file"}
SEAT = {"AGENTKIT_SESSION": "acme"}
# ak's own code, run in the Home: `order` names the runs admitted first and the landing line
PRELUDE = f"""import json, sys, time
sys.path.insert(0, {str(REPO)!r})
from pathlib import Path
from agentkit import config, gate, land, leases, record, update
def order():
    print(json.dumps({{"first": sorted(d.name for d in record.run_dirs()
                                        if not gate.slot_order(record.read_state(d) or {{}})[0]),
                      "line": [d.name for d, _ in land.line(Path("line"))]}}))
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class HeldFixFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env.update(OFFLINE, AK_MAX_RUNS="3")
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        cls.rig = Rig(home, "agentkit")
        cls.gh = GitHub(home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="pass", codex="pass")
        cls.seat = Seat(home, "acme", cwd=cls.rig.path, record={"workers": ["opus", "astra"]},
                        planned=True)
        # the install: on main, with the held commit fetched but not in it
        cls.held = cls.rig.branch("held", {"api.py": "broken\n"})
        cls.install = home.path / "agentkit"
        for args in (("clone", "-q", str(cls.rig.bare), str(cls.install)),
                     ("-C", str(cls.install), "fetch", "-q", "origin", "held"),
                     ("-C", str(cls.install), "remote", "set-url", "origin",
                      "https://github.com/acme/agentkit.git")):
            assert home.run("git", *args).code == 0
        # the seat's own runs, held by this test, take every slot, so each run it launches waits
        # queued, and it may queue three (`gate.seat_full`)
        for slot in ("20261026-0800-slot", "20261026-0800-slot-2", "20261026-0800-slot-3"):
            home.write(f".agentkit/runs/{slot}/run.json",
                       {"run_id": slot, "state": "running", "started_at": 1,
                        "launched_session": "acme", **run_record.process_owner()})
        # the seat's merged run is what makes it the one a red of agentkit's main is told to
        home.write(".agentkit/runs/20261026-0801-merged/run.json",
                   {"run_id": "20261026-0801-merged", "state": "pass", "merged": True,
                    "launched_session": "acme", "started_at": 1,
                    "pr": "https://github.com/acme/agentkit/pull/99"})
        cls.rig.branch("contrib", {"x.py": "x\n"})
        cls.pr = cls.gh.open_pr(cls.rig, "contrib", author="someone")

        cls.before = cls.review()       # before the hand-back: never the place
        cls.check = home.path / f".agentkit/state/live-checks/{cls.held}-1000"
        cls.check.mkdir(parents=True)
        (cls.check / "output").write_text("FAIL  4 acme meter: missing reading\n[exit 1]\n")
        cls.ak_code(f"update.live_hand_back({cls.held!r}, Path({str(cls.check)!r}), 1, print)")
        cls.told = cls.seat.wait_lines(1)

    @classmethod
    def ak_code(cls, code):
        done = cls.home.run(sys.executable, "-c", PRELUDE + code)
        assert done.code == 0, done.out + done.err
        return done.out

    @classmethod
    def order(cls):
        return json.loads(cls.ak_code("order()").splitlines()[-1])

    @classmethod
    def launch(cls, *args):
        known = set(taskfile.runs(cls.home))
        done = cls.home.ak("run", *args, "--bg", env=SEAT)
        new = [run for run in taskfile.runs(cls.home) if run not in known]
        assert len(new) == 1, (done, new)
        return new[0].name, done.code

    @classmethod
    def review(cls):
        return cls.launch("--review-pr", cls.pr)[0]

    @classmethod
    def task(cls, title):
        name, code = cls.launch(str(taskfile.write(cls.home, cls.rig.path, title,
                                                   done_when=("true",))))
        assert code == 0, name
        return name

    def record(self, name):
        return json.loads((self.home.path / ".agentkit/runs" / name / "run.json").read_text())

    def test_the_hand_back_tells_the_seat_its_next_agentkit_run_goes_first(self):
        self.assertTrue(" ".join(self.told).endswith(
            "Fix main: your next agentkit run goes first in line until the install moves, "
            "so make it the fix."), self.told)
        handed = json.loads((self.check / "handed").read_text())
        self.assertEqual(handed["seat"], "acme")
        self.assertGreater(handed["at"], self.record(self.before)["started_at"])

    def test_the_place_follows_the_seats_runs_however_they_launch_end_and_restart(self):
        refused, code = self.launch("--review-pr", self.pr)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.record(refused)["state"], "error")
        self.assertEqual(self.order()["first"], [])

        fix = self.task("Fix main")
        later = self.task("Something else")
        self.assertEqual(self.order()["first"], [fix])

        self.assertEqual(self.home.ak("run", "stop", fix, "--keep").code, 0)
        self.assertEqual(self.order()["first"], [later])
        self.assertEqual(self.home.ak("run", "stop", later).code, 0)
        again = self.task("Fix main again")
        last = self.task("One more")
        self.assertEqual(self.order()["first"], [again])

        # parked on a collision, then started again once its holder is over
        self.ak_code(f"leases.park({{'run': {again!r}}}, {self.before!r}, ['api.py'], time.time())")
        self.assertEqual(self.order()["first"], [last])
        self.assertEqual(self.home.ak("run", "stop", self.before).code, 0)
        self.ak_code("leases.restart()")
        restarted = self.record(again)["lease_restarted"]
        self.assertEqual(self.order()["first"], [restarted])

        # in the landing line: behind a green delivery, admitted first too, and ahead of the
        # member that joined first
        delivery = "20261026-0802-delivery"
        self.home.write(f".agentkit/runs/{delivery}/run.json",
                        {"run_id": delivery, "state": "waiting", "started_at": 1,
                         "waiting_on": {"line": "line", "joined": 30, "land": "tree"}})
        for name, joined in ((last, 10), (restarted, 20)):
            self.join(name, joined)
        self.assertEqual(self.order()["line"], [delivery, restarted, last])

        handed = (self.check / "handed").read_text()
        for unreadable in ("{", "[]"):
            (self.check / "handed").write_text(unreadable)
            self.assertEqual(self.order(), {"first": [delivery],
                                            "line": [delivery, last, restarted]})
        (self.check / "handed").write_text(handed)
        session = self.home.path / ".agentkit/state/session-acme.json"
        kept = session.read_text()
        self.home.write(".agentkit/state/session-acme.json", {"renamed": "acme-2"})
        self.home.write(".agentkit/state/session-acme-2.json", {"renamed": "acme"})
        self.assertEqual(self.order()["first"], [delivery])
        session.write_text(kept)
        self.assertEqual(self.order()["first"], [delivery, restarted])
        # another seat's hand-back, its session unreadable, takes nothing from this one's
        other = self.check.with_name(f"{self.held}-2000")
        other.mkdir()
        (other / "handed").write_text(json.dumps({"seat": "ghost", "at": 1}))
        self.home.write(".agentkit/state/session-ghost.json", "{")
        self.assertEqual(self.order()["first"], [delivery, restarted])

        self.assertEqual(self.home.run("git", "-C", str(self.install), "merge", "-q",
                                       "--ff-only", self.held).code, 0)
        self.assertEqual(self.order(), {"first": [delivery], "line": [delivery, last, restarted]})

    def join(self, name, joined):
        """That run as its loop leaves it in the landing line: waiting, with no process."""
        state = self.record(name)
        try:
            os.kill(state["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass
        while run_record.process_active(state):
            time.sleep(0.05)
        state.update(state="waiting", waiting_on={"line": "line", "joined": joined})
        self.home.write(f".agentkit/runs/{name}/run.json", state)


if __name__ == "__main__":
    unittest.main()
