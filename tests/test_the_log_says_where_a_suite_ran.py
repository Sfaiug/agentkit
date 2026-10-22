"""Every suite placement reaches the lander's log, with the reason for running here.

Offline: temporary repositories and HOME, fake ssh exits, no owner notifications.
"""

from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_suite_helper as suite_fixture
from agentkit import config, gate, helper, land, run

SUITE = suite_fixture.SUITE


class SuiteLocation(unittest.TestCase):
    turn = suite_fixture.SuiteHelper.turn

    def setUp(self):
        suite_fixture.SuiteHelper.setUp(self)
        self.stack.enter_context(patch.object(gate, "derived_heavy_limit", return_value=2))

    def check(self, command=SUITE, *, shard=None, only=None, landing=True):
        state = {"repo": str(self.repo), "waiting_on": {"joined": 1, "line": ".merge-acme"}}
        result = []

        def check_line(_turn, log):
            if landing:
                result.append(land._check(self.root, state, self.repo, [command],
                                          self.root / "suite.log", log, shard=shard, only=only)[0])
            else:
                result.append(gate.run_done_when([command], self.repo, self.root / "suite.log",
                                                 set(), log=log, shard=shard, only=only)[0])

        with (self.root / "lander.log").open("w") as output, redirect_stdout(output), \
                patch.object(land, "check_line", side_effect=check_line):
            self.assertEqual(run.main(["--lander", ".merge-acme"]), 0)
        self.assertEqual(result, [True], (self.root / "suite.log").read_text())
        return (self.root / "lander.log").read_text()

    def response(self, verb, code, reply="diagnostic says battery, regardless of the exit\n"):
        script = suite_fixture.FAKE_SSH.replace('case $5 in', '''if [ -e "$here/exit-$5" ]; then
  cat "$here/reply-$5"; exit "$(cat "$here/exit-$5")"
fi
case $5 in''')
        (self.fake / "ssh").write_text(script)
        (self.fake / f"exit-{verb}").write_text(str(code))
        (self.fake / f"reply-{verb}").write_text(reply)

    def assert_here(self, log, reason):
        self.assertEqual(log.count(f"suite runs here: {reason}\n"), 1, log)
        for shard in ("1/2", "2/2"):
            self.assertEqual(log.count(f"AK_SHARD={shard} runs here: {reason}\n"), 1, log)

    def test_no_helper_or_recipe_says_why_without_contacting_the_mac(self):
        (config.HOME / config.CONFIG_NAME).write_text("")
        for landing in (True, False):
            self.assert_here(self.check(landing=landing), "no suite helper set up")
        self.assertFalse((self.fake / "calls").exists())
        (config.HOME / config.CONFIG_NAME).write_text('suite_helper = "acme-mac"\n')
        subprocess.run([*self.git, "rm", "-q", helper.RECIPE], check=True)
        subprocess.run([*self.git, "commit", "-qm", "no recipe"], check=True)
        self.assert_here(self.check(), "no recipe for the suite helper acme-mac")
        self.assertFalse((self.fake / "calls").exists())

    def test_probe_and_prepare_codes_each_say_why_in_the_lander_log(self):
        reasons = {255: "did not answer (asleep or away)", 251: "is on battery",
                   252: "is busy", 253: "could not prepare or run the container",
                   17: "failed (exit 17)"}
        for verb in ("probe", "prepare"):
            for code, reason in reasons.items():
                with self.subTest(verb=verb, code=code):
                    self.response(verb, code)
                    self.assert_here(self.check(), f"helper acme-mac {reason}")
            (self.fake / f"exit-{verb}").unlink()

    def test_no_room_names_the_spare_cpus_and_memory(self):
        for cpus, memory in ((1, 1048576), (6, 10)):
            with self.subTest(cpus=cpus, memory=memory):
                self.response("probe", 0,
                              f"cpus {cpus}\nload 0\nmemory_mb {memory}\nfree_percent 100\n")
                self.assert_here(self.check(),
                                 f"helper acme-mac has no room ({cpus} spare CPUs and "
                                 f"{memory / 2:g} MiB)")

    def test_timeout_or_unreadable_readings_explains_the_fallback(self):
        for reply in ("", "cpus unknown\n", "cpus 6\nload 0\nmemory_mb NaN\nfree_percent 50\n"):
            with self.subTest(reply=reply):
                self.response("probe", 0, reply)
                self.assert_here(self.check(), "helper acme-mac did not answer (asleep or away)")
        with patch.object(helper, "_remote", side_effect=subprocess.TimeoutExpired("ssh", 30)):
            self.assert_here(self.check(), "helper acme-mac did not answer (asleep or away)")

    def test_helper_success_names_the_mac_and_each_piece(self):
        log = self.check()
        self.assertIn("suite on acme-mac: 3 pieces, 2 CPUs", log)
        for shard in ("1/3", "2/3", "3/3"):
            self.assertIn(f"AK_SHARD={shard} on acme-mac\n", log)

    def test_each_piece_returned_by_the_helper_names_its_reason_here(self):
        for code, reason in ((255, "did not answer (asleep or away)"), (251, "is on battery"),
                             (252, "is busy"), (253, "could not prepare or run the container"),
                             (1, "failed (exit 1)"), (254, "ran out of memory")):
            with self.subTest(code=code):
                (self.fake / "code-2").write_text(str(code))
                log = self.check()
                self.assertIn("AK_SHARD=2/3 on acme-mac\n", log)
                self.assertIn(f"AK_SHARD=2/3 runs here: helper acme-mac {reason}\n", log)

    def test_unsplit_and_pinned_commands_say_they_are_not_sent_there(self):
        for landing in (True, False):
            with self.subTest(landing=landing):
                self.assertIn("suite runs here: command is not sent to the suite helper "
                              "(does not name AK_SHARD)\n", self.check("true", landing=landing))
                for only, label in ((None, "2/3"), ([], "2/3, its failed tests alone")):
                    self.assertIn(f"AK_SHARD={label} runs here: command is not sent to the "
                                  "suite helper (pinned piece)\n",
                                  self.check(shard="2/3", only=only, landing=landing))
        self.assertFalse((self.fake / "calls").exists())


if __name__ == "__main__":
    unittest.main()
