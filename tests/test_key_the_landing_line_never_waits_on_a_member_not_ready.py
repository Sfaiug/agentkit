"""Unready members keep their place without holding checks or eligible fixers behind them.

Black-box through AK_BIN and Line's fake suites; process ownership and resume launches
are faked in the child, so no worker or live process is touched.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK
from fixtures.akline import READINGS, Line

HOST = """
import json, sys
from pathlib import Path
if sys.argv[:1] == [{ak!r}]:
    sys.path.insert(0, {repo!r})
    from agentkit import host, orch
    active = json.loads(Path({active!r}).read_text())
    host.alive = lambda pid: pid in active
    host.process_identity = lambda pid: ({{"boot": "fixture", "ticks": 1}}
                                         if pid in active else None)
    def start(argv, *_args, **_kw):
        name = argv[-1]
        with Path({wakes!r}).open("a") as out:
            out.write(name + "\\n")
        if name in json.loads(Path({rejoiners!r}).read_text()):
            path = Path({runs!r}) / name / "run.json"
            state = json.loads(path.read_text())
            state["waiting_on"] = {{key: state["waiting_on"][key]
                                   for key in ("line", "joined")}}
            path.write_text(json.dumps(state))
        return 999
    orch.start_in_slice = start
"""


class LandingLineNeverWaits(unittest.TestCase):
    def setUp(self):
        self.line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(self.line.close)
        self.home = self.line.home
        self.active = self.home.write("fakes/active.json", [4242])
        self.rejoiners = self.home.write("fakes/rejoiners.json", [])
        self.wakes = self.home.write("fakes/wakes", "")
        self.home.write("fakes/sitecustomize.py", HOST.format(
            ak=AK, repo=str(Path(AK).resolve().parents[1]), active=str(self.active),
            rejoiners=str(self.rejoiners), wakes=str(self.wakes),
            runs=str(self.home.path / ".agentkit" / "runs")))

    def member(self):
        n = len(self.line.members) + 1
        self.line.member({f"member-{n}.txt": f"{n}\n"})
        return n

    def write(self, n, **changes):
        path = self.line.members[n - 1] / "run.json"
        state = json.loads(path.read_text())
        state.update(changes)
        path.write_text(json.dumps(state))

    def blame(self, n, after):
        wait = {**self.line.verdict(n), "fix": {"line": "fake red", "log": "suite.log"},
                "after": after}
        self.write(n, waiting_on=wait)
        return wait

    def land(self):
        done = self.home.ak("run", "--lander", self.line.line, env={
            "AK_HOST_READINGS": READINGS, "PYTHONPATH": str(self.active.parent)})
        self.assertEqual(done.code, 0, done.out + done.err)
        return self.wakes.read_text().splitlines()

    def test_an_active_head_is_skipped_and_keeps_its_place_when_ready(self):
        for _ in range(3):
            self.member()
        self.write(1, pid=4242, process_identity={"boot": "fixture", "ticks": 1})
        before = (self.line.members[0] / "run.json").read_bytes()
        self.assertEqual(self.land(), ["fix-2", "fix-3"])
        self.assertEqual((self.line.members[0] / "run.json").read_bytes(), before)
        for n in (2, 3):
            tree = self.line.verdict(n)["land"]
            files = self.line.rig.git("ls-tree", "--name-only", tree).splitlines()
            self.assertNotIn("member-1.txt", files)
            self.write(n, state="pass", merged=True)
        self.member()
        self.active.write_text("[]")
        self.assertEqual(self.land(), ["fix-2", "fix-3", "fix-1", "fix-4"])
        self.assertEqual(self.line.verdict(1)["joined"], 1)
        self.assertEqual(self.line.verdict(4)["after"], {"fix-1": self.line.verdict(1)["land"]})

    def test_every_unblocked_red_wakes_even_behind_a_member_that_always_rejoins(self):
        for _ in range(3):
            self.member()
        waits = {n: self.blame(n, {"departed": "tree"}) for n in (2, 3)}
        self.rejoiners.write_text('["fix-1"]')
        for _ in range(2):
            self.wakes.write_text("")
            self.assertEqual(self.land(), ["fix-2", "fix-3", "fix-1"])
            self.assertNotIn("land", self.line.verdict(1))
            for n, wait in waits.items():
                self.assertEqual(self.line.verdict(n), wait)

    def test_a_red_still_waiting_on_a_member_does_not_hold_the_tail(self):
        for _ in range(3):
            self.member()
        self.write(1, pid=4242, process_identity={"boot": "fixture", "ticks": 1})
        wait = self.blame(2, {"fix-1": "tree"})
        self.assertEqual(self.land(), ["fix-3"])
        self.assertEqual(self.line.verdict(2), wait)
        self.assertIn("land", self.line.verdict(3))

    def test_other_checkouts_on_unready_members_do_not_split_ready_stacks(self):
        for _ in range(3):
            self.member()
        other = str(self.home.path / "other-ak")
        self.write(2, ak_checkout=other, pid=4242,
                   process_identity={"boot": "fixture", "ticks": 1})
        wait = self.blame(3, {"fix-1": "tree"})
        self.write(3, ak_checkout=other)
        self.rejoiners.write_text('["fix-1"]')
        for _ in range(2):
            tail = self.member()
            self.wakes.write_text("")
            self.assertEqual(self.land(), ["fix-1", f"fix-{tail}"])
            files = self.line.rig.git("ls-tree", "--name-only",
                                      self.line.verdict(tail)["land"]).splitlines()
            self.assertIn("member-1.txt", files)
            self.assertIn(f"member-{tail}.txt", files)
            for n in (2, 3):
                self.assertNotIn(f"member-{n}.txt", files)
            self.assertEqual(self.line.verdict(3), wait)
            self.assertNotIn("land", self.line.verdict(1))
            self.write(tail, state="pass", merged=True)


if __name__ == "__main__":
    unittest.main()
