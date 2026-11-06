"""A merge follows its health to live without any tick, and tells its waiting seat once.

Black-box: AK_BIN runs against Home, Rig, GitHub, Seat and Sink. Health counts its probes
and stays red until the test deploys, after two failures. An already live run starts none.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.sink import Sink

HEALTH = ('printf "%s\\n" "$AK_MERGE_SHA" >>"$HOME/probes"; '
          'test -e "$HOME/live-ok" || { echo deploying; exit 1; }')
DEPLOYED = ('printf "%s\\n" "$AK_MERGE_SHA" >>"$HOME/deploy-probes"; '
            'test -e "$HOME/live-ok"')


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LiveWithoutATick(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        self.rig = Rig(self.home, "app", files={
            "AGENTS.md": f"---\ntests: none\nhealth: {HEALTH}\ndeployed: {DEPLOYED}\nusers: none\n---\n"})
        GitHub(self.home).grant(self.rig.slug, "WRITE")
        akconfig.write(self.home, ["opus", "astra"])
        fakeadapter.install(self.home, claude="work", codex="pass")
        self.seat = Seat(self.home, "acme", cwd=self.rig.path, planned=True)
        self.task = taskfile.write(self.home, self.rig.path)

    def launch(self, *flags):
        done = self.home.ak("run", str(self.task), *flags,
                            env={"AGENTKIT_SESSION": "acme"}, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.directory = taskfile.only_run(self.home)
        return self.record()

    def record(self):
        return json.loads((self.directory / "run.json").read_text())

    def probes(self, name="probes"):
        path = self.home.path / name
        return path.read_text().splitlines() if path.exists() else []

    def until(self, ready, bound=90):
        deadline = time.monotonic() + bound
        while not ready():
            self.assertLess(time.monotonic(), deadline,
                            f"never became ready; record: {self.record()}; probes: {self.probes()}")
            time.sleep(0.05)

    def test_a_merge_retries_until_live_and_tells_its_seat_once_without_a_tick(self):
        state = self.launch()
        self.assertTrue(state["merged"])
        # Its seat has read the merge's ending; only the deployment is left to hear.
        done = self.home.ak("run", "status", self.directory.name,
                            env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.until(lambda: len(self.probes()) >= 2 and
                   self.record().get("health", {}).get("output") == "deploying")
        self.assertNotIn("live_at", self.record())
        self.assertNotIn("deployed_at", self.record())
        self.home.write("live-ok", "")
        self.until(lambda: self.record().get("live_notified"))
        self.assertIsInstance(self.record().get("live_at"), (int, float))
        self.assertIsInstance(self.record().get("deployed_at"), (int, float))
        self.assertEqual(self.record()["health"], {"command": HEALTH})
        self.assertGreaterEqual(len(self.probes()), 3)
        self.assertEqual(set(self.probes()), {self.rig.head()})
        self.assertEqual(self.probes("deploy-probes"), self.probes())
        self.seat.wait_lines(1)
        notice = f"run {self.directory.name} is live"
        self.assertEqual(sum(notice in line for line in self.seat.lines()), 1)
        done = self.home.ak("run", "merge", self.directory.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(sum(notice in line for line in self.seat.lines()), 1)
        self.assertEqual(self.sink.pages(), [])

    def test_a_record_already_live_starts_no_probe_when_it_merges(self):
        state = self.launch("--no-merge")
        state.update(live_at=time.time(), merge_failed=True, no_merge=False)
        state["launch_opts"]["--no-merge"] = False
        self.home.write(f".agentkit/runs/{self.directory.name}/run.json", state)
        done = self.home.ak("run", "merge", self.directory.name, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(self.record()["merged"])
        self.assertEqual(self.record()["live_at"], state["live_at"])
        self.assertEqual(self.probes(), [])
        self.assertEqual(self.probes("deploy-probes"), [])
        self.assertEqual(self.sink.pages(), [])


if __name__ == "__main__":
    unittest.main()
