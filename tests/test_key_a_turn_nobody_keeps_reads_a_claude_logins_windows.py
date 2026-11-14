"""A turn nobody keeps reads a Claude login's windows: `usage_turn.meters` runs one turn of the
harness's `[check]` model on the login named, on no seat, and gives what it streamed of the
login's windows; nothing where the turn exited non-zero, ran past the usage probe's budget or
said nothing of a window.  The shipped adapter runs that turn with no tool and keeps no
conversation, and every other turn as before.

In a Home of tests/fixtures/akbin.py a child python3 asks the module, on the adapters of
tests/fixtures/fakeadapter.py, then on the shipped one with a stand-in for Claude Code.
"""

import json
from pathlib import Path
import sys
import time
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import fakeadapter
from fixtures.akbin import Home

REPO = Path(__file__).resolve().parents[1]
# A caller of the module: the meters of the turn on the login named, if any, as JSON.
READ = ("import json, sys; sys.path.insert(0, sys.argv[1]); from agentkit import usage_turn; "
        "print(json.dumps(usage_turn.meters('claude', *sys.argv[2:])))")


class ATurnNobodyKeepsReadsAClaudeLoginsWindows(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.now = int(time.time())
        self.check = tomllib.loads((REPO / "adapters/claude.toml").read_text())["check"]

    def stream(self, session, week):
        """What a `claude -p` turn streams of a login `session`% into its session and `week`%
        into its week."""
        return json.dumps({"type": "rate_limit_event", "rate_limit_info": {
            "status": "allowed" if session < 100 else "rejected", "unifiedWindows": {
                "five_hour": {"utilization": session / 100, "resetsAt": self.now + 10800},
                "seven_day": {"utilization": week / 100, "resetsAt": self.now + 259200}}}}) + "\n"

    def windows(self, session, week):
        """The meters ak reads that stream as."""
        return [{"name": "session", "used": session, "resets_at": self.now + 10800,
                 "window_secs": 18000},
                {"name": "weekly_all", "used": week, "resets_at": self.now + 259200,
                 "window_secs": 604800}]

    def meters(self, *account, **env):
        done = self.home.run(sys.executable, "-c", READ, str(REPO), *account, env=env)
        self.assertEqual(done.code, 0, done.err)
        return json.loads(done.out)

    def test_one_turn_of_the_check_model_reads_the_logins_windows_on_no_seat(self):
        claude = fakeadapter.install(
            self.home, claude={"events": self.stream(25, 50), "final": "Hi."})["claude"]
        # the caller is a seat, on a login of its own
        for account, login in ((["acme-second"], "acme-second"), ([], "")):
            with self.subTest(login=login or "the usual"):
                self.assertEqual(self.meters(*account, AGENTKIT_SESSION="fix-api",
                                             AGENTKIT_ACCOUNT="acme-third"),
                                 self.windows(25, 50))
                turn = claude.runs()[-1]
                self.assertEqual(turn["argv"][:2], [self.check["model"], self.check["effort"]])
                self.assertEqual(turn["env"]["AGENTKIT_ACCOUNT"], login)
                self.assertNotIn("AGENTKIT_SESSION", turn["env"])
                self.assertEqual(turn["env"]["AGENTKIT_UNKEPT"], "1")

    def test_a_turn_refused_out_of_time_or_saying_nothing_reads_nothing(self):
        claude = fakeadapter.install(self.home, claude="pass")["claude"]
        for name, step in (("refused", {"events": self.stream(100, 50), "exit": 1,
                                        "final": "You've hit your limit"}),
                           # streamed, then still running at the probe's budget
                           ("out of time", {"events": self.stream(25, 50), "sh": "sleep 600"}),
                           ("silent", {"final": "Hi."})):
            with self.subTest(name):
                claude.behave(step)
                runs = claude.n
                self.assertEqual(self.meters(AGENTKIT_MUSE_USAGE_TIMEOUT="2"), [])
                self.assertEqual(claude.n, runs + 1)

    def test_the_shipped_adapter_runs_it_with_no_tool_keeping_no_conversation(self):
        log = self.home.root / "claude-argv"
        self.home.fake("claude", f"#!{sys.executable} -I\nimport json, sys\n"
                                 f"with open({str(log)!r}, 'a') as log:\n"
                                 "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                                 f"sys.stdin.read()\nprint({self.stream(25, 50).strip()!r})\n")
        self.assertEqual(self.meters(), self.windows(25, 50))
        prompt = self.home.write("prompt.md", "Fix the api.\n")
        done = self.home.run(str(REPO / "adapters/claude.sh"), "run", "m-1", "high",
                             str(self.home.path), str(prompt), str(self.home.path / "out"))
        self.assertEqual(done.code, 0, done.err)
        unkept, kept = map(json.loads, log.read_text().splitlines())
        self.assertEqual(unkept[unkept.index("--tools") + 1], "")
        self.assertIn("--no-session-persistence", unkept)
        self.assertEqual(unkept[unkept.index("--model") + 1], self.check["model"])
        self.assertFalse({"--tools", "--no-session-persistence"} & set(kept), kept)


if __name__ == "__main__":
    unittest.main()
