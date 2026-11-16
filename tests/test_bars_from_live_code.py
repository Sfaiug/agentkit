"""Every seat's bar is drawn by the live install as it is now, and an open menu starts again on
new code, its highlight on the seat or subscription it was on: ak from another checkout than
~/agentkit, or a process older than the install, writes no bar, where a worktree's menu wrote
its own design over the live one's and every bar flipped between the two (the owner's report of
19 Oct 2026).  Offline: a temporary HOME, tmux faked.
"""

import copy
import io
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, menu, statusbar, terminal

OPTION = ("=fix-api:", "@ak_top", "working")


class Keyboard:
    """A terminal the menu has taken."""
    take = give = close = lambda self, **_kw: True


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
        steps = [None, "result", None, terminal.Key("esc")]
        def moving(*_a, **_kw):                          # a wait, the result, a wait, then Esc
            step = steps.pop(0)
            if step == "result":
                inbox[0].append({"moved": False, "lines": ["install.sh failed"]})
                return None
            return step
        with patch.object(menu, "Live", **{"return_value.heard.return_value": [],
                                           "return_value.stuck.return_value": ""}), \
                patch.object(terminal, "Keyboard", Keyboard), \
                patch.object(terminal, "sense", lambda: None), \
                patch.object(menu, "update_first", update_first), \
                patch.object(menu, "moving", moving), \
                patch.object(menu, "show_notices", said.extend), \
                patch.object(menu.os, "execve", lambda *_a: said.append("restart")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg), 0)
        self.assertEqual(said, ["install.sh failed", "restart"])

    def test_a_menu_whose_own_update_never_starts_still_restarts_on_new_code(self):
        stamp = config.STATE / "installed-at"
        for live in (False, True):                       # no live checkout; its updater refused
            with self.subTest(live=live):
                if live:
                    (config.Path.home() / "agentkit").symlink_to(config.REPO)
                stamp.unlink(missing_ok=True)
                steps, notices = [None, None, terminal.Key("esc")], []
                def moving(*_a, **_kw):                  # the tick installs after the first frame
                    stamp.write_text(str(int(config.STARTED) + 5))
                    return steps.pop(0)
                with patch.object(menu, "Live", **{"return_value.heard.return_value": [],
                                                   "return_value.stuck.return_value": ""}), \
                        patch.object(terminal, "Keyboard", Keyboard), \
                        patch.object(terminal, "sense", lambda: None), \
                        patch.object(menu, "moving", moving), \
                        patch.object(menu, "show_notices", notices.extend), \
                        patch.object(menu.subprocess, "Popen", side_effect=OSError("no fork")), \
                        patch.object(menu.os, "execve", side_effect=SystemExit) as restart, \
                        redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                    menu.loop(self.cfg)                  # an exec does not come back
                self.assertEqual(restart.call_count, 1)
                self.assertEqual(notices, ["update: no fork"] if live else [])

    def test_an_open_menu_starts_again_once_new_code_is_installed_under_it(self):
        def restarts():
            with patch.object(menu, "Live", **{"return_value.heard.return_value": [],
                                               "return_value.stuck.return_value": ""}), \
                    patch.object(menu, "wait_key", side_effect=[None, terminal.Key("esc")]), \
                    patch.object(terminal, "Keyboard", Keyboard), \
                    patch.object(terminal, "sense", lambda: None), \
                    patch.object(menu.os, "execve") as restart, redirect_stdout(io.StringIO()):
                self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
            return restart.call_count
        self.assertEqual(restarts(), 0)
        (config.STATE / "installed-at").write_text(str(int(config.STARTED) + 5))
        self.assertEqual(restarts(), 1)

    def test_new_code_comes_up_on_the_meter_the_old_left(self):
        (config.STATE / "installed-at").write_text(str(int(config.STARTED) + 5))
        handed = {}
        def restart(_program, _argv, env):
            handed.update(env)
            raise SystemExit
        def opened(cfg, env, *keys):     # the highlight of the last draw before the keys ran out
            with patch.object(menu, "Live", **{"return_value.heard.return_value": [],
                                               "return_value.cfg": cfg}), \
                    patch.object(menu, "moving", side_effect=[*keys, terminal.Key("esc")]), \
                    patch.object(terminal, "Keyboard", Keyboard), \
                    patch.object(terminal, "sense", lambda: None), \
                    patch.dict(menu.os.environ, env), \
                    patch.object(menu.os, "execve", side_effect=restart), \
                    patch.object(menu, "draw", wraps=menu.draw) as draw, \
                    redirect_stdout(io.StringIO()):
                try:
                    menu.loop(cfg, dry_run=True)
                except SystemExit:
                    pass
            meter = draw.call_args.args[5]["cursor"]
            return menu.subscription(menu.usage_rows(cfg)[meter[1] - 1])
        # ↑ off the first row onto the last meter, whose number another process's new
        # subscription, read only by the new code, gives to the one before it
        left = opened(self.cfg, {}, terminal.Key("up"), None)
        moved = copy.deepcopy(self.cfg)
        moved["providers"]["anthropic"]["accounts"] = ["default", "tide"]
        self.assertEqual(opened(moved, {"AK_MENU_CURSOR": handed["AK_MENU_CURSOR"]}), left)
        # as an open menu on the code before hands it on, its meter's number
        last = str(len(menu.usage_rows(self.cfg)))
        self.assertEqual(opened(self.cfg, {"AK_MENU_CURSOR": "", "AK_MENU_METER": last}), left)


if __name__ == "__main__":
    unittest.main()
