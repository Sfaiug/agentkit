"""A tick from any checkout but ~/agentkit leaves ~/agentkit alone; `ak update` moves it from
anywhere.

~/agentkit is the host's live install, and the tick that runs from it fast-forwards it to
origin/main and reinstalls it soon after a merge.  Every other checkout -- a seat's worktree, a
test's above all -- runs the same tick: if that moved ~/agentkit too, trying a change to the
tick would pull and reinstall the live ak under every seat.  `ak update` is a person's own
command, and it fast-forwards ~/agentkit whichever checkout it runs from.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py; HOME/agentkit is a
clone of a bare origin on disk (tests/fixtures/gitrig.py) that is one commit ahead of it.
"""

import os
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REFUSED, SYSTEM, Home
from fixtures.gitrig import Rig

HARNESSES = ("claude", "codex", "muse", "grok", "opencode", "agy")
# The tick asks the public boards and the shared browser, and fetches the checkout it runs
# from: a test reaches none of them.
OFFLINE = {"https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
           "GIT_ALLOW_PROTOCOL": "file"}
# What reinstalling ran, and from which commit, kept outside the checkout so it stays clean.
INSTALL = '#!/bin/sh\ngit -C "${0%/*}" rev-parse HEAD >>"$HOME/install.log"\n'


def no_harness_path(home):
    """The Home's PATH with no harness anywhere on it, not even a refusing fake: `ak update`
    upgrades every harness it finds, and its gate makes real model calls."""
    tools = home.root / "tools"
    tools.mkdir()
    for directory in (str(Path(sys.executable).parent), *SYSTEM):
        for entry in os.scandir(directory) if os.path.isdir(directory) else ():
            if (entry.name not in REFUSED and not (tools / entry.name).exists()
                    and entry.is_file() and os.access(entry.path, os.X_OK)):
                (tools / entry.name).symlink_to(entry.path)
    for name in HARNESSES:
        (home.bin / name).unlink()
    return os.pathsep.join([str(home.bin), str(tools)])


class UpdateOtherCheckout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env.update(OFFLINE, PATH=no_harness_path(home))
        akconfig.write(home, ["opus", "astra"])
        rig = Rig(home, "agentkit", files={"install.sh": INSTALL})
        (rig.path / "install.sh").chmod(0o755)
        cls.installed = rig.commit({}, "install.sh runs")
        cls.live = home.path / "agentkit"
        home.run("git", "clone", "-q", str(rig.bare), str(cls.live))
        cls.ahead = rig.commit({"NEWS": "one more\n"}, "one ahead")
        cls.tick = home.ak("watch")
        cls.after_tick = (cls.head(), cls.leftovers())
        cls.update = home.ak("update")
        cls.after_update = (cls.head(), cls.leftovers())

    @classmethod
    def head(cls):
        return cls.home.run("git", "-C", str(cls.live), "rev-parse", "HEAD").out.strip()

    @classmethod
    def leftovers(cls):
        """What a move of ~/agentkit leaves: the reinstalls run, and the marks of one half
        done or of its live checks."""
        state = cls.home.path / ".agentkit/state"
        try:
            ran = (cls.home.path / "install.log").read_text().split()
        except FileNotFoundError:
            ran = []
        return ran, sorted(name for name in ("agentkit-install-pending", "live-checks")
                           if (state / name).exists())

    def test_a_tick_from_another_checkout_leaves_agentkit_where_it_is(self):
        self.assertEqual(self.tick.code, 0, self.tick.out + self.tick.err)
        self.assertNotEqual(self.installed, self.ahead)
        self.assertEqual(self.after_tick, (self.installed, ([], [])))

    def test_ak_update_from_another_checkout_fast_forwards_agentkit_and_reinstalls_it(self):
        self.assertEqual(self.update.code, 0, self.update.out + self.update.err)
        self.assertEqual(self.after_update, (self.ahead, ([self.ahead], [])))


if __name__ == "__main__":
    unittest.main()
