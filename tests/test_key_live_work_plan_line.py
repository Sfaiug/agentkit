"""A seat that worked on the live host with no open plan line is sent back once to write it down.

Work done straight on the live host involves no run, so a seat could finish a whole job there with
no plan line and read `idle` (owner, 26 Oct 2026).  A seat's own `ssh` naming the live host runs
the real ssh and is written down; a turn that did so and ends with no open line in its plan goes
back once, told to `ak plan add` what it changed there, and in that turn `ak plan add` takes a
check that already passes, written done on the commit it passed on.  Black-box: the shims a
seat's launch installs (tests/fixtures/shims.py), hooks/seat-state.sh starting each turn,
hooks/orchestrator-stop.sh ending it, and `ak plan add`, all run as the harness and the seat run
them, in an answer-key Home with `prod` as its live host.
"""

import json
import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures.shims import Shims

PASSES = ("ak plan: this check already passes on acme's default branch, so it proves nothing; "
          "write one that fails until the work is done\n")
DONE = "- [x] the monitor account is enrolled · check: `test -f done.txt` · acme · written "
OPEN = "- [ ] the parser parses · check: `false` · acme · written 2026-10-09 12:00\n"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LiveWork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)
        cls.rig = Rig(cls.home, "acme", files={"done.txt": "done\n"})
        Seat(cls.home, "acme", cwd=cls.rig.path, record={"repo": str(cls.rig.path)}, alive=False)
        cls.shims.fake("ssh", out="ssh ran\n")
        cls.config = cls.home.path / ".agentkit" / "config.toml"
        cls.shipped = cls.config.read_text()
        cls.config.write_text(f'live_host = "prod"\n{cls.shipped}')
        cls.state = cls.home.path / ".agentkit" / "state"
        cls.plan = cls.state / "plan-acme.md"
        cls.said = cls.home.root / "transcript.jsonl"
        cls.said.write_text(json.dumps({"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "Done."}]}}) + "\n")

    def setUp(self):
        self.plan.unlink(missing_ok=True)
        self.prompt()

    def hook(self, script, payload, env=None):
        done = self.home.run("bash", str(REPO / "hooks" / script), input=json.dumps(payload),
                             env={"AGENTKIT_SESSION": "acme", **(env or {})})
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def prompt(self):
        """The owner's prompt starts a turn, as the harness's UserPromptSubmit hook says."""
        self.hook("seat-state.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "go",
                                    "session_id": "conv-acme"})

    def stop(self):
        """The reason the turn's end is sent back with, or "" where it stands."""
        out = self.hook("orchestrator-stop.sh", {"hook_event_name": "Stop", "session_id": "conv-acme",
                                                 "transcript_path": str(self.said)})
        return json.loads(out)["reason"] if out.strip() else ""

    def ssh(self, *argv, seat="acme", env=None):
        """A command's ssh, run as typed by the real (fake) ssh, its output back."""
        done = self.shims.run("ssh", *argv, seat=seat, env=env)
        self.assertEqual((done.code, done.out, done.err), (0, "ssh ran\n", ""))
        self.assertEqual(self.home.calls("ssh")[-1], list(argv))

    def add(self):
        return self.home.ak("plan", "add", "the monitor account is enrolled",
                            "--check", "test -f done.txt",
                            env={"AGENTKIT_SESSION": "acme"}, cwd=self.rig.path)

    def assertHeldOnce(self):
        self.assertIn("ak plan add", self.stop())
        self.assertEqual(self.stop(), "")       # the second stop that turn stands
        self.assertFalse((self.state / "notify-acme.json").exists())
        record = self.state / "seat-acme.json"
        self.assertNotIn("unasked", json.loads(record.read_text()) if record.exists() else {})

    def test_a_turn_that_reached_the_live_host_with_no_plan_goes_back_once(self):
        for host in ("prod", "deploy@prod"):
            with self.subTest(host=host):
                self.prompt()
                self.ssh(host, "uptime")
                self.assertHeldOnce()

    def test_every_line_done_is_held_too_and_an_open_line_is_not(self):
        self.plan.write_text(DONE + "2026-10-09 12:00 · done 0123456789ab\n")
        self.ssh("prod", "uptime")
        self.assertHeldOnce()
        self.prompt()
        self.plan.write_text(OPEN)
        self.ssh("prod", "uptime")
        self.assertEqual(self.stop(), "")

    def test_no_reach_this_turn_lets_the_turn_end(self):
        self.ssh("prod", "uptime")
        self.prompt()                           # the reach was in an earlier turn
        self.assertEqual(self.stop(), "")
        for argv, seat, env in ((("other", "uptime"), "acme", None),
                                (("prod", "uptime"), "acme", {"AK_RUN_ROLE": "worker"}),
                                (("prod", "uptime"), None, None)):
            with self.subTest(argv=argv, seat=seat, env=env):
                self.prompt()
                self.ssh(*argv, seat=seat, env=env)
                self.assertEqual(self.stop(), "")

    def test_with_no_live_host_named_nothing_is_recorded(self):
        live = self.config.read_text()
        self.addCleanup(self.config.write_text, live)
        self.config.write_text(self.shipped)
        self.ssh("prod", "uptime")
        self.assertEqual(self.stop(), "")

    def test_plan_add_takes_a_passing_check_only_in_a_turn_that_reached_the_live_host(self):
        done = self.add()
        self.assertEqual((done.code, done.out, done.err), (2, "", PASSES))
        self.assertFalse(self.plan.exists())
        self.ssh("prod", "sudo enroll-monitor")
        done = self.add()
        self.assertEqual(done.code, 0, done.err)
        head = self.rig.head()[:12]
        self.assertTrue(done.out.startswith(DONE), done.out)
        self.assertTrue(done.out.endswith(f" · done {head}\n"), done.out)
        self.assertEqual(self.plan.read_text(), done.out)
        finished = subprocess.run(
            [sys.executable, "-c", "from agentkit import plan; print(plan.finished('acme'))"],
            capture_output=True, text=True, cwd=REPO, timeout=60,
            env={**self.home.env, "PYTHONPATH": str(REPO)})
        self.assertEqual(finished.stdout, "the monitor account is enrolled\n", finished.stderr)


if __name__ == "__main__":
    unittest.main()
