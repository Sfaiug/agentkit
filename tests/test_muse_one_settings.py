"""Muse logins share user settings while keeping their credentials apart.

Muse Code 1.4.7 (1.4.7-R6101.1) was checked in a temporary HOME: `muse skills
disable acme --scope user`, `enable`, and the TUI's /theme picker changed
settings.json through a symlink without replacing it (the link's inode stayed
the same). This offline fake reads that same path; no real Muse, login or session
is reached here.
"""

from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
FAKE_MUSE = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path

home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "muse"
print(json.dumps({"payload": {"kind": "run_terminal", "text": json.dumps({
    "settings": json.loads((home / "settings.json").read_text()),
    "login": (home / "auth.json").read_text(),
})}}))
'''

PAUSED_JQ = r'''#!/usr/bin/env python3
import os
import subprocess
import sys

result = subprocess.run([os.environ["REAL_JQ"], *sys.argv[1:]],
                        stdin=sys.stdin, capture_output=True)
if sys.argv[1] == "-s" and "SETTINGS_READY" in os.environ:
    os.write(int(os.environ["SETTINGS_READY"]), b"1")
    os.read(int(os.environ["SETTINGS_RESUME"]), 1)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
'''


class MuseOneSettings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-muse-settings-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        binary = self.bin / "muse"
        binary.write_text(FAKE_MUSE)
        binary.chmod(0o755)
        self.usual = self.root / ".config/muse/settings.json"
        self.own = self.root / ".muse-second/muse/settings.json"
        self.rules = self.root / "rules.md"
        self.rules.write_text("Do the task.\n")
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("AGENTKIT_", "AK_", "XDG_", "MUSE_", "TBH_"))
                    and key != "META_API_KEY"}
        self.env.update(HOME=str(self.root), PATH=f"{self.bin}:{os.environ['PATH']}",
                        AGENTKIT_RULEBOOK=str(self.rules))
        for path, login in [(self.usual, "usual"), (self.own, "second")]:
            path.parent.mkdir(parents=True)
            (path.parent / "auth.json").write_text(login)
            (path.parent / "trust.json").write_text(login + "-trust")

    def save(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, **data}))

    def adapter(self, account="second", interactive=False, pass_fds=(), **env):
        args = (["interactive", "acme", "high"] if interactive else
                ["run", "acme", "high", str(self.root), str(self.rules),
                 str(self.root / "out")])
        return subprocess.run([str(REPO / "adapters/muse.sh"), *args],
                              env={**self.env, "AGENTKIT_ACCOUNT": account, **env},
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=20, pass_fds=pass_fds)

    def turn(self, account="second", **env):
        proc = self.adapter(account, **env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads((self.root / "out/final.md").read_text())

    def test_first_launch_merges_login_only_values_and_usual_values_win(self):
        self.save(self.usual, {"tui": {"terminal_background": "dark"},
                               "notifications": False, "auto_memory": None})
        self.save(self.own, {"tui": {"terminal_background": "light", "voice": True},
                             "notifications": True, "auto_memory": True,
                             "runtime_capabilities": {"observer": False}})
        private = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                   for parent in [self.usual.parent, self.own.parent]
                   for p in [parent / "auth.json", parent / "trust.json"]}
        result = self.turn()
        self.assertTrue(self.own.is_symlink())
        self.assertEqual(self.own.resolve(), self.usual)
        expected = {"schema_version": 1,
                    "tui": {"terminal_background": "dark", "voice": True},
                    "notifications": False, "auto_memory": None,
                    "runtime_capabilities": {"observer": False}}
        self.assertEqual(result, {"settings": expected, "login": "second"})
        self.assertEqual(json.loads(self.usual.read_text()), expected)
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in private}, private)

        # A write through either login is what every subsequent worker and seat reads.
        self.save(self.own, {"tui": {"terminal_background": "light"}})
        self.assertEqual(self.turn(account="")["settings"]["tui"]["terminal_background"],
                         "light")
        third = self.root / ".muse-third/muse/settings.json"
        third.parent.mkdir(parents=True)
        (third.parent / "auth.json").write_text("third")
        self.turn(account="third")
        self.assertTrue(third.is_symlink())
        self.save(self.usual, {"tui": {"terminal_background": "dark"}})
        self.assertEqual(self.turn()["settings"]["tui"]["terminal_background"], "dark")
        self.assertEqual(json.loads(third.read_text()), json.loads(self.usual.read_text()))

    def test_a_seat_imports_settings_when_the_usual_file_is_absent(self):
        self.save(self.own, {"tui": {"terminal_background": "light"}})
        proc = self.adapter(interactive=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.own.is_symlink())
        self.assertEqual(self.own.resolve(), self.usual)
        self.assertEqual(json.loads(self.usual.read_text())["tui"]["terminal_background"],
                         "light")

    def test_simultaneous_first_launches_keep_both_logins_settings_under_muses_lock(self):
        self.save(self.usual, {})
        self.save(self.own, {"from_second": True})
        third = self.root / ".muse-third/muse/settings.json"
        self.save(third, {"from_third": True})
        self.env["REAL_JQ"] = shutil.which("jq", path=self.env["PATH"])
        jq = self.bin / "jq"
        jq.write_text(PAUSED_JQ)
        jq.chmod(0o755)
        ready, announce = os.pipe()
        resume, proceed = os.pipe()
        for fd in (ready, announce, resume, proceed):
            self.addCleanup(os.close, fd)
        lock = self.usual.parent / ".settings.json.lock"
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.adapter, interactive=True,
                                pass_fds=(announce, resume), SETTINGS_READY=str(announce),
                                SETTINGS_RESUME=str(resume))
            try:
                self.assertTrue(select.select([ready], [], [], 10)[0],
                                "first launch never read the settings")
                self.assertEqual(os.read(ready, 1), b"1")
                second = pool.submit(self.adapter, account="third", interactive=True)
                with lock.open("a") as held:
                    try:
                        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        # Without a lock, force the competing merge to finish before the
                        # paused launch writes its older snapshot: deterministic data loss.
                        fcntl.flock(held, fcntl.LOCK_UN)
                        result = second.result(timeout=25)
                        self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                os.write(proceed, b"1")
            for future in (first, second):
                result = future.result(timeout=25)
                self.assertEqual(result.returncode, 0, result.stderr)
        for path in (self.usual, self.own, third):
            self.assertEqual(json.loads(path.read_text()),
                             {"schema_version": 1, "from_second": True, "from_third": True})
        for path in (self.own, third):
            shared_lock = path.parent / ".settings.json.lock"
            self.assertTrue(shared_lock.is_symlink())
            self.assertEqual(shared_lock.resolve(), lock)

    def test_empty_logins_get_valid_settings_and_relaunch_keeps_the_link(self):
        self.assertEqual(self.turn()["settings"], {"schema_version": 1})
        link = self.own.lstat().st_ino
        before = (self.usual.read_bytes(), self.usual.stat().st_mtime_ns)
        self.turn()
        self.assertTrue(self.own.is_symlink())
        self.assertEqual(self.own.lstat().st_ino, link)
        self.assertEqual((self.usual.read_bytes(), self.usual.stat().st_mtime_ns), before)

    def test_usual_launch_leaves_its_settings_as_they_are(self):
        self.save(self.usual, {"tui": {"terminal_background": "dark"}})
        before = (self.usual.read_bytes(), self.usual.stat().st_mtime_ns)
        self.turn(account="")
        self.assertFalse(self.usual.is_symlink())
        self.assertEqual((self.usual.read_bytes(), self.usual.stat().st_mtime_ns), before)

    def test_preparing_a_named_login_leaves_unchanged_usual_settings_in_place(self):
        self.save(self.usual, {"tui": {"terminal_background": "dark"}})
        self.save(self.own, {"tui": {"terminal_background": "light"}})
        before = (self.usual.read_bytes(), self.usual.stat().st_mtime_ns,
                  self.usual.stat().st_ino)
        self.turn()
        self.assertTrue(self.own.is_symlink())
        self.assertFalse(self.usual.is_symlink())
        self.assertEqual((self.usual.read_bytes(), self.usual.stat().st_mtime_ns,
                          self.usual.stat().st_ino), before)

    def test_custom_config_home_and_an_inherited_named_home(self):
        custom = self.root / "custom/muse/settings.json"
        self.save(custom, {"tui": {"terminal_background": "light"}})
        self.turn(XDG_CONFIG_HOME=str(custom.parent.parent))
        self.assertEqual(self.own.resolve(), custom)
        # A worker launched by another named login still shares the usual config.
        self.turn(XDG_CONFIG_HOME=str(self.root / ".muse-other"))
        self.assertEqual(self.own.resolve(), self.usual)

    def test_invalid_settings_refuse_migration_without_losing_either_file(self):
        self.save(self.usual, {"tui": {"terminal_background": "dark"}})
        self.own.write_text("{broken")
        before = (self.usual.read_bytes(), self.own.read_bytes())
        proc = self.adapter()
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(self.own.is_symlink())
        self.assertEqual((self.usual.read_bytes(), self.own.read_bytes()), before)
        self.save(self.own, {"tui": {"terminal_background": "light"}})
        self.usual.write_text("[]")
        before = (self.usual.read_bytes(), self.own.read_bytes())
        proc = self.adapter()
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(self.own.is_symlink())
        self.assertEqual((self.usual.read_bytes(), self.own.read_bytes()), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
