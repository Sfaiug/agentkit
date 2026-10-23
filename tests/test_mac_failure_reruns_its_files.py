"""A piece that fails on the suite helper naming its failed tests runs only those here: passing,
the suite passes with a flake note naming the helper; failing, it is red. One that names none
runs whole here. Offline: the fake `ssh` of test_suite_helper, whose piece 2/3 fails there.
"""

import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_suite_helper as fixture
from agentkit import gate, helper

# The helper hands back what the failed piece named (`named`), as mac.sh's `failed` does.
FAKE_SSH = fixture.FAKE_SSH.replace("esac", 'failed) cat "$here/named" 2>/dev/null ;;\nesac')

# The whole piece, or the tests AK_ONLY lists, named as run unless ACME_UNNAMED, failing with
# ACME_RED.
SUITE = ('[ -n "$AK_ONLY" ] || { printf "piece %s\\n" "$AK_SHARD"; exit; }; '
         'printf "listed [%s]\\n" "$(cat "$AK_ONLY")"; '
         '[ -n "$ACME_UNNAMED" ] || cat "$AK_ONLY" >>"$AK_RAN"; '
         '[ -z "$ACME_RED" ] || { cat "$AK_ONLY" >>"$AK_FAILED"; exit 1; }')


class MacFailureRerunsItsFiles(unittest.TestCase):
    turn = fixture.SuiteHelper.turn

    def setUp(self):
        fixture.SuiteHelper.setUp(self)
        (self.fake / "ssh").write_text(FAKE_SSH)
        (self.fake / "code-2").write_text("1")

    def suite(self, named="", **env):
        (self.fake / "named").write_text(named)
        with patch.dict(os.environ, env):
            code, text, _ = gate.run_suite(SUITE, 30, cwd=self.repo,
                                           activity=self.root / "live.log", output=io.BytesIO(),
                                           log=lambda _line: None, stderr=subprocess.STDOUT)
        return code, text

    def test_its_failed_tests_alone_passing_here_pass_it_as_a_flake_of_the_helper(self):
        code, text = self.suite("tests/test_a.py\n")
        self.assertEqual(code, 0, text)
        self.assertIn("--- AK_SHARD=2/3 ---\n[exit 0]\nlisted [tests/test_a.py]\n", text)
        self.assertNotIn("piece 2/3", text)
        self.assertIn(f"flaky: {SUITE} (AK_SHARD=2/3) failed on the suite helper acme-mac, "
                      "then passed on its re-run", text)

    def test_its_failed_tests_failing_here_or_not_named_as_run_keep_it_red(self):
        for env in ({"ACME_RED": "1"}, {"ACME_UNNAMED": "1"}):
            with self.subTest(env=env):
                code, text = self.suite("tests/test_a.py\n", **env)
                self.assertEqual(code, 1, text)
                self.assertIn("--- AK_SHARD=2/3 ---\n[exit 1]\n"
                              "its failed tests failed again here, run alone\n"
                              "listed [tests/test_a.py]", text)
                self.assertNotIn("flaky:", text)

    def test_a_piece_that_named_no_test_runs_whole_here(self):
        code, text = self.suite()
        self.assertEqual(code, 0, text)
        self.assertIn("--- AK_SHARD=2/3 ---\n[exit 0]\npiece 2/3", text)
        self.assertNotIn("listed", text)


class MacHandsBackTheNames(unittest.TestCase):
    setUp, git = fixture.HelperMac.setUp, fixture.HelperMac.git

    def test_failed_reads_what_the_piece_named_never_through_a_link(self):
        away = helper.Away("acme-mac", "key", "acme", "ak-helper:new", 1, 2, 512, "", "", "")
        named = self.root / "key" / "ak-key-1-1.out" / "failed"
        named.parent.mkdir(parents=True)
        named.write_text("tests/test_a.py\n\ntests/test_a.py\n")
        self.assertEqual(helper.failed(away, "1/1"), ["tests/test_a.py"])
        named.unlink()
        named.symlink_to(self.fake / "sysctl")    # a file of the Mac's own
        self.assertEqual(helper.failed(away, "1/1"), [])


if __name__ == "__main__":
    unittest.main()
