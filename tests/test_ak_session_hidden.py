"""A tmux session named `_ak` on ak's own server is never a seat.

The Go port keeps one hidden control session there, `_ak` (`orch.CONTROL`), and talks to tmux
through it: no listing counts it, no sweep closes it, and no seat may be named after it.  Only
that exact name: `_akx` and `ak` stay seats.  tmux, `ps` and `/proc` are fakes answering as tmux
3.5a and Linux do; no real process is read.
"""

import os
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, guard, orch, statusbar

LOOP = ["bash", "-c", "while :; do sleep 60; done"]
NOW = 1_800_000_000


class ControlSessionHidden(Sandbox):
    def setUp(self):
        super().setUp()
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "acme.toml").write_text('[launch]\nprograms = ["acme-bin-*"]\n')
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        self.stack.enter_context(patch.object(orch.time, "time", return_value=NOW))
        # name: (session id, mark, [(pid, dead, dead time)]); each runs an agent unless told
        self.sessions = {}
        self.table = {}
        self.calls = []
        self.add("_ak", "$0", [(100, "0", "")])
        self.add("_akx", "$1", [(101, "0", "")])
        self.add("ak", "$2", [(102, "0", "")])
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        real = subprocess.run

        def run(argv, *args, **kwargs):
            if list(argv[:1]) != ["ps"]:
                return real(argv, *args, **kwargs)
            return subprocess.CompletedProcess(argv, 0, "\n".join(
                f"{pid} {parent} {' '.join(words)}" for pid, (parent, words) in self.table.items()))

        self.stack.enter_context(patch.object(orch.subprocess, "run", side_effect=run))
        read_bytes = Path.read_bytes
        self.stack.enter_context(patch.object(
            Path, "read_bytes", lambda path: b"AK_RUN_ROLE=seat\0"
            if str(path).startswith("/proc/") else read_bytes(path)))
        orch._PROCESSES.clear()
        self.addCleanup(orch._PROCESSES.clear)

    def add(self, name, sid, panes, mark="", words=("acme",)):
        self.sessions[name] = (sid, mark, panes)
        for pid, _, _ in panes:
            self.table[pid] = (1, list(words))

    def tmux(self, *args, **_kw):
        self.calls.append(args)
        if args[0] in ("list-sessions", "list-panes"):
            rows = [({"session_id": sid, "session_name": name, orch.MARK: mark,
                      "session_path": str(self.root), "session_created": "100",
                      "session_attached": "0", "pane_id": f"%{pid}", "pane_pid": str(pid),
                      "pane_dead": dead, "pane_dead_time": when})
                    for name, (sid, mark, panes) in self.sessions.items()
                    for pid, dead, when in (panes[:1] if args[0] == "list-sessions" else panes)]
            return 0, "\n".join(re.sub(r"#\{([^}]*)\}", lambda field: row.get(field[1], ""),
                                       args[args.index("-F") + 1]) for row in rows)
        if args[0] == "show-environment":
            return 1, f"unknown variable: {guard.TMUX_OWNER}"
        return 0, ""

    def test_no_listing_counts_it(self):
        self.assertEqual([s["name"] for s in orch.server_sessions(None, False, False)],
                         ["_akx", "ak"])
        self.assertEqual(orch.held_names(), {"_akx", "ak"})
        self.assertEqual([name for _, name, _ in statusbar.sessions()], ["_akx", "ak"])

    def test_the_seat_guard_does_not_list_it(self):
        def run(argv, **_kw):
            rc, out = self.tmux(*argv[3:])
            return subprocess.CompletedProcess(argv, rc, out, "")

        with patch.object(guard.subprocess, "run", side_effect=run):
            self.assertEqual(guard.sessions("tmux", ["-L", "agentkit-test"]),
                             {"$1": "_akx", "$2": "ak"})

    def test_no_agent_in_it_makes_it_no_stranger(self):
        for name in ("_ak", "_akx"):
            self.add(name, self.sessions[name][0], self.sessions[name][2], words=LOOP)
        self.assertEqual(orch.agentless(None, {"_ak", "_akx", "ak"}), {"_akx"})

    def test_it_is_never_dead_or_swept(self):
        for name in ("_ak", "_akx"):
            self.add(name, self.sessions[name][0], [(int(self.sessions[name][0][1:]) + 200,
                                                     "1", str(NOW - 2 * 86400))])
        self.assertEqual(orch.dead(None), {"_akx"})
        orch.sweep_finished({}, print)
        asked = [call[2] for call in self.calls if call[0] == "show-environment"]
        self.assertEqual(asked, ["$1", "$2"])   # each other is asked whose it is; `_ak` never

    def test_no_seat_takes_its_name(self):
        for raw in ("_ak", " _AK "):
            self.assertEqual(orch.session_name(raw), "")
        self.assertEqual(orch.session_name("_akx"), "_akx")
        self.assertEqual(orch.session_name("ak"), "ak")
        with self.assertRaisesRegex(config.Error, "needs a name"):
            orch.create({}, "_ak", self.root)


if __name__ == "__main__":
    unittest.main()
