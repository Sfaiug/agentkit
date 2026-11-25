"""A click on a meter on the ak screen opens its row on Subscriptions, lit on `→ log in again`
where its login ends soon and on nothing else, and Enter there hands the terminal to that
login's `login again`, the ak screen back from the page with the meter grey once the login it
made stands.  `menu.loop` in-process, its keys scripted, with a fake Claude adapter whose
`login again` makes a login 30 days out, or fails where $FAKE/fail exists.
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
                    for first, last, at, *_ in places if at == cell)

    def signed_in(self):
        """The meters amber on the last screen drawn, and the login kept, as the owner clicks
        the grey meter and goes back from its row, then clicks the amber one and presses Enter
        on its row, then goes back and leaves."""
        draws, amber, opened = [], [], []
        real, page = menu.draw, menu.matrix_key

        def draw(*args, **kwargs):
            draws.append(args[5])         # what the screen drew, read back as the loop does
            amber.append([number for number, (note, *_) in enumerate(
                menu.login_notes(menu.usage_rows(args[0])), 1) if note])
            return real(*args, **kwargs)

        def matrix_key(title, body, places, rows, here, top, said, keys, **kwargs):
            # the row it is on, the acts on its line and what Enter does
            acts = [act.strip(" []") for line in body
                    for act in terminal.plain(line, spaced=True).split("   ")
                    if act.strip(" [")[:1] in ("→", "−")]
            opened.append((title, here, acts, keys))
            return page(title, body, places, rows, here, top, said, keys, **kwargs)
        script = iter([lambda: self.click(draws[-1], "ChatGPT"),   # grey: no login ends soon
                       lambda: terminal.Key("esc"),                # back from its row
                       lambda: self.click(draws[-1], "Claude"),    # amber: it ends in 2 days
                       lambda: terminal.Key("enter"), lambda: terminal.Key("esc"),
                       lambda: terminal.Key("esc")])

        def key(*_a, **_kw):          # the ak screen's, and Subscriptions'
            return next(script)()
        with patch.object(menu, "draw", side_effect=draw), \
                patch.object(menu, "matrix_key", side_effect=matrix_key), \
                patch.object(menu, "moving", side_effect=key), \
                patch.object(terminal, "read_key", side_effect=key), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        page = "config · subscriptions"
        self.assertEqual(opened[:2], [
            (page, ("sub", number(self.cfg, "ChatGPT")), ["− remove"],
             terminal.keys("esc back", enter=None)),
            (page, ("sub", number(self.cfg, "Claude")),
             ["→ log in again", "→ spend a reset", "− remove"],
             terminal.keys("esc back", enter="log in again"))])
        calls = self.fake / "calls"
        self.assertEqual(calls.read_text() if calls.exists() else "", "again default\n")
        self.assertEqual(len(draws), 3)   # the ak screen, and back from each row it opened
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
