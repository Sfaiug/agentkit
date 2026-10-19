"""Every seat's bar is drawn by the live install as it is now, and an open menu starts again on
new code: ak from another checkout than ~/agentkit, or a process older than the install, writes
no bar, where a worktree's menu wrote its own design over the live one's and every bar flipped
between the two (the owner's report of 19 Oct 2026).  Offline: a temporary HOME, tmux faked.
"""

import io
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, menu, statusbar, terminal

OPTION = ("=fix-api:", "@ak_top", "working")


class Keyboard:
    """A terminal the menu has taken."""
    take = give = close = lambda self: True


class BarsFromLiveCode(Sandbox):
    def told(self):
        """Whether one bar option written now reaches tmux."""
        with patch.object(statusbar, "sessions", return_value=[]), \
                patch.object(statusbar, "seats", return_value=[]), \
                patch.object(statusbar.orch, "tmux_options") as tmux:
            statusbar._tell(own=[OPTION])
        return tmux.called

    def test_only_the_live_checkout_as_it_is_now_writes_a_bar(self):
        self.assertTrue(self.told())                     # no live checkout here: a sandbox
        live = config.Path.home() / "agentkit"
        live.symlink_to(config.REPO)
        self.assertTrue(self.told())                     # the live checkout itself
        live.unlink()
        live.mkdir()
        self.assertFalse(self.told())                    # another checkout: a worktree's ak
        live.rmdir()
        (config.STATE / "installed-at").write_text(str(int(config.STARTED) + 5))
        self.assertFalse(self.told())                    # installed since this process began

    def test_an_install_while_a_bar_waits_for_its_lock_stops_it(self):
        def flock(*_a):                                  # the install lands while it waits
            (config.STATE / "installed-at").write_text(str(int(config.STARTED) + 5))
        with patch.object(statusbar.fcntl, "flock", flock):
            self.assertFalse(self.told())

    def test_the_menus_own_update_says_how_it_went_before_new_code_restarts_it(self):
        said, inbox = [], []
        def update_first(live, updates):                 # install.sh stamps, then it reports
            inbox.append(updates)
            updates.append({"progress": 2 / 3})
            (config.STATE / "installed-at").write_text(str(int(config.STARTED) + 5))
        steps = [None, "result", terminal.Key("esc")]
        def moving(*_a, **_kw):                          # a wait, the result, then Esc
            step = steps.pop(0)
            if step == "result":
                inbox[0].append({"moved": False, "lines": ["install.sh failed"]})
                return None
            return step
        with patch.object(menu, "Live", **{"return_value.heard.return_value": [],
                                           "return_value.asking.return_value": None}), \
                patch.object(terminal, "Keyboard", Keyboard), \
                patch.object(terminal, "sense", lambda: None), \
                patch.object(menu, "update_first", update_first), \
                patch.object(menu, "moving", moving), \
                patch.object(menu, "show_notices", said.extend), \
                patch.object(menu.os, "execve", lambda *_a: said.append("restart")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg), 0)
        self.assertEqual(said, ["install.sh failed", "restart"])

    def test_an_open_menu_starts_again_once_new_code_is_installed_under_it(self):
        def restarts():
            with patch.object(menu, "Live", **{"return_value.heard.return_value": [],
                                               "return_value.asking.return_value": None}), \
                    patch.object(menu, "wait_key", return_value=terminal.Key("esc")), \
                    patch.object(terminal, "Keyboard", Keyboard), \
                    patch.object(terminal, "sense", lambda: None), \
                    patch.object(menu.os, "execve") as restart, redirect_stdout(io.StringIO()):
                self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
            return restart.call_count
        self.assertEqual(restarts(), 0)
        (config.STATE / "installed-at").write_text(str(int(config.STARTED) + 5))
        self.assertEqual(restarts(), 1)


if __name__ == "__main__":
    unittest.main()
