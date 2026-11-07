"""agentkit's own `health:` reads a merge live only once this host has installed it, no install
is pending and the installed ak works: `ak doctor` exits 1 when no tick has ended within
`TICK_HUNG` and fails outright on an install that cannot run.  A tick runs that line, the one
this checkout's AGENTS.md declares, as it runs any project's.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, its tick in the box `home.tick()`
builds, on a project from gitrig.py, the GitHub of fakegh.py and a seat from akseat.py, with
~/agentkit a clone of the project whose bin/ak is a stand-in.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

FRONT = (Path(__file__).resolve().parents[1] / "AGENTS.md").read_text().split("\n---\n")[0]
HEALTH = next(line.removeprefix("health:").strip() for line in FRONT.splitlines()
              if line.startswith("health:"))
RUN = "20261020-1200-fix-api"
# ~/agentkit's program: it writes down AK_MERGE_SHA and its words, and exits {code} for doctor
STAND_IN = ('#!/bin/sh\nprintf "%s\\t%s\\n" "$AK_MERGE_SHA" "$*" >>"$HOME/ak-calls"\n'
            '[ "$1" = doctor ] || exit 2\nexit {code}\n')


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class HealthNeedsAWorkingAk(unittest.TestCase):
    """A Home with project app merged by run RUN ten minutes ago from seat acme, its checks
    green, its probe agentkit's own, and ~/agentkit a clone of it at the merge, without a
    remote."""

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        # what the audit seat opens for is its own key
        config = self.home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        rig = Rig(self.home, "app", files={"AGENTS.md": f"---\nhealth: {HEALTH}\n---\n"})
        self.merged = rig.commit({"api.py": "x = 2\n"}, "fix api")
        GitHub(self.home).check(self.merged, "ci")
        Seat(self.home, "acme", cwd=rig.path)
        self.installed = self.home.path / "agentkit"
        self.git("clone", "-q", str(rig.path), str(self.installed))
        self.git("-C", str(self.installed), "remote", "remove", "origin")
        now = time.time()
        self.home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "state": "pass", "verdict": "PASS", "merged": True,
            "finished_at": now - 600, "started_at": now - 1200, "repo": str(rig.path),
            "pr": "https://github.com/acme/app/pull/7", "merge_sha": self.merged,
            "health": {"command": HEALTH}, "launched_session": "acme"})

    def git(self, *args):
        done = self.home.run("git", *args)
        self.assertEqual(done.code, 0, done.err)

    def tick(self, doctor):
        """One tick, ~/agentkit's bin/ak exiting `doctor` when asked doctor: the run's record
        after it, and the words of each call to that program carrying the merge in
        AK_MERGE_SHA, the probe's; the tick may run it for ends of its own."""
        self.home.write("agentkit/bin/ak", STAND_IN.format(code=doctor)).chmod(0o755)
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        record = json.loads((self.home.path / f".agentkit/runs/{RUN}/run.json").read_text())
        calls = self.home.path / "ak-calls"
        lines = calls.read_text().splitlines() if calls.exists() else []
        return record, [words for sha, _, words in (line.partition("\t") for line in lines)
                        if sha == self.merged]

    def test_an_ak_that_exits_1_fails_the_probe(self):
        record, asked = self.tick(1)
        self.assertNotIn("live_at", record, "a merge whose installed ak is hung reads live")
        self.assertEqual(record.get("health", {}).get("command"), HEALTH,
                         "a failed probe is not kept for a later tick")
        self.assertEqual(asked, ["doctor"], "the probe never asked the installed ak")

    def test_an_ak_that_exits_0_passes_the_probe(self):
        record, asked = self.tick(0)
        self.assertIsInstance(record.get("live_at"), (int, float), record)
        self.assertEqual(asked, ["doctor"], "the probe never asked the installed ak")

    def test_a_merge_not_installed_fails_first(self):
        self.git("-C", str(self.installed), "reset", "-q", "--hard", "HEAD~1")
        record, asked = self.tick(0)
        self.assertNotIn("live_at", record, "a merge this host has not installed reads live")
        self.assertEqual(asked, [], "ak was asked before the merge was found installed")

    def test_an_install_pending_fails_first(self):
        self.home.write(".agentkit/state/agentkit-install-pending", "")
        record, asked = self.tick(0)
        self.assertNotIn("live_at", record, "a merge whose install.sh has not passed reads live")
        self.assertEqual(asked, [], "ak was asked before the install passed")


if __name__ == "__main__":
    unittest.main()
