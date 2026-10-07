"""A seat shows as soon as tmux has it: its pane marks it, binds itself and dresses the bars.

Offline: a fake tmux that records what it is asked, and a harness adapter that writes down
each command it builds.  The pane's boot runs here, as the pane runs it (`fixtures.pane`).
"""

import io
import os
from contextlib import redirect_stderr
import shlex
import unittest
from unittest.mock import patch

from fixtures import pane
from fixtures.sandbox import Sandbox
from agentkit import config, menu, orch, statusbar

ADAPTER = '''#!/bin/sh
[ "$1" = interactive ] || exit 97
[ -n "${AK_TEST_REFUSE:-}" ] && { echo "acme login expired" >&2; exit 1; }
if [ "${5:-}" = new ]; then echo "claude --session-id $4"
elif [ -n "${4:-}" ]; then echo "claude --resume $4"
else echo claude; fi
'''


class SeatShowsAtOnce(Sandbox):
    def setUp(self):
        super().setUp()
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "claude.sh").write_text(ADAPTER)
        (adapters / "claude.sh").chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.dress = self.stack.enter_context(patch.object(statusbar, "dress"))
        self.calls = []

    def tmux(self, *args, **_kw):
        self.calls.append(args)
        return 0, ""

    def test_the_owner_waits_on_tmux_alone_for_a_new_seat(self):
        # the menu checked the name as it was typed; tmux is asked whether it holds it now,
        # and starts the seat: no bar is dressed and no option set before the pane is there
        self.assertTrue(orch.create(self.cfg, "acme", self.root, taken={"other"},
                                    selection=({}, ("opus", "chosen", ["opus"]))))
        self.assertEqual([args[0] for args in self.calls], ["list-sessions", "source-file", "-f"])
        self.dress.assert_not_called()
        # its pane then marks the seat ours, keeps it past its harness, binds itself, dresses
        # the bars, and runs the harness on the conversation the record names
        launched = self.calls[-1]
        self.calls = []
        runs = shlex.split(pane.resolved(launched)[-1])
        self.assertEqual(self.calls, [
            ("set-option", "-t", "=acme:", orch.MARK, "1"),
            ("set-option", "-t", "=acme:", "remain-on-exit", "on"),
            ("set-option", "-F", "-t", "=acme:", orch.PANE_OPTION, "#{pane_id}")])
        self.dress.assert_called_once_with("acme", "opus")
        self.assertEqual(runs[-2:], ["--session-id", config.session_records()["acme"]["conversation"]])

    def test_a_start_that_fails_touches_nothing_of_the_seat_it_would_replace(self):
        # a seat tmux lost, its record, its open plan and the question it left
        config.save_session(self.cfg, "acme", "opus", ["opus"], {"cwd": str(self.root),
                                                                 "created": 1})
        config.plan_path("acme").write_text("- [ ] ship the acme fix\n")
        config.notify_path("acme").write_text('{"kind": "question", "summary": "merge acme?"}\n')
        before = config.session_records()["acme"]
        with patch.dict(os.environ, {"AK_TEST_REFUSE": "1"}), \
                self.assertRaisesRegex(config.Error, "acme login expired"):
            orch.create(self.cfg, "acme", self.root, taken=set(),
                        selection=({}, ("opus", "chosen", ["opus"])))
        self.assertEqual([args[0] for args in self.calls], ["list-sessions"])
        self.assertEqual(config.session_records()["acme"], before)
        self.assertEqual(config.plan_path("acme").read_text(), "- [ ] ship the acme fix\n")
        self.assertIn("merge acme?", config.notify_path("acme").read_text())

    def test_a_harness_that_cannot_run_says_so_in_its_pane(self):
        said = io.StringIO()
        with redirect_stderr(said):
            request = orch.booting("acme", "opus", [str(self.root / "no-such-harness")],
                                   orch.socket_name(), "=acme:")[-1]
            self.assertEqual(orch.boot([request]), 1)
        self.assertIn("acme did not start: cannot run", said.getvalue())
        # the pane stays with those words: it was kept past its harness first
        self.assertIn(("set-option", "-t", "=acme:", "remain-on-exit", "on"), self.calls)
        self.assertNotEqual(menu.state({"name": "acme", "path": str(self.root), "created": 1,
                                        "attached": True, "exited": True, "legacy": False}),
                            "working")

    def test_opening_a_listed_seat_asks_tmux_only_to_switch_to_it(self):
        listed = {"name": "acme", "path": str(self.root), "created": 1, "attached": False,
                  "exited": False, "legacy": False}
        with patch.dict(os.environ, {"TMUX": f"/tmp/tmux-1/{orch.socket_name()},1,0"}), \
                patch.object(orch.sys.stdin, "isatty", return_value=True), \
                patch.object(orch.sys.stdout, "isatty", return_value=True), \
                patch.object(orch, "seen_by_user"):
            self.assertEqual(orch.attach("acme", wait=True, session=listed), 0)
        self.assertEqual(self.calls, [("switch-client", "-t", "=acme")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
