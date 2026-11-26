"""A cleanup pass locks `~/.agentkit/state`, leaving `~/.agentkit` and `config.tmp` free for config saves.

A pass (`ak run gc`, both its sweep and its collector) serialises on `~/.agentkit/state` without
creating a lock file, never on `~/.agentkit` where config writes take their lock.  While a pass is
held open in the middle of removing a candidate, a config write from another process completes
without waiting for it and saves its changes, while a second `ak run gc` still sees the pass busy
and prints `gc: no eligible artifacts`.  A week-old `config.tmp` at the top of `~/.agentkit` is
ak's own temporary file, never planned or removed by collection.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, boxed
with a /tmp and processes of its own for collection, and on the echo fixture's harness for the
config-writing `ak orch` call.
"""

import contextlib
import fcntl
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REAL_TMUX, boxable, Home
from fixtures.garbage import DAY, ROOM, checkout, plant, run

ADAPTERS = Path(__file__).resolve().parent / "fixtures" / "adapters"
BOX = ("bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp", "--unshare-pid", "--proc", "/proc")
NONE = "gc: no eligible artifacts\n"
CONFIG = """[defaults]
orchestrator = "one"
workers = ["one", "two"]

[models.one]
harness = "echo"
model = "echo-1"
effort = "high"
provider = "test"

[models.two]
harness = "echo"
model = "echo-2"
effort = "high"
provider = "test"

[providers.test]
mode = "subscription"

[audit]
on = false
"""


@contextlib.contextmanager
def directory_lock(path):
    """Hold an exclusive flock on directory `path` until the block ends."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def gc_cmd(home, *args, timeout=30):
    return home.run(*home.box(BOX), AK, "run", "gc", *args, env=ROOM, timeout=timeout)


@unittest.skipUnless(boxable() and REAL_TMUX, "no bwrap or tmux installed")
class ConfigFreeDuringCleanup(unittest.TestCase):
    def test_a_config_save_completes_while_a_cleanup_pass_is_held_open(self):
        with Home() as home:
            home.env["AGENTKIT_ADAPTER_DIR"] = str(ADAPTERS)
            cfg_path = home.write(".agentkit/config.toml", CONFIG)
            (home.path / "code").mkdir()
            session = home.write(".grok/sessions/%2Fcode%2Facme/grok-old/summary.json",
                                 "{}\n", ago=40 * DAY).parent
            started = home.root / "grok-started"
            release = home.root / "grok-release"
            home.fake("grok", (
                "#!/bin/sh\n"
                f"printf 'held\\n' > {shlex.quote(str(started))}\n"
                "i=0\n"
                f"while [ ! -e {shlex.quote(str(release))} ] && [ $i -lt 1200 ]; do\n"
                "    sleep 0.05\n"
                "    i=$((i + 1))\n"
                "done\n"
                'rm -r "$GROK_HOME"/sessions/*/"$3"\n'
            ))
            ak_dir = home.path / ".agentkit"
            state_dir = ak_dir / "state"
            ak_before = sorted(p.name for p in ak_dir.iterdir())
            state_before = sorted(p.name for p in state_dir.iterdir())
            proc = home._popen([*home.box(BOX), AK, "run", "gc"], env=ROOM, cwd=home.path,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 30
                while not started.exists():
                    if proc.poll() is not None:
                        out, err = proc.communicate()
                        self.fail(f"cleanup pass exited before reaching candidate: {out}{err}")
                    self.assertLess(time.monotonic(), deadline,
                                    "cleanup pass never reached candidate removal")
                    time.sleep(0.05)

                # While the pass holds its lock, no lock file was created, a second pass sees
                # it busy, and a config write from another process completes without waiting.
                self.assertEqual(sorted(p.name for p in ak_dir.iterdir()), ak_before)
                self.assertEqual(sorted(p.name for p in state_dir.iterdir()), state_before)

                busy = gc_cmd(home, timeout=15)
                self.assertEqual(busy, (0, NONE, ""))
                self.assertIsNone(proc.poll())

                saved = home.ak("orch", "demo", "--model", "two", "--workers", "one",
                                tty=True, cwd=home.path / "code", timeout=15)
                self.assertEqual(saved.code, 0, saved.out + saved.err)
                self.assertEqual(tomllib.loads(cfg_path.read_text())["defaults"],
                                 {"orchestrator": "two", "workers": ["one"]})
                self.assertIsNone(proc.poll(), "cleanup pass ended before being released")
            finally:
                release.write_text("go\n")
                if proc.poll() is None:
                    try:
                        out, err = proc.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.communicate()
                        raise
                else:
                    out, err = proc.communicate()

            self.assertEqual(proc.returncode, 0, out + err)
            self.assertIn(f"gc: remove conversation {session}", out)
            self.assertFalse(session.exists())


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class ConfigTmpAndStateLock(unittest.TestCase):
    def test_a_week_old_config_tmp_at_homes_top_stays_off_the_plan_and_untouched(self):
        with Home() as home:
            ak_dir = home.path / ".agentkit"
            # Directories, because utime cannot backdate a regular file's ctime; home_entries
            # checks config.OWN by name first, so an aged entry proves config.tmp is owned.
            tmp = plant(ak_dir / "config.tmp", 10)
            stray = plant(ak_dir / "stray-notes", 10)

            dry = gc_cmd(home, "--dry-run")
            self.assertEqual((dry.code, dry.err), (0, ""))
            self.assertIn(f"gc: would remove home-entry {stray}:", dry.out)
            self.assertNotIn(str(tmp), dry.out)

            done = gc_cmd(home)
            self.assertEqual((done.code, done.err), (0, ""))
            self.assertFalse(stray.exists())
            self.assertTrue(tmp.is_dir())

    def test_passes_lock_state_not_home(self):
        with Home() as home:
            ak_dir = home.path / ".agentkit"
            merged = checkout(home, "acme-merged")
            run(home, "acme-merged", 1, state="pass", merged=True, worktree=str(merged))
            stray = plant(ak_dir / "stray-notes", 10)

            # Holding the state directory lock keeps both sweep and gc out.
            with directory_lock(ak_dir / "state"):
                self.assertEqual(gc_cmd(home), (0, NONE, ""))
                self.assertTrue(merged.is_dir())
                self.assertTrue(stray.is_dir())

            # Holding the home directory lock (config._config_lock's lock) blocks neither.
            with directory_lock(ak_dir):
                done = gc_cmd(home)
                self.assertEqual((done.code, done.err), (0, ""))
                self.assertFalse(merged.exists())
                self.assertFalse(stray.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
