"""install.sh makes a home ready for ak: private state, the owner's config kept, ak on PATH.

Every host is made by install.sh, and the menu's update runs it again, so a second run must
change nothing an owner wrote: the shipped config is copied only where there is none, the PATH
line goes in once, above the early return of a non-interactive bashrc (`ssh host ak` reads only
what is above it), and of the per-command links earlier versions left only ak's own go.  A HOME
not the account's own is a sandbox, where no package, harness login or cron is touched; a
client records the server it reaches.  Black-box: install.sh of the checkout `AK_BIN` names
runs from outside in a Home of tests/fixtures/akbin.py, the host's tools the refusing fakes of
tests/fixtures/installer.py.
"""

import os
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import Home

BASHRC = ("# the owner's bashrc\ncase $- in\n    *i*) ;;\n      *) return;;\nesac\n"
          "alias ll='ls -l'\n")
HARNESSES = ("claude", "codex", "muse", "grok", "opencode", "agy")
SETUP = {"login", "auth", "install", "setup-token", "update"}


class FreshServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        installer.prepare(home)
        cls.ak_dir = home.path / ".agentkit"
        (cls.ak_dir / "config.toml").unlink()
        cls.ak_dir.chmod(0o755)
        home.write(".bashrc", BASHRC)
        cls.bin = home.path / ".local" / "bin"
        cls.bin.mkdir(parents=True)
        for script in ("tools/notify", "other/bin/ak", "other/bin/orch", ".local/bin/worker"):
            home.write(script, "#!/bin/sh\n")
        links = {"run": installer.CHECKOUT / "bin/run",           # ak's own
                 "usage": home.path / "old-checkout/bin/usage",    # dangling at */bin/usage
                 "orch": home.path / "other/bin/orch",             # in a bin/ that holds ak
                 "notify": home.path / "tools/notify"}             # the owner's own
        for name, target in links.items():
            (cls.bin / name).symlink_to(target)
        cls.before = int(time.time())
        cls.first = installer.run(home)
        cls.shipped = (cls.ak_dir / "config.toml").read_text()
        cls.shipped_mode = (cls.ak_dir / "config.toml").stat().st_mode & 0o777
        (cls.ak_dir / "config.toml").write_text("# the owner's own\nmax_runs = 2\n")
        cls.second = installer.run(home)

    def test_both_runs_succeed(self):
        for done in (self.first, self.second):
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_sandbox_home_installs_no_package_harness_login_or_cron(self):
        for tool in ("sudo", "apt-get", "brew", "npm", "dpkg", "curl", "tailscale", "crontab",
                     "systemctl", "launchctl", "gh"):
            self.assertEqual(self.home.calls(tool), [], tool)
        for harness in HARNESSES:
            asked = [call for call in self.home.calls(harness) if SETUP & set(call)]
            self.assertEqual(asked, [], harness)

    def test_ak_s_state_directories_are_private(self):
        for name in ("", "state", "secrets", "tmp", "env", "runs", "wt", "work"):
            with self.subTest(name or ".agentkit"):
                self.assertEqual((self.ak_dir / name).stat().st_mode & 0o777, 0o700)

    def test_the_shipped_config_is_copied_once_and_never_written_over(self):
        self.assertEqual(self.shipped, (installer.CHECKOUT / "config.default.toml").read_text())
        self.assertEqual(self.shipped_mode, 0o600)
        self.assertEqual((self.ak_dir / "config.toml").read_text(),
                         "# the owner's own\nmax_runs = 2\n")

    def test_ak_on_path_is_a_link_to_the_program(self):
        self.assertEqual(os.readlink(self.bin / "ak"), str(installer.CHECKOUT / "bin" / "ak"))

    def test_only_the_old_per_command_links_that_were_ak_s_go(self):
        self.assertEqual(sorted(path.name for path in self.bin.iterdir()),
                         ["ak", "notify", "worker"])
        self.assertEqual(os.readlink(self.bin / "notify"), str(self.home.path / "tools/notify"))

    def test_the_path_line_sits_once_above_the_bashrc_s_early_return(self):
        text = (self.home.path / ".bashrc").read_text()
        lines = text.splitlines()
        exports = [i for i, line in enumerate(lines)
                   if line.startswith("export PATH=") and "$HOME/.local/bin" in line]
        self.assertEqual(len(exports), 1, text)
        self.assertLess(exports[0], lines.index("      *) return;;"))
        self.assertIn(BASHRC, text)
        # what `ssh host ak` gets: a shell that is not interactive and reads the bashrc
        found = self.home.run("bash", "-c", '. "$HOME/.bashrc"; command -v ak')
        self.assertEqual(found.out, f"{self.bin / 'ak'}\n", found.err)
        profile = (self.home.path / ".profile").read_text()
        self.assertEqual(profile.count("$HOME/.local/bin"), 1, profile)

    def test_a_server_records_when_it_was_installed(self):
        stamp = (self.ak_dir / "state" / "installed-at").read_text()
        self.assertRegex(stamp, r"^\d+\n$")
        self.assertLessEqual(self.before, int(stamp))
        self.assertTrue((self.home.path / "code").is_dir())


class Roles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        installer.prepare(cls.home)
        cls.server = cls.home.path / ".agentkit" / "state" / "server"

    def installed(self, *args):
        done = installer.run(self.home, *args)
        self.assertEqual(done.code, 0, done.out + done.err)
        return self.server.read_text() if self.server.exists() else None

    def test_a_client_records_the_alias_it_reaches_and_a_server_removes_it(self):
        self.assertEqual(self.installed("--client", "acme-box"), "acme-box\n")
        self.assertEqual(self.installed(), "acme-box\n")      # remembered
        self.assertEqual(self.installed("--client"), "agentkit\n")
        self.assertIsNone(self.installed("--server"))
        self.assertEqual(self.home.calls("crontab"), [])

    def test_an_unknown_option_or_a_phone_key_with_none_is_refused_with_exit_2(self):
        for args in (("--acme",), ("--phone-key",)):
            with self.subTest(args=args):
                done = installer.run(self.home, *args)
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertEqual(done.out, "")
                self.assertIn(args[0], done.err)


if __name__ == "__main__":
    unittest.main()
