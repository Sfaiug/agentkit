"""`ak standby ALIAS` copies, before ak's folder and at the same paths, what a seat carrying on from
the copy needs of each harness: its logins, every account's, and the folders its conversations are
in.  One pass copies the usual login, a second account's and a conversation each of Claude Code and
Codex, and the next removes a conversation the home deleted.  A harness's settings and its install
on the home do not come, this machine's own stay as they were, and so does a login the home lacks.
A pass that cannot read a conversation on the home fails and leaves ak's folder here as it was.  A
link here at a harness's folder, or an account's, refuses the pass, which then changes nothing.
Black-box, through tests/fixtures/twohomes.py.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

CONVERSATION = ".codex/sessions/2026/11/14/rollout-2026-11-14T07-36-00-7c0ffee.jsonl"
# The home's, which a pass copies: the usual login, a second account's, and a conversation each of
# Claude Code and Codex.
COPIED = (".claude/.credentials.json", ".claude-acme-second/.credentials.json",
          ".claude/projects/-home-acme-code-api/7c0ffee.jsonl", CONVERSATION)
# Each machine's own: a harness's settings, an account's, and Claude Code's install.
OWN = (".claude/settings.json", ".claude-acme-second/settings.json",
       ".local/share/claude/versions/2.1.316")
THEIRS = (*OWN, ".codex/config.toml")     # the home's, with settings this machine has none of
LOGIN = ".codex-acme-second/auth.json"    # this machine's, a login the home lacks
STATE = ".agentkit/state/watch.json"      # the home's, in ak's folder


def files(machine, paths):
    """Each of `paths` under `machine`'s HOME with its bytes, or None where it is no file."""
    tree = machine.tree()
    return {path: tree.get(path) for path in paths}


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassCopiesLoginsAndConversations(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        for path in (*COPIED, *THEIRS, STATE):
            home.write(path, f"the home's {path}")
        for path in (*OWN, LOGIN):
            here.write(path, f"this machine's {path}")

    def standby(self):
        done = self.here.ak("standby", self.home.name)
        self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_pass_copies_logins_and_conversations_and_the_next_what_the_home_deleted(self):
        self.standby()
        self.assertEqual(files(self.here, COPIED), files(self.home, COPIED))
        (self.home.path / CONVERSATION).unlink()
        self.standby()
        self.assertEqual(files(self.here, COPIED), files(self.home, COPIED))
        self.assertNotIn(CONVERSATION, self.here.tree())

    def test_a_harnesss_settings_install_and_a_login_the_home_lacks_stay_this_machines(self):
        before = files(self.here, (*THEIRS, LOGIN))
        self.standby()
        self.assertEqual(files(self.here, (*THEIRS, LOGIN)), before)

    def test_a_pass_that_cannot_read_a_conversation_fails_and_leaves_aks_folder(self):
        home, here = self.home, self.here
        (home.path / CONVERSATION).chmod(0)
        before = {path: data for path, data in here.copy().items() if path.startswith(".agentkit")}
        done = here.ak("standby", home.name)
        self.assertNotEqual(done.code, 0)
        self.assertIn(f"the pass from {home.name} failed", done.err)
        self.assertEqual({path: data for path, data in here.copy().items()
                          if path.startswith(".agentkit")}, before)

    def test_a_link_here_at_a_harnesss_folder_refuses_the_pass(self):
        home, here = self.home, self.here
        for name in (".claude", ".claude-acme-second"):
            with self.subTest(link=name):
                linked, aside = here.path / name, here.path / "dotfiles" / name
                aside.parent.mkdir(exist_ok=True)
                linked.rename(aside)
                linked.symlink_to(os.path.relpath(aside, linked.parent))
                before = here.tree()
                done = here.ak("standby", home.name)
                self.assertNotEqual(done.code, 0)
                self.assertIn(f"refused: ~/{name} is a link here", done.err)
                self.assertEqual(here.tree(), before)
                linked.unlink()
                aside.rename(linked)


if __name__ == "__main__":
    unittest.main()
