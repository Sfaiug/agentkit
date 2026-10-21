"""install.sh points the phone's key at `ak attach`, undoes its old links and merges yolo defaults.

The phone reaches the server through one authorized_keys line, tagged `phone-termius`, whose
forced command is the whole session that key can have: install.sh adds it once or repoints it,
touches no other key and leaves the file as sshd demands it, mode 600.  An older install linked
the rulebook over the owner's ~/.claude/CLAUDE.md; that link goes and the owner's newest backup
comes back, while a link that is not ak's stays.  Claude and Codex settings get ak's yolo
defaults merged in, everything the owner set kept.  Black-box: install.sh of the checkout
`AK_BIN` names runs from outside in a Home of tests/fixtures/akbin.py, the host's tools the
refusing fakes of tests/fixtures/installer.py.
"""

import json
import os
import sys
from pathlib import Path
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import Home

LAPTOP = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAacmelaptop laptop\n"
OLD = ('command="ak orch",no-pty ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAacmeold phone-termius\n'
       "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAacmebare phone-termius\n")
PHONE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAacmephone acme@phone"
ATTACH = 'command="ak attach",no-agent-forwarding,no-port-forwarding'
CODEX = ('model = "acme-model"\napproval_policy = "on-request"  # the owner\'s\n\n'
         '[projects."/srv/acme"]\ntrust_level = "trusted"\n')
CLAUDE = {"model": "acme-model", "env": {"ACME": "1"},
          "permissions": {"allow": ["Bash(ls:*)"], "defaultMode": "default"}}


def home_with(case):
    case.home = Home()
    case.addClassCleanup(case.home.close)
    installer.prepare(case.home)
    return case.home


def installed(home, *args):
    done = installer.run(home, *args)
    assert done.code == 0, done.out + done.err
    return done


class PhoneKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = home_with(cls)
        cls.keys = home.write(".ssh/authorized_keys", LAPTOP + OLD)
        cls.keys.chmod(0o644)
        installed(home)
        cls.repointed = cls.keys.read_text()
        cls.backups = [path.read_text() for path in cls.keys.parent.glob("authorized_keys.bak-*")]
        installed(home, "--phone-key", str(home.write("phone.pub", PHONE + "\n")))
        installed(home, "--phone-key", PHONE)
        cls.refused = installer.run(home, "--phone-key", "acme phone key")

    def test_an_existing_phone_line_is_pointed_at_ak_attach_and_no_other_key_is_touched(self):
        self.assertEqual(self.repointed, LAPTOP
                         + 'command="ak attach",no-pty ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAacmeold'
                           ' phone-termius\n'
                         + 'command="ak attach" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAacmebare'
                           ' phone-termius\n')
        self.assertEqual(self.backups, [LAPTOP + OLD])

    def test_a_new_phone_key_is_appended_once_with_the_forced_command(self):
        self.assertEqual(self.keys.read_text(), self.repointed
                         + f"{ATTACH} ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAacmephone"
                           " phone-termius\n")

    def test_the_file_is_mode_600(self):
        self.assertEqual(self.keys.stat().st_mode & 0o777, 0o600)

    def test_what_is_not_a_public_key_is_refused_with_exit_2(self):
        self.assertEqual(self.refused.code, 2, self.refused.out + self.refused.err)
        self.assertIn("--phone-key", self.refused.err)


class OldLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = home_with(cls)
        cls.claude_md = home.path / ".claude/CLAUDE.md"
        cls.agents_md = home.path / ".codex/AGENTS.md"
        home.write(".claude/CLAUDE.md.bak-20250101", "older\n")
        home.write(".claude/CLAUDE.md.bak-20250601", "newest\n")
        cls.claude_md.symlink_to(os.path.relpath(installer.CHECKOUT / "AGENTS.md",
                                                 cls.claude_md.parent))
        cls.agents_md.parent.mkdir()
        cls.agents_md.symlink_to(installer.CHECKOUT / "orchestrator.md")
        installed(home)
        cls.agents_gone = not os.path.lexists(cls.agents_md)
        cls.agents_md.symlink_to(home.write("notes.md", "the owner's notes\n"))
        installed(home)

    def test_a_link_into_the_checkout_goes_and_the_newest_backup_comes_back(self):
        self.assertFalse(self.claude_md.is_symlink())
        self.assertEqual(self.claude_md.read_text(), "newest\n")
        self.assertEqual(sorted(path.name for path in self.claude_md.parent.glob("CLAUDE.md*")),
                         ["CLAUDE.md", "CLAUDE.md.bak-20250101"])
        self.assertTrue(self.agents_gone)

    def test_a_link_that_is_not_ak_s_is_left_alone(self):
        self.assertEqual(os.readlink(self.agents_md), str(self.home.path / "notes.md"))


class YoloDefaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = home_with(cls)
        home.write(".claude/settings.json", CLAUDE)
        home.write(".codex/config.toml", CODEX)
        installed(home)
        cls.claude = json.loads((home.path / ".claude/settings.json").read_text())
        cls.codex = (home.path / ".codex/config.toml").read_text()

    def test_claude_settings_get_bypass_and_no_autoupdate_with_the_owner_s_kept(self):
        self.assertEqual({key: self.claude.get(key) for key in (
            "model", "permissions", "skipDangerousModePermissionPrompt", "env")}, {
            "model": "acme-model", "skipDangerousModePermissionPrompt": True,
            "permissions": {"allow": ["Bash(ls:*)"], "defaultMode": "bypassPermissions"},
            "env": {"ACME": "1", "DISABLE_AUTOUPDATER": "1"}})

    def test_codex_gets_never_ask_and_full_access_at_top_level_with_the_owner_s_kept(self):
        config = tomllib.loads(self.codex)
        self.assertEqual({key: config.get(key) for key in (
            "model", "approval_policy", "sandbox_mode", "check_for_update_on_startup")}, {
            "model": "acme-model", "approval_policy": "never",
            "sandbox_mode": "danger-full-access", "check_for_update_on_startup": False})
        self.assertEqual(config["projects"], {"/srv/acme": {"trust_level": "trusted"}})
        self.assertIn('approval_policy = "never"  # the owner\'s\n', self.codex)


if __name__ == "__main__":
    unittest.main()
