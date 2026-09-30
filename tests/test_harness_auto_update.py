"""Every harness keeps itself on its latest release, in the background.

The tick asks each harness's `[update] latest` at most hourly; one this host has that is behind
it is upgraded through `ak update`'s own gated path -- the upgrade, both gates, the revert --
while sessions work, one upgrade at a time host-wide.  A failed gate puts it back and is said
once in the tick's log, and that release is tried again a day after its last start, a newer
one at once.

Offline throughout: `acme` is a fake harness whose manifest, binary and release source live
under a temporary HOME, the checkout the tick runs from is a throwaway directory holding two
fake gates, and the background child runs in-process.  No real harness, upgrade or
`tests/smoke.sh` is ever run.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, update

START = update.start   # the real starter, before a test stands in for it

T = 1_000_000.0     # the first tick's clock
MANIFEST = """version = 1
[update]
version = ["acme", "--version"]
upgrade = ["acme", "upgrade"]
revert = ["acme", "install", "{version}"]
latest = ["acme-latest"]
"""
# installed: the build on this host; released: what the release source says is newest;
# calls: every upgrade and reinstall; asks: every question put to the release source
ACME = """#!/bin/sh
case "$1" in
  --version) cat "{root}/installed" ;;
  upgrade) echo upgrade >>"{root}/calls"; cp "{root}/released" "{root}/installed" ;;
  install) echo "install $2" >>"{root}/calls"; echo "$2" >"{root}/installed" ;;
  session) exec sleep 600 ;;
esac
"""
LATEST = '#!/bin/sh\necho asked >>"{root}/asks"\ncat "{root}/released"\n'


class HarnessAutoUpdate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-harness-auto-update-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for directory in ("bin", "adapters", "agentkit/tests"):
            (root / directory).mkdir(parents=True)
        (root / "adapters/acme.toml").write_text(MANIFEST)
        for name, text in (("bin/acme", ACME), ("bin/acme-latest", LATEST),
                           ("agentkit/tests/smoke.sh", 'exit "$(cat "{root}/smoke")"\n'),
                           ("agentkit/tests/e2e-fresh.sh", "exit 0\n")):
            (root / name).write_text(text.format(root=root))
            (root / name).chmod(0o755)
        self.write(installed="1.0.0", released="2.0.0", smoke="0")
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
            config.ADAPTER_DIR_ENV: str(root / "adapters")}))
        self.stack.enter_context(patch.object(config, "HOME", root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        # the tick moves only from the checkout it runs from: here, the throwaway one
        self.stack.enter_context(patch.object(config, "REPO", root / "agentkit"))
        cfg = {"models": {"acme-model": {"harness": "acme", "provider": "acme"}},
               "providers": {"acme": {}}}
        self.stack.enter_context(patch.object(config, "load", return_value=cfg))
        # a session is working the whole time, and that holds nothing back
        self.working = self.stack.enter_context(
            patch.object(update, "working_sessions", return_value=["atoll"]))
        # the detached child, run here and now instead
        self.start = self.stack.enter_context(
            patch.object(update, "start", side_effect=update.background))

    def write(self, **files):
        for name, text in files.items():
            (self.root / name).write_text(text + "\n")

    def read(self, name):
        path = self.root / name
        return path.read_text().splitlines() if path.exists() else []

    def tick(self, now):
        """One tick's harness pass: what it wrote to the tick's log."""
        said = []
        update.keep_current(said.append, now=now)
        return said

    def test_behind_is_upgraded_in_the_background_while_a_session_works(self):
        seat = subprocess.Popen([str(self.root / "bin/acme"), "session"])
        self.addCleanup(seat.wait)
        self.addCleanup(seat.kill)
        self.assertEqual(self.tick(T),
                         ["acme 1.0.0 is behind 2.0.0: upgrading it in the background"])
        self.assertEqual(self.read("installed"), ["2.0.0"])
        self.assertEqual(self.read("calls"), ["upgrade"])
        said = self.tick(T + 180)
        self.assertEqual(said[0], "the background upgrade of acme:")
        self.assertIn("  update: acme: upgraded, 1.0.0->2.0.0", said)
        self.assertEqual(self.tick(T + 360), [])            # said once
        self.assertEqual(self.read("asks"), ["asked"])      # asked once in the hour
        self.assertEqual(self.tick(T + update.ASK_EVERY), [])
        self.assertEqual(self.read("asks"), ["asked"] * 2)  # current now: nothing to do
        self.assertEqual(self.read("calls"), ["upgrade"])
        self.assertIsNone(seat.poll())                      # the seat worked through it
        self.working.assert_not_called()

    def test_a_failed_gate_reverts_once_and_that_release_is_retried_only_after_a_day(self):
        self.write(smoke="1")
        self.assertEqual(self.tick(T),
                         ["acme 1.0.0 is behind 2.0.0: upgrading it in the background"])
        self.assertEqual(self.read("installed"), ["1.0.0"])
        self.assertEqual(self.read("calls"), ["upgrade", "install 1.0.0"])
        said = self.tick(T + 180)
        self.assertEqual(said[0], "WARN the background upgrade of acme failed:")
        self.assertTrue(any("smoke FAILED after acme 1.0.0->2.0.0" in line for line in said), said)
        self.assertIn("  update: acme: reverted, back on 1.0.0", said)
        # not within the day of its start
        for later in (T + 360, T + update.ASK_EVERY, T + update.RETRY_AFTER - update.ASK_EVERY):
            self.assertEqual(self.tick(later), [])
        self.assertEqual(self.read("asks"), ["asked"] * 3)
        self.assertEqual(self.read("calls"), ["upgrade", "install 1.0.0"])
        # after it, the same release is started again; it fails again, and the day counts anew
        day = T + update.RETRY_AFTER
        self.assertEqual(self.tick(day),
                         ["acme 1.0.0 is behind 2.0.0: upgrading it in the background"])
        self.assertEqual(self.read("calls"), ["upgrade", "install 1.0.0"] * 2)
        self.assertEqual(self.tick(day + 180)[0], "WARN the background upgrade of acme failed:")
        self.assertEqual(self.tick(day + update.ASK_EVERY), [])
        self.assertEqual(self.read("calls"), ["upgrade", "install 1.0.0"] * 2)
        # a newer release is tried at once, and passes
        self.write(released="2.1.0", smoke="0")
        self.assertEqual(self.tick(day + 2 * update.ASK_EVERY),
                         ["acme 1.0.0 is behind 2.1.0: upgrading it in the background"])
        self.assertEqual(self.read("installed"), ["2.1.0"])

    def test_one_upgrade_at_a_time_host_wide(self):
        held = update.one_at_a_time()
        self.assertIsNotNone(held)
        with held:
            self.assertEqual(self.tick(T), [])
            self.assertEqual(self.read("asks"), [])
            self.assertEqual(update.background("acme"), 0)
            out = io.StringIO()
            with patch.object(self.working, "return_value", []), \
                    patch.object(update, "update_self", return_value=0), \
                    redirect_stdout(out), redirect_stderr(out):
                self.assertEqual(update.main([]), 0)
            self.assertIn("update: harnesses: skipped: another upgrade is running", out.getvalue())
        self.assertEqual(self.read("calls"), [])
        self.start.assert_not_called()
        self.assertEqual(self.tick(T + 180),
                         ["acme 1.0.0 is behind 2.0.0: upgrading it in the background"])

    def test_a_tick_from_another_checkout_never_upgrades_a_harness(self):
        with patch.object(config, "REPO", REPO):
            self.assertEqual(self.tick(T), [])
        self.assertEqual(self.read("asks"), [])
        self.start.assert_not_called()

    def test_the_upgrade_outlives_the_tick_that_starts_it(self):
        with patch.object(update.subprocess, "Popen") as popen:
            START("acme")
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [sys.executable, "-m", "agentkit.update", "acme"])
        self.assertEqual(kwargs["cwd"], config.REPO)
        self.assertTrue(kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()
