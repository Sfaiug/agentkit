"""A click on an amber meter -- a login ending within a week -- hands the terminal to that
login's `login again`, and the ak screen is back as soon as it ends, however it did, with no
key to press; the login is asked again off the screen, which the tick may hold up, and its meter
is no longer amber once a new login stands.  A click on any other meter signs nothing in.

`menu.loop` in-process on a taken keyboard, its keys scripted, in a temporary HOME whose
Claude adapter is a fake: `login again` writes down its call and a login 30 days out, and
`login-end` answers whichever login stands.  Nothing here logs in or reads a real login.
"""

from contextlib import closing, redirect_stdout
import io
import json
import os
import sys
import threading
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from fixtures.subscriptions import number
from agentkit import config, logins, menu, terminal

DAY = 86400
WEEK = {"name": "weekly", "resets_at": 10000 + 3 * DAY, "window_secs": 604800, "used": 50}
ADAPTER = r"""#!/usr/bin/env bash
case "$*" in
  "login again") echo "again ${AGENTKIT_ACCOUNT:-default}" >>"$FAKE/calls"
                 cp "$FAKE/renewed" "$FAKE/standing" ;;
  login-end) cat "$FAKE/standing" ;;
  *) exit 2 ;;
esac
"""


class Keyboard:
    def __init__(self, **_kw):
        pass

    def take(self):
        return True

    def give(self):
        pass

    def close(self):
        pass


class Screen(io.StringIO):
    """The terminal the menu draws on; `drawn()` is called as each frame goes out."""

    def __init__(self, drawn=lambda: None):
        super().__init__()
        self.drawn = drawn

    def isatty(self):
        return True

    def write(self, text):
        written = super().write(text)
        if text.startswith("\033[H"):
            self.drawn()
        return written


class LoginClick(Sandbox):
    def setUp(self):
        super().setUp()
        self.fake = self.root / "fake"
        self.fake.mkdir()
        (self.fake / "claude.sh").write_text(ADAPTER)
        (self.fake / "claude.sh").chmod(0o755)
        soon = {"email": "owner@acme.test", "ends": 10000 + 2 * DAY}
        (self.fake / "standing").write_text(json.dumps(soon))
        (self.fake / "renewed").write_text(json.dumps({**soon, "ends": 10000 + 30 * DAY}))
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [WEEK]}, "openai": {"meters": [WEEK]}}}))
        (config.STATE / "logins.json").write_text(json.dumps(
            {"anthropic": {"default": {**soon, "checked_at": 10000}}}))
        self.stack.enter_context(patch.dict(os.environ, {
            "FAKE": str(self.fake), config.ADAPTER_DIR_ENV: str(self.fake)}))
        for target, name, value in ((menu.orch, "listing", []), (menu.orch, "job_notices", []),
                                    (menu.Live, "probe", False), (sys.stdin, "isatty", True)):
            self.stack.enter_context(patch.object(target, name, return_value=value))
        self.stack.enter_context(patch.object(menu.usage, "collect", return_value={}))
        for target, name in ((menu.Live, "watch"), (terminal, "sense")):
            self.stack.enter_context(patch.object(target, name))
        self.stack.enter_context(patch.object(terminal, "Keyboard", Keyboard))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))
        self.draws, real = [], menu.draw

        def draw(*args, **kwargs):
            self.draws.append(args[5])        # what the screen drew, read back as the loop does
            return real(*args, **kwargs)
        self.stack.enter_context(patch.object(menu, "draw", side_effect=draw))

    def click(self, drawn, label):
        """A click on the middle of `label`'s cell in the grid as `drawn`."""
        cell = ("usage", number(self.cfg, label))
        return next(terminal.Key("click", col=(first + last) // 2, row=row)
                    for row, (_, places) in drawn["spots"].items()
                    for first, last, at in places if at == cell)

    def loop(self, *keys, screen=None):
        """`menu.loop` until Esc, each of `keys()` read in turn after a draw."""
        script = iter([*keys, lambda: terminal.Key("esc")])
        with patch.object(menu, "moving", side_effect=lambda *a, **k: next(script)()), \
                redirect_stdout(screen or Screen()):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)

    def sign_in(self, *labels):
        """Each of `labels`' meters clicked in turn, then the screen drawn again once the login
        read the last click started has landed: whether that read found the screen back before
        it went on.  It waits for that, as one waits while the tick asks other logins."""
        waited, back, landed, real = [], threading.Event(), threading.Event(), logins.refresh

        def refresh(*args, **kwargs):
            waited.append(back.wait(10))
            try:
                return real(*args, **kwargs)
            finally:
                landed.set()

        def landing():
            back.set()
            self.assertTrue(landed.wait(10))
            return None          # drawn again, as the watcher has it once logins.json changes
        with patch.object(logins, "refresh", side_effect=refresh):
            self.loop(*(lambda label=label: self.click(self.draws[-1], label) for label in labels),
                      landing)
        return waited

    def test_a_click_on_the_amber_meter_signs_in_and_comes_back(self):
        # grey: no login ends soon; amber: it ends in 2 days
        self.assertEqual(self.sign_in("ChatGPT", "Claude"), [True])
        calls = self.fake / "calls"
        self.assertEqual(calls.read_text() if calls.exists() else "", "again default\n")
        kept = json.loads((config.STATE / "logins.json").read_text())["anthropic"]["default"]
        self.assertEqual(kept["ends"], 10000 + 30 * DAY)
        # back before the read landed, and drawn again once it had with no meter amber
        self.assertEqual(len(self.draws), 4)
        self.assertEqual(self.draws[-1]["logins"], {})
        with closing(menu.Live(self.cfg)) as live:
            self.assertIn("logins.json", [entry[0] for entry in live.recorded()])

    def test_a_login_that_fails_comes_back_at_once_its_meter_still_amber(self):
        (self.fake / "claude.sh").write_text("#!/bin/sh\nexit 1\n")
        with patch.object(menu, "read", side_effect=AssertionError("a key was waited for")):
            self.assertEqual(self.sign_in("Claude"), [True])
        self.assertEqual(list(self.draws[-1]["logins"].values()), [("anthropic", None)])

    def test_a_click_signs_in_only_what_the_screen_drew_amber(self):
        login = config.STATE / "logins.json"
        ending = login.read_text()
        login.write_text(json.dumps({"anthropic": {"default": {
            "email": "owner@acme.test", "ends": 10000 + 30 * DAY, "checked_at": 10000}}}))
        # the tick writes a login ending soon as the first frame, drawn grey, goes out
        tick = [lambda: login.write_text(ending)]
        self.loop(lambda: self.click(self.draws[-1], "Claude"),
                  screen=Screen(lambda: tick and tick.pop()()))
        self.assertFalse((self.fake / "calls").exists())


if __name__ == "__main__":
    unittest.main()
