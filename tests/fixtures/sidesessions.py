"""A tick over ak's side sessions, on a fake tmux and a temporary HOME.

`SideSessions.add` puts a session on the fake, tagged by the seat that started it; `tick` runs
the tick's retention pass; `closed` lists the sessions it closed and `messages` what it logged.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from agentkit import config, gc, guard, orch, watch

NOW = 1_800_000_000


def expand(text, fields, windows):
    """The fake's tmux formats: variables, comparisons and window/pane loops."""
    while "#{" in text:
        start = text.index("#{")
        depth, end = 1, start + 2
        while depth:
            depth += (text[end:end + 2] == "#{") - (text[end] == "}")
            end += 2 if text[end:end + 2] == "#{" else 1
        word = text[start + 2:end - 1]
        op, _, body = word.partition(":")
        if op == "W":
            value = "".join(expand(body, fields, [window]) for window in windows)
        elif op == "P":
            value = "".join(expand(body, {**fields, **pane}, []) for pane in windows[0])
        elif op in ("==", "!=", "&&"):
            left, right = expand(body, fields, windows).split(",", 1)
            value = str(int({"==": left == right, "!=": left != right,
                             "&&": left not in ("", "0") and right not in ("", "0")}[op]))
        else:
            value = fields.get(word, "")
        text = text[:start] + value + text[end:]
    return text


class SideSessions(unittest.TestCase):
    """A tick over a fake tmux's tagged sessions (`add`): `acme`'s by default, a recorded seat."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-finished-tmux-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.enterContext(patch.dict(os.environ, {"HOME": str(self.root),
                          "AGENTKIT_SESSION": "acme", "AK_RUN_ROLE": "",
                          "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        for key in ("STATE", "TMP", "RUNS"):
            path = self.root / ".agentkit" / key.lower()
            path.mkdir(parents=True)
            self.enterContext(patch.object(config, key, path))
        self.enterContext(patch.object(orch.time, "time", return_value=NOW))
        self.enterContext(patch.object(orch, "sessions", return_value=[]))
        self.enterContext(patch.object(orch, "records", return_value={}))
        self.enterContext(patch.object(orch, "tmux_out", side_effect=self.tmux))
        config.session_path("acme").write_text("{}")
        self.sessions, self.owners, self.closed, self.messages = {}, {}, [], []
        self.capture_error, self.after_capture = False, lambda: None

    def add(self, sid, name, ages=(25 * 3600,), owner="acme", mark=""):
        # A format reads the session's own tag, else the server's environment, which holds one
        # when a process in a tagged pane started the server: only show-environment tells.
        fields = {"session_id": sid, "session_name": name, guard.TMUX_OWNER: owner or "acme",
                  orch.MARK: mark}
        windows = [[{"pane_id": f"%{len(self.sessions) * 10 + i}",
                     "pane_dead": "0" if age is None else "1",
                     "pane_dead_time": "" if age is None else str(NOW - age)}]
                   for i, age in enumerate(ages)]
        self.sessions[sid] = fields, windows
        self.owners[sid] = owner

    def tmux(self, *args, **kw):
        self.assertIn(kw.get("socket", orch.socket_name()), (None, "agentkit-test"))
        if ";" in args:                 # tmux skips the rest of a list after a failed command
            rc, out = self.tmux(*args[:args.index(";")], **kw)
            return (rc, out) if rc else self.tmux(*args[args.index(";") + 1:], **kw)
        if args[0] == "list-panes":
            return 0, "\n".join(expand(args[-1], {**fields, **pane}, windows)
                                 for fields, windows in self.sessions.values()
                                 for window in windows for pane in window)
        if args[:2] == ("show-environment", "-t") and args[3:] == (guard.TMUX_OWNER,):
            owner = self.owners[args[2]]
            return (0, f"{guard.TMUX_OWNER}={owner}") if owner else \
                (1, f"unknown variable: {guard.TMUX_OWNER}")
        if args[0] == "list-sessions":
            return 0, "\n".join(expand(args[-1], fields, windows)
                                 for fields, windows in self.sessions.values())
        if args[:2] == ("has-session", "-t"):     # `=$1` is session $1 to tmux
            if args[2].removeprefix("=") in self.sessions:
                return 0, ""
            return 1, f"can't find session: {args[2].removeprefix('=')}"
        if args[0] == "if-shell":
            sid = args[args.index("-t") + 1]
            fields, windows = self.sessions[sid]
            if expand(args[-2], fields, windows) == "1":
                self.assertEqual(args[-1], f"kill-session -t '{sid}'")
                self.assertTrue(any(config.TMP.glob("tmux-*.txt")))
                self.closed.append(sid)
                del self.sessions[sid]
            return 0, ""
        self.fail(f"unexpected tmux call: {args}")

    def capture(self, args, *, stdout, **_kw):
        self.assertEqual(args[-4:-1], ["capture-pane", "-p", "-t"])
        self.assertEqual(args[1:3], ["-L", "agentkit-test"])
        self.assertNotIn("TMUX", _kw["env"])
        self.after_capture()
        stdout.write(f"  last screen {args[-1]}  \n\n")
        return subprocess.CompletedProcess(args, int(self.capture_error))

    def tick(self):
        with patch.object(gc, "schedule_gc"), patch.object(orch, "stamp"), \
                patch.object(orch.subprocess, "run", side_effect=self.capture):
            for why, call, dry in watch.local_passes({}, False, self.messages.append):
                if why in ("collection", "exit clocks", "seat sweep"):
                    self.assertFalse(dry)
                    call()
