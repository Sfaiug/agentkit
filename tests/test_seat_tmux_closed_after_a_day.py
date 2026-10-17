"""A seat's finished auxiliary tmux sessions keep their screens, then close after a day.

Offline: the shim calls an argv recorder; the tick sees a fake tmux and a temporary HOME.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
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


class FinishedTmux(unittest.TestCase):
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
        self.sessions, self.closed, self.messages = {}, [], []
        self.capture_error, self.after_capture = False, lambda: None

    def add(self, sid, name, ages=(25 * 3600,), owner="acme", mark=""):
        fields = {"session_id": sid, "session_name": name, guard.TMUX_OWNER: owner,
                  orch.MARK: mark}
        windows = [[{"pane_id": f"%{len(self.sessions) * 10 + i}",
                     "pane_dead": "0" if age is None else "1",
                     "pane_dead_time": "" if age is None else str(NOW - age)}]
                   for i, age in enumerate(ages)]
        self.sessions[sid] = fields, windows

    def tmux(self, *args, **kw):
        self.assertIn(kw.get("socket", orch.socket_name()), (None, "agentkit-test"))
        if args[0] == "list-panes":
            return 0, "\n".join(expand(args[-1], {**fields, **pane}, windows)
                                 for fields, windows in self.sessions.values()
                                 for window in windows for pane in window)
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
                if why == "retention pass did not finish":
                    self.assertFalse(dry)
                    call()

    def test_the_tick_saves_and_closes_only_tagged_sessions_dead_for_a_day(self):
        self.add("$1", "old")
        self.add("$2", "recent", (3600,))
        self.add("$3", "running", (25 * 3600, None))
        self.add("$4", "by-hand", owner="")
        self.add("$5", "marked-seat", mark="1")
        self.add("$6", "recorded-seat")
        config.session_path("recorded-seat").write_text("{}")
        self.add("$7", "mixed", (25 * 3600, 3600))
        self.add("$8", "several-windows", (25 * 3600, 26 * 3600))
        self.add("$9", "boundary", (86400,))
        self.tick()
        self.assertEqual(self.closed, ["$1", "$8", "$9"])
        saved = list(config.TMP.glob("tmux-*.txt"))
        self.assertEqual(len(saved), 3)
        screens = "".join(path.read_text() for path in saved)
        for pane in ("%0", "%70", "%71", "%80"):
            self.assertIn(f"  last screen {pane}  \n\n", screens)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in saved))

    def test_failed_capture_or_exclusive_creation_never_authorizes_closing(self):
        self.add("$1", "old")
        self.capture_error = True
        self.tick()
        self.assertEqual(self.closed, [])
        self.capture_error = False
        victim = self.root / "keep"
        victim.write_text("untouched")
        (config.TMP / "tmux-collision.txt").symlink_to(victim)
        with patch.object(orch.uuid, "uuid4") as uuid:
            uuid.return_value.hex = "collision"
            self.tick()
        self.assertEqual(victim.read_text(), "untouched")
        self.assertEqual(self.closed, [])

    def test_a_linked_tmp_directory_is_never_used(self):
        self.add("$1", "old")
        config.TMP.rmdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        config.TMP.symlink_to(elsewhere, target_is_directory=True)
        self.tick()
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(self.closed, [])

    def test_a_session_changed_during_capture_is_kept(self):
        for change in ("respawned", "marked", "renamed", "new-pane"):
            with self.subTest(change=change):
                self.sessions.clear()
                self.add("$1", "old")
                fields, windows = self.sessions["$1"]
                self.after_capture = {
                    "respawned": lambda: windows[0][0].update(pane_dead="0", pane_dead_time=""),
                    "marked": lambda: fields.update({orch.MARK: "1"}),
                    "renamed": lambda: fields.update(session_name="recorded-seat"),
                    "new-pane": lambda: windows[0].append({"pane_id": "%99", "pane_dead": "0",
                                                          "pane_dead_time": ""}),
                }[change]
                config.session_path("recorded-seat").write_text("{}")
                self.tick()
                self.assertEqual(self.closed, [])

    def test_the_shim_tags_every_creation_and_preserves_output_and_exit_status(self):
        shimdir, realdir = self.root / "shim", self.root / "real"
        shimdir.mkdir()
        realdir.mkdir()
        (shimdir / "tmux").symlink_to(REPO / "tools/tmux-shim")
        real = realdir / "tmux"
        real.write_text(f"#!{sys.executable}\nimport json, sys\n"
                        "print(json.dumps(sys.argv[1:]))\nsys.exit(3)\n")
        real.chmod(0o755)
        env = {**os.environ, "PATH": os.pathsep.join([str(shimdir), str(realdir),
                                                    os.environ.get("PATH", "")])}
        for command in ("new-session", "new", "new-s"):
            args = ["-uL", "elsewhere", command, "-d", "-s", "watch", ";",
                    "new-session", "-d", "echo finished"]
            result = subprocess.run([str(shimdir / "tmux"), *args], env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 3, result.stderr)
            tag = ["-e", "AGENTKIT_SESSION=acme", "-e", f"{guard.TMUX_OWNER}=acme"]
            self.assertEqual(json.loads(result.stdout),
                             [*args[:3], *tag, *args[3:8], *tag, *args[8:]])
        for override in ({"AK_RUN_ROLE": "worker"}, {"AGENTKIT_SESSION": ""}):
            result = subprocess.run([str(shimdir / "tmux"), "new-session", "-d"],
                                    env={**env, **override}, capture_output=True, text=True,
                                    timeout=15)
            self.assertEqual(json.loads(result.stdout), ["new-session", "-d"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
