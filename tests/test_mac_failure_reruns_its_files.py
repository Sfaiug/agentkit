"""A piece that fails on the suite helper naming its failed tests runs those alone here: failing,
it is red; passing, the piece runs whole here, and passing that too, the suite passes with a
flake note naming the helper. One that names none runs whole here. Offline: the fake `ssh` of test_suite_helper, whose piece 2/6 fails there.
"""

import io
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_suite_helper as fixture
from agentkit import gate, helper, worker

# The helper hands back what the failed piece named, as failed or flaky, as mac.sh's `failed` does.
FAKE_SSH = fixture.FAKE_SSH.replace("esac", 'failed) cat "$here/$8" 2>/dev/null ;;\nesac')

# The whole piece, or the tests AK_ONLY lists, failing with ACME_RED.
SUITE = ('[ -n "$AK_ONLY" ] || { printf "piece %s\\n" "$AK_SHARD"; exit; }; '
         'printf "listed [%s]\\n" "$(cat "$AK_ONLY")"; '
         '[ -z "$ACME_RED" ] || { cat "$AK_ONLY" >>"$AK_FAILED"; exit 1; }')


class MacFailureRerunsItsFiles(unittest.TestCase):
    turn = fixture.SuiteHelper.turn

    def setUp(self):
        fixture.SuiteHelper.setUp(self)
        (self.fake / "ssh").write_text(FAKE_SSH)
        (self.fake / "code-2").write_text("1")

    def suite(self, named="", flaky=None, **env):
        (self.fake / "failed").write_text(named)
        with patch.dict(os.environ, env):
            code, text, _ = gate.run_suite(SUITE, 30, cwd=self.repo,
                                           activity=self.root / "live.log", output=io.BytesIO(),
                                           log=lambda _line: None, stderr=subprocess.STDOUT,
                                           flaky=flaky)
        return code, text

    def test_what_a_piece_there_names_flaky_is_flaky(self):
        (self.fake / "flaky").write_text("tests/test_b.py\n")
        flaky = []
        self.assertEqual(self.suite(flaky=flaky)[0], 0)
        self.assertIn("tests/test_b.py", flaky)

    def test_its_failed_tests_alone_passing_here_run_it_whole_a_flake_of_the_helper(self):
        boxed, busy = worker.boxed, []

        def once_busy(*args, only=None, **kw):   # its turn goes back; its tests run after
            if only and not busy:
                busy.append(only)
                return gate.SUITE_BUSY, "", False
            return boxed(*args, only=only, **kw)
        for first in (boxed, once_busy):
            with self.subTest(first=first.__name__), patch.object(worker, "boxed", first), \
                    patch.object(gate, "busy_turn", return_value=0):
                code, text = self.suite("tests/test_a.py\n")
                self.assertEqual(code, 0, text)
                self.assertIn("--- AK_SHARD=2/6 ---\n[exit 0]\npiece 2/6\n", text)
                self.assertIn(f"flaky: {SUITE} (AK_SHARD=2/6) failed on the suite helper "
                              "acme-mac, then passed on its re-run", text)
        self.assertEqual(busy, [["tests/test_a.py"]])

    def test_its_failed_tests_failing_here_keep_it_red(self):
        code, text = self.suite("tests/test_a.py\n", ACME_RED="1")
        self.assertEqual(code, 1, text)
        self.assertIn("--- AK_SHARD=2/6 ---\n[exit 1]\n"
                      "its failed tests failed again, run alone\n"
                      "listed [tests/test_a.py]", text)
        self.assertNotIn("flaky:", text)

    def test_a_piece_that_named_no_test_runs_whole_here(self):
        code, text = self.suite()
        self.assertEqual(code, 0, text)
        self.assertIn("--- AK_SHARD=2/6 ---\n[exit 0]\npiece 2/6", text)
        self.assertNotIn("listed", text)


class MacHandsBackTheNames(unittest.TestCase):
    setUp, git = fixture.HelperMac.setUp, fixture.HelperMac.git

    def test_failed_reads_what_the_piece_named_never_through_a_link(self):
        away = helper.Away("acme-mac", "key", "acme", "ak-helper:new", 1, 2, 512, 1, "", "", "")
        named = self.root / "key" / "ak-key-1-1.out" / "failed"
        named.parent.mkdir(parents=True)
        named.write_text("tests/test_a.py\n\ntests/test_a.py\n")
        self.assertEqual(helper.failed(away, "1/1"), ["tests/test_a.py"])
        named.with_name("flaky").write_text("tests/test_b.py\n")
        self.assertEqual(helper.failed(away, "1/1", "flaky"), ["tests/test_b.py"])
        named.unlink()
        named.symlink_to(self.fake / "sysctl")    # a file of the Mac's own
        self.assertEqual(helper.failed(away, "1/1"), [])

    def test_each_piece_starts_with_no_names_and_a_folder_the_vm_writes(self):
        away = helper.Away("acme-mac", "key", "acme", "ak-helper:new", 1, 2, 512, 1, "", "", "")
        (self.root / "mirrors" / "acme").mkdir(parents=True)
        named = self.root / "key" / "ak-key-1-1.out" / "failed"
        named.parent.mkdir(parents=True)
        named.write_text("tests/test_a.py\n")    # what an earlier command's piece named
        run = subprocess.Popen(helper._remote("acme-mac", "run", "key", "ak-helper:new",
                                              "ak-key-1-1", 1, 512, "acme"),
                               stdout=subprocess.DEVNULL)
        vm, deadline = self.fake / "vm-ak-key-1-1", time.monotonic() + 30
        while not vm.exists():
            self.assertLess(time.monotonic(), deadline, "the VM never came up")
            time.sleep(0.1)
        vm.unlink()
        self.assertEqual(run.wait(30), 0)
        self.assertEqual(helper.failed(away, "1/1"), [])
        self.assertEqual(named.parent.stat().st_mode & 0o777, 0o777)


if __name__ == "__main__":
    unittest.main()
