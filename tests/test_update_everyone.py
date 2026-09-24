"""`ak update` works for everyone, and the server alias is one value.

Offline throughout: harness upgrades, gates and installs are stand-ins, and HOME is a
temporary directory. What is pinned is the contract -- a gate that cannot run on this
host is a `skipped:` line, never a refusal; so is a harness this host does not have; no
harness moves while a session is working, and agentkit itself moves whether or not one is;
and the bridge reaches the server install.sh recorded, not a literal alias.
"""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
from pathlib import Path
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, macbridge, update


PLAN = [{"name": "echo", "version": ["echo", "1.0.0"], "upgrade": ["echo", "upgrade"],
         "revert": None, "env": {}, "cannot": "a fixture with no installer",
         "snapshot_dir": ""}]


class Everyone(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".update-everyone-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        (self.root / "agentkit" / ".git").mkdir(parents=True)

    def test_dry_run_lists_gates_as_run_or_skipped_without_refusing(self):
        for why in ("", "fixture: no throwaway account here"):
            with self.subTest(why=why or "available"):
                out = io.StringIO()
                with patch.object(update, "harnesses", return_value=PLAN), \
                        patch.object(update, "version", return_value="1.0.0"), \
                        patch.object(update, "fresh_unavailable", return_value=why), \
                        patch.object(update, "working_sessions", return_value=[]), \
                        redirect_stdout(out):
                    self.assertEqual(update.main(["--dry-run"]), 0)
                text = out.getvalue()
                self.assertIn("dry run, nothing changed", text)
                self.assertIn("update: gate smoke: run", text)
                if why:
                    self.assertIn(f"update: gate fresh: skipped: {why}", text)
                else:
                    self.assertIn("update: gate fresh: run", text)
                self.assertNotIn("nothing was upgraded or verified", text)
                self.assertNotIn("INCOMPLETE", text)

    def test_unavailable_fresh_gate_is_skipped_not_a_refusal(self):
        calls = []
        out = io.StringIO()
        with patch.object(update, "harnesses", return_value=PLAN), \
                patch.object(update, "version", return_value="1.0.0"), \
                patch.object(update, "fresh_unavailable",
                             return_value="fixture: no throwaway account here"), \
                patch.object(update, "step",
                             side_effect=lambda cmd, *a, **k: calls.append(cmd) or True), \
                patch.object(update, "working_sessions", return_value=[]), \
                patch.object(update, "update_agentkit", return_value=0) as selfmove, \
                redirect_stdout(out), redirect_stderr(out):
            self.assertEqual(update.main([]), 0)
        text = out.getvalue()
        self.assertIn("skipped: fixture: no throwaway account here", text)
        self.assertNotIn("nothing was upgraded or verified", text)
        self.assertNotIn("the gate was not run", text)
        self.assertEqual(calls[0], PLAN[0]["upgrade"])
        self.assertEqual(calls[1][:2], ["bash", str(config.REPO / "tests/smoke.sh")])
        self.assertEqual(len(calls), 2)
        selfmove.assert_called_once_with()

    def test_fresh_gate_skips_on_its_own_exit_after_smoke_passed(self):
        # The real host path: smoke wrote its acceptance line to the shared log first,
        # then the fresh gate left before its first check. Only its own appended lines
        # may classify it -- the smoke line must not read as a failed fresh run.
        smoke = config.REPO / "tests/smoke.sh"

        def run(cmd, fh, env=None, timeout=None):
            fh.write(f"\n$ {' '.join(cmd)}\n")
            if cmd == ["bash", str(smoke)]:
                fh.write("1 passed, 0 failed, 0 skipped\n"
                         "acceptance: all checks exercised and passed\n[exit 0]\n")
            else:
                fh.write("e2e-fresh.sh: fixture cannot make a throwaway account here\n"
                         "[exit 2]\n")
            fh.flush()
            return cmd == ["bash", str(smoke)] or cmd == PLAN[0]["upgrade"]

        out = io.StringIO()
        with patch.object(update, "harnesses", return_value=PLAN), \
                patch.object(update, "version", return_value="1.0.0"), \
                patch.object(update, "fresh_unavailable", return_value=""), \
                patch.object(update, "step", side_effect=run), \
                patch.object(update, "working_sessions", return_value=[]), \
                patch.object(update, "update_agentkit", return_value=0) as selfmove, \
                redirect_stdout(out), redirect_stderr(out):
            self.assertEqual(update.main([]), 0)
        text = out.getvalue()
        self.assertIn("skipped: fixture cannot make a throwaway account here", text)
        self.assertNotIn("FAILED", text)
        self.assertNotIn("reverted", text)
        self.assertNotIn("cannot revert", text)
        selfmove.assert_called_once_with()

    def test_client_with_no_harness_still_moves_its_checkout(self):
        out = io.StringIO()
        with patch.object(update, "harnesses", return_value=PLAN), \
                patch.object(update, "version", return_value=""), \
                patch.object(update.shutil, "which", return_value=None), \
                patch.object(update, "step",
                             side_effect=AssertionError("no gate runs with nothing to verify")), \
                patch.object(update, "working_sessions", return_value=[]), \
                patch.object(update, "update_agentkit", return_value=0) as selfmove, \
                redirect_stdout(out), redirect_stderr(out):
            self.assertEqual(update.main([]), 0)
        text = out.getvalue()
        self.assertIn("update: no harness installed here; nothing to upgrade", text)
        self.assertNotIn("the gate was not run", text)
        selfmove.assert_called_once_with()

    def test_no_harness_and_no_checkout_is_exit_1_with_no_gate(self):
        # Where the checkout cannot move either, nothing at all happened: the exit-1
        # the gate pins, in the same words, without running anything.
        shutil.rmtree(self.root / "agentkit")
        out = io.StringIO()
        with patch.object(update, "harnesses", return_value=PLAN), \
                patch.object(update, "version", return_value=""), \
                patch.object(update.shutil, "which", return_value=None), \
                patch.object(update, "step",
                             side_effect=AssertionError("the gate was not run")), \
                patch.object(update, "working_sessions", return_value=[]), \
                patch.object(update, "update_agentkit",
                             side_effect=AssertionError("no checkout to move")), \
                redirect_stdout(out), redirect_stderr(out):
            self.assertEqual(update.main([]), 1)
        text = out.getvalue()
        self.assertIn("update: agentkit: skipped: no checkout at ", text)
        self.assertIn("nothing was upgraded", text)
        self.assertIn("the gate was not run", text)

    def test_working_word_detection_names_only_working_sessions(self):
        seats = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        words = {"a": "working", "b": "needs you", "c": "working"}
        with patch("agentkit.orch.listing", return_value=seats) as listing, \
                patch("agentkit.watch.session_state",
                      side_effect=lambda name, **k: {"word": words[name]}):
            self.assertEqual(update.working_sessions(cfg={}), ["a", "c"])
        listing.assert_called_once_with(reconcile=False)

    def test_agentkit_moves_while_sessions_work(self):
        # A refusal to upgrade under a working session is no failure: exit 0 even where
        # agentkit's own move then fails, and that failure is still said.
        for working, moved in ((["atoll", "vega"], 0), (["atoll", "vega"], 1), ([], 0)):
            with self.subTest(working=working, moved=moved):
                calls = []
                out = io.StringIO()
                with patch.object(update, "harnesses", return_value=PLAN), \
                        patch.object(update, "version", return_value="1.0.0"), \
                        patch.object(update, "step",
                                     side_effect=lambda cmd, *a, **k: calls.append(cmd) or True), \
                        patch.object(update, "fresh_gate",
                                     return_value=(True, "passed (fixture)")), \
                        patch.object(update, "working_sessions", return_value=working), \
                        patch.object(update, "update_agentkit",
                                     side_effect=lambda: print("fixture: pull failed") or moved) \
                        as selfmove, \
                        redirect_stdout(out), redirect_stderr(out):
                    self.assertEqual(update.main([]), 0)
                selfmove.assert_called_once_with()
                self.assertNotIn("agentkit: skipped:", out.getvalue())
                if moved:
                    self.assertIn("fixture: pull failed", out.getvalue())
                if working:
                    # no harness moves under a working session, and no gate runs for nothing
                    self.assertEqual(calls, [])
                    self.assertIn("update: harnesses: skipped: 2 sessions are working "
                                  "(atoll, vega)", out.getvalue())
                else:
                    self.assertEqual(calls[0], PLAN[0]["upgrade"])

    def test_one_harness_host_upgrades_it_through_the_gates(self):
        # Only echo on this host.  gone, configured but not installed, is a skipped line and is
        # never run; echo upgrades through both gates and goes back when either fails.  While a
        # session works nothing upgrades, the sessions are named, and the exit is 0.
        echo = {**PLAN[0], "revert": ["echo", "install", "{version}"]}
        both = [echo, {**PLAN[0], "name": "gone", "version": ["ak-fixture-gone", "--version"],
                       "upgrade": ["ak-fixture-gone", "upgrade"]}]
        smoke = ["bash", str(config.REPO / "tests/smoke.sh")]
        back = ["echo", "install", "1.0.0"]
        for argv, working, failing in ((["--dry-run"], [], ""), ([], [], ""), ([], [], "smoke"),
                                       ([], [], "fresh"), ([], ["atoll", "vega"], "")):
            with self.subTest(argv=argv, working=working, failing=failing):
                versions = {"echo": "1.0.0", "gone": ""}
                calls = []

                def run(cmd, *a, **k):
                    calls.append(cmd)
                    versions["echo"] = {tuple(echo["upgrade"]): "2.0.0",
                                        tuple(back): "1.0.0"}.get(tuple(cmd), versions["echo"])
                    return cmd != smoke or failing != "smoke"

                out = io.StringIO()
                with patch.object(update, "harnesses", return_value=both), \
                        patch.object(update, "version", side_effect=lambda h: versions[h["name"]]), \
                        patch.object(update, "step", side_effect=run), \
                        patch.object(update, "fresh_gate",
                                     return_value=(failing != "fresh", "failed" if failing else "passed")), \
                        patch.object(update, "working_sessions", return_value=working), \
                        patch.object(update, "update_agentkit", return_value=0) as selfmove, \
                        redirect_stdout(out), redirect_stderr(out):
                    self.assertEqual(update.main(argv), 1 if failing else 0)
                text = out.getvalue()
                self.assertIn("update: gone: skipped: not installed here", text)
                if argv:
                    # the plan still names every configured harness, the absent one too
                    self.assertIn("echo 1.0.0 (versioned reinstall available): echo upgrade", text)
                    self.assertIn("gone not installed (", text)
                    self.assertIn("update: gate smoke: run", text)
                    self.assertEqual(calls, [])
                elif working:
                    self.assertIn("update: harnesses: skipped: 2 sessions are working "
                                  "(atoll, vega)", text)
                    self.assertEqual(calls, [])
                    selfmove.assert_called_once_with()
                elif failing:
                    self.assertEqual(calls, [echo["upgrade"], smoke, back])
                    self.assertIn("FAILED after echo 1.0.0->2.0.0", text)
                    self.assertIn("update: echo: reverted, back on 1.0.0", text)
                    selfmove.assert_not_called()
                else:
                    self.assertEqual(calls, [echo["upgrade"], smoke])
                    self.assertIn("update: echo: upgraded, 1.0.0->2.0.0", text)
                    selfmove.assert_called_once_with()

    def test_macbridge_has_no_literal_server_alias(self):
        text = (REPO / "agentkit/macbridge.py").read_text()
        # every ssh target is the recorded alias, never a host name written into the code
        self.assertEqual(set(re.findall(r'"-T", ([^,\]]+)', text)), {"server()"})
        self.assertIn("server_alias", text)
        with patch.object(config, "server_alias", return_value="myserver"):
            self.assertEqual(macbridge.server(), "myserver")
            with patch.object(macbridge.subprocess, "run") as call:
                macbridge.publish_error("0123456789abcdef", "fixture", [], io.StringIO())
            self.assertEqual(call.call_args.args[0][:3], ["ssh", "-T", "myserver"])
        with patch.object(config, "server_alias", return_value=None):
            with self.assertRaises(config.Error):
                macbridge.server()

    def test_client_install_writes_the_alias_the_bridge_reads(self):
        home = self.root / "client-home"
        home.mkdir()
        alias = "myserver"
        proc = subprocess.run(["bash", str(REPO / "install.sh"), "--client", alias],
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, "HOME": str(home)})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        record = home / ".agentkit/state/server"
        self.assertEqual(record.read_text().splitlines()[0], alias)
        with patch.object(config, "STATE", record.parent):
            self.assertEqual(config.server_alias(), alias)
            self.assertEqual(macbridge.server(), alias)


if __name__ == "__main__":
    unittest.main()
