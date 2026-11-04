"""A job's receipt ends its wait, with its own hand-back as the seat's one notice.

Black-box through AK_BIN: two real tasks, fake adapters and GitHub in acme/widget, and a
seat that may be renamed after the hand-back but before the tick sees the ending.
"""

import json
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable, rerun_boxed
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


def wait_for(read, bound=120):
    deadline = time.monotonic() + bound
    while not (seen := read()):
        if time.monotonic() > deadline:
            raise AssertionError("job did not reach its expected state")
        time.sleep(.1)
    return seen


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class WaitOnAJob(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        self.rig, self.gh = Rig(home, "widget"), GitHub(home)
        self.seat = Seat(home, "acme", cwd=self.rig.path, planned=True,
                         record={"workers": ["opus", "astra"]})
        fakes = fakeadapter.install(home, claude="work", codex="pass")
        release = fakes["claude"].dir / "release"
        self.release = release
        hold = (f"for i in $(seq 1200); do [ -f {shlex.quote(str(release))} ] && break; "
                "sleep .1; done")
        fakes["claude"].behave(*({**fakeadapter.WORK, "write": {f"{name}.txt": name},
                                  "sh": hold} for name in ("alpha", "beta")))
        tasks = [taskfile.write(home, self.rig.path, f"Add {name} file",
                                done_when=(f"test -f {name}.txt",)) for name in ("alpha", "beta")]
        launched = home.ak("run", *map(str, tasks), "--bg", "--parallel", "1",
                           "--exec", "opus", "--review", "astra",
                           env={"AGENTKIT_SESSION": self.seat.name})
        self.assertEqual(launched.code, 0, launched.out + launched.err)
        self.directory, = (home.path / ".agentkit/jobs").iterdir()
        wait_for(lambda: fakes["claude"].n)
        waited = home.ak("wait", self.directory.name, env={"AGENTKIT_SESSION": self.seat.name})
        self.assertEqual((waited.code, waited.out),
                         (0, f"acme: waiting on job {self.directory.name}\n"), waited.err)
        self.assertEqual((self.wait()["kind"], self.wait()["on"]),
                         ("job", self.directory.name))
        self.assertFalse(self.job().get("finished_at"))
        self.assertFalse(self.wait().get("told"))

    def job(self):
        return json.loads((self.directory / "job.json").read_text())

    def wait(self):
        return json.loads((self.home.path / f".agentkit/state/seat-{self.seat.name}.json")
                          .read_text())["wait"]

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def finish(self):
        self.release.touch()
        wait_for(lambda: self.job().get("finished_at"))
        wait_for(lambda: self.job().get("card_sent") or self.job().get("handback_pending"))
        self.assertEqual([task["state"] for task in self.job()["tasks"]], ["merged", "merged"])
        self.assertEqual([pr["state"] for pr in self.gh.prs()], ["MERGED", "MERGED"])

    def assert_handback_once(self):
        wait_for(lambda: (self.job().get("card_sent") or {}).get("kind") == "handback")
        lines = self.seat.wait_lines(1)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith(f"job {self.directory.name}: all 2 tasks finished"))
        self.assertNotIn("your wait is over", lines[0])
        self.tick()
        self.assertTrue(self.wait().get("over"))
        self.assertTrue(self.wait().get("told"))
        self.tick()
        self.assertEqual(self.seat.lines(), lines)

    def test_its_handback_ends_the_wait_once(self):
        self.finish()
        self.assert_handback_once()

    def test_a_rename_after_the_handback_keeps_it_told(self):
        self.finish()
        wait_for(lambda: (self.job().get("card_sent") or {}).get("kind") == "handback")
        self.seat.wait_lines(1)
        done = self.home.ak("orch", "rename", "acme", "acme-renamed")
        self.assertEqual(done.code, 0, done.err)
        self.seat.name = "acme-renamed"
        self.assertEqual(self.job()["seat"], "acme")
        self.assert_handback_once()

    def test_a_deferred_handback_is_the_waits_only_line(self):
        self.seat.show("claude-working-pane.txt")
        self.finish()
        self.tick()
        self.assertTrue(self.wait().get("over"))
        self.assertFalse(self.wait().get("told"))
        self.assertEqual(self.seat.lines(), [])
        self.seat.show("claude-prompt-pane.txt")
        self.tick()
        self.assert_handback_once()

    def test_a_job_stopped_without_a_handback_gets_one_wait_line(self):
        done = self.home.ak("run", "stop", self.directory.name,
                            env={"AGENTKIT_SESSION": self.seat.name})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(self.job().get("finished_at"))
        self.assertFalse(self.job().get("card_sent"))
        self.tick()
        lines = self.seat.wait_lines(1)
        self.assertEqual(lines, [f"job {self.directory.name} finished; your wait is over. "
                                 "Decide the next step."])
        self.assertTrue(self.wait().get("told"))
        self.tick()
        self.assertEqual(self.seat.lines(), lines)


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
