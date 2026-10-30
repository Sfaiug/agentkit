"""A click on a meter lists what it offers, as Enter on it over `c` does (test_meter_acts.py),
and `↻ log in again` on an amber one hands the terminal to that login's `login again`, the ak
screen back as soon as it ends, the meter grey once the login it made stands; Esc on the list
signs nothing in.  `menu.loop` in-process, its keys and picks scripted, with a fake Claude adapter
whose `login again` makes a login 30 days out, or fails where $FAKE/fail exists.
"""

from contextlib import redirect_stdout
import io
import json
import os
import sys
import unittest
from unittest.mock import Mock, patch

from fixtures.sandbox import Sandbox
from fixtures.subscriptions import number
from agentkit import config, logins, menu, terminal

DAY = 86400
WEEK = {"name": "weekly", "resets_at": 10000 + 3 * DAY, "window_secs": 604800, "used": 50}
ADAPTER = r"""#!/usr/bin/env bash
case "$*" in
  "login again") echo "again ${AGENTKIT_ACCOUNT:-default}" >>"$FAKE/calls"
                 [ ! -e "$FAKE/fail" ] || exit 1
                 cp "$FAKE/renewed" "$FAKE/standing" ;;
  login-end) cat "$FAKE/standing" ;;
  *) exit 2 ;;
esac
"""


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
            "anthropic": {"meters": [WEEK], "resets": 1}, "openai": {"meters": [WEEK]}}}))
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
        self.stack.enter_context(patch.object(terminal, "Keyboard",
                                              return_value=Mock(**{"take.return_value": True})))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))

    def click(self, drawn, label):
        """A click on the middle of `label`'s cell in the grid as `drawn`."""
        cell = ("usage", number(self.cfg, label))
        return next(terminal.Key("click", col=(first + last) // 2, row=row)
                    for row, (_, places, *_) in drawn["spots"].items()
                    for first, last, at in places if at == cell)

    def signed_in(self):
        """The meters amber on the last screen drawn, and the login kept, as the owner clicks
        the grey meter, which lists nothing, then the amber one and picks `↻ log in again`,
        then Esc."""
        draws, amber, offered = [], [], []
        real = menu.draw

        def draw(*args, **kwargs):
            draws.append(args[5])         # what the screen drew, read back as the loop does
            amber.append([number for number, note in enumerate(
                menu.login_notes(menu.usage_rows(args[0])), 1) if note])
            return real(*args, **kwargs)
        script = iter([lambda: self.click(draws[-1], "ChatGPT"),   # grey: no login ends soon
                       lambda: self.click(draws[-1], "Claude"),    # amber: it ends in 2 days
                       lambda: terminal.Key("esc")])
        picks = iter(["↻ log in again"])
        with patch.object(menu, "draw", side_effect=draw), \
                patch.object(menu, "moving", side_effect=lambda *a, **k: next(script)()), \
                patch.object(terminal, "choose", side_effect=lambda choices, **_kw:
                             offered.append(choices) or next(picks)), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        self.assertEqual(offered, [["↻ log in again", "↻ spend a reset"]])
        calls = self.fake / "calls"
        self.assertEqual(calls.read_text() if calls.exists() else "", "again default\n")
        self.assertEqual(len(draws), 3)   # the screen came back by itself before Esc left it
        return amber[-1], logins.read()["anthropic"]["default"]

    def test_a_click_on_the_amber_meter_comes_back_with_it_grey(self):
        amber, kept = self.signed_in()
        self.assertEqual(amber, [])                 # no meter amber, before any tick asked
        self.assertEqual(kept["ends"], 10000 + 30 * DAY)

    def test_a_login_that_failed_leaves_its_meter_amber(self):
        (self.fake / "fail").touch()
        amber, kept = self.signed_in()
        self.assertEqual(amber, [number(self.cfg, "Claude")])
        self.assertEqual(kept["ends"], 10000 + 2 * DAY)


if __name__ == "__main__":
    unittest.main()
