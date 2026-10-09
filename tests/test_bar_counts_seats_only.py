"""A tmux session with no agent in it is on no seat's bar, from the moment it starts.

An orchestrator's watcher -- `tmux new-session -d -s acme-watch '<a loop>'` on ak's own server
-- is nobody's seat: no bar counts it, whatever word a record under its name says, and a
session started since the process table was last read is judged by what it runs, never taken
for a seat until the next reading.  tmux, `ps` and `/proc` are fakes here: no real process is
read.
"""

import os
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch, statusbar, watch
from agentkit.guard import commands

LOOP = ["bash", "-c", "while :; do sleep 60; done"]   # the watcher: no agent under it
PANES = "#{session_name}\t#{pane_pid}\t#{pane_dead}"


def drawn(value):
    """An option's text as tmux draws it: styles dropped, the doubled `#` single."""
    return re.sub(r"#\[[^\]]*\]", "", value).replace("##", "#")


class NoAgentNoSeat(Sandbox):
    def setUp(self):
        super().setUp()
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "acme.toml").write_text('[launch]\nprograms = ["acme-bin-*"]\n')
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", config.ADAPTER_DIR_ENV: str(adapters)}))
        # the seat ak opened carries its mark; every other session here is somebody's `tmux new`
        self.sessions = {"fix-api": ("$0", "1")}
        self.panes = {"fix-api": [101]}
        self.table = {101: (1, ["acme"])}
        self.readings, self.options = 0, {}
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        real = subprocess.run

        def run(argv, *args, **kwargs):
            if list(argv[:1]) != ["ps"]:
                return real(argv, *args, **kwargs)
            self.readings += 1
            return subprocess.CompletedProcess(argv, 0, "\n".join(
                f"{pid} {parent} {' '.join(words)}" for pid, (parent, words) in self.table.items()))

        self.stack.enter_context(patch.object(orch.subprocess, "run", side_effect=run))
        read_bytes = Path.read_bytes
        self.stack.enter_context(patch.object(
            Path, "read_bytes", lambda path: b"AK_RUN_ROLE=seat\0"
            if str(path).startswith("/proc/") else read_bytes(path)))
        orch._PROCESSES.clear()
        self.addCleanup(orch._PROCESSES.clear)
        watch.seat_write("fix-api", word="working", reason="", word_since=None)

    def tmux(self, *args, **_kw):
        if args[:2] == ("list-sessions", "-F"):   # each field it was asked for, and no other
            return 0, "\n".join("\t".join(
                {"#{session_id}": sid, "#{session_name}": name, f"#{{{orch.MARK}}}": mark,
                 "#{session_path}": str(self.root), "#{session_created}": "100",
                 "#{session_attached}": "0"}[field] for field in args[2].split("\t"))
                for name, (sid, mark) in self.sessions.items())
        if args[:3] == ("list-panes", "-a", "-F"):
            if args[3] == PANES:
                return 0, "\n".join(f"{name}\t{pid}\t0" for name, pids in self.panes.items()
                                    for pid in pids)
            return 0, "\n".join(f"{name}\t0" for name in self.panes)
        for command in commands(args):       # a command list, as tmux takes one
            if command[0] == "set-option":   # each seat's own options, by its exact target
                self.options.setdefault(command[2][1:-1], {})[command[3]] = command[-1]
        return 0, ""

    def start(self, name, pid, words):
        """Somebody's `tmux new-session -d -s <name> <words>`: no mark and no record."""
        self.sessions[name] = (f"${len(self.sessions)}", "")
        self.panes[name] = [pid]
        self.table[pid] = (1, words)

    def held(self):
        return [session["name"] for session in orch.server_sessions(None, False, False)]

    def test_a_watcher_started_since_the_reading_is_no_seat(self):
        with orch.one_reading():
            orch.processes()                 # the reading every later ask shares
            self.start("acme-watch", 201, LOOP)
            self.assertEqual(self.held(), ["fix-api"])
            self.assertEqual(self.readings, 2)   # read again for the pane it had not seen,
            self.assertEqual(self.held(), ["fix-api"])
            self.assertEqual(self.readings, 2)   # and that reading answers from here on

    def test_an_agent_started_since_the_reading_is_a_seat_at_once(self):
        with orch.one_reading():
            orch.processes()
            self.start("by-hand", 301, ["acme"])
            self.assertEqual(self.held(), ["fix-api", "by-hand"])

    def test_a_pane_whose_process_has_ended_makes_no_seat(self):
        self.start("acme-watch", 201, LOOP)
        del self.table[201]                  # tmux still names the pane; `ps` has it no more
        self.assertEqual(self.held(), ["fix-api"])

    def test_no_bar_counts_a_watcher_whatever_its_record_says(self):
        self.start("acme-watch", 201, LOOP)
        self.start("by-hand", 301, ["acme"])
        # the word a watcher was given while it was taken for a seat, and a seat's own
        for name in ("acme-watch", "by-hand"):
            watch.seat_write(name, word="needs you", reason="waiting for you", word_since=None)
        self.assertEqual(statusbar.seats(), [("$0", "fix-api", "working"),
                                             ("$2", "by-hand", "needs you")])
        statusbar.dress("fix-api", "opus")
        self.assertEqual(drawn(self.options["fix-api"][statusbar.SEATS]), "! by-hand needs you ")
        self.assertEqual(drawn(self.options["by-hand"][statusbar.SEATS]), "● 1 working ")
        self.assertNotIn("acme-watch", self.options)     # and no bar is written on it either


if __name__ == "__main__":
    unittest.main(verbosity=2)
