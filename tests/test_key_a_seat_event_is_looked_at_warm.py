"""A seat's event is looked at by a process already warm (`agentkit/looker.py`).

With a looker up, the hook's look is its fork, on the runs it read: the word is published with no
run.json of a run at rest opened, nor the runs listed again.  With none up, or one older than the
install, the same event is looked at cold, reading every run.  An audit hook writes down what each
look opens or lists; no clock bounds the handshake (`warm.WAIT`).
"""

import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]
from agentkit import config, looker, parsed, warm  # noqa: E402
from test_live_status import FAKE_TMUX, looks  # noqa: E402

# `pid<TAB>ppid<TAB>open|os.scandir<TAB>path` to $LOOK_READS, for each under HOME from here on
AUDIT = r"""
import os, sys
def _read(event, args, home=os.environ["HOME"] + "/",
          log=os.open(os.environ["LOOK_READS"], os.O_WRONLY | os.O_APPEND | os.O_CREAT)):
    path = event in ("open", "os.scandir") and args[0]
    if isinstance(path, (str, os.PathLike)) and os.fspath(path).startswith(home):
        os.write(log, f"{os.getpid()}\t{os.getppid()}\t{event}\t{path}\n".encode())
sys.addaudithook(_read)
"""
CLIENT = AUDIT + """
import runpy
del sys.argv[0]                 # as `python looker.py` has them
sys.path.insert(0, os.path.dirname(sys.argv[0]))
__import__("warm").WAIT = None
runpy.run_path(sys.argv[0], run_name="__main__")
"""


class Warm(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="looker-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        python = shlex.quote(sys.executable)
        (root / "bin").mkdir()
        for name, script in (("tmux", FAKE_TMUX), ("python3", (
                f"#!/bin/bash\n[[ $1 = */agentkit/looker.py ]] && "
                f"exec {python} -c {shlex.quote(CLIENT)} \"$@\"\nexec {python} \"$@\"\n"))):
            (root / "bin" / name).write_text(script)
            (root / "bin" / name).chmod(0o755)
        self.log, self.reads, home = root / "tmux.log", root / "reads", root / ".agentkit"
        for patched in (patch.dict(os.environ, clear=True, values={
                "HOME": str(root), "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
                "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                "AK_NOTIFY_SINK": "dry-run", "FAKE_TMUX_LOG": str(self.log),
                "FAKE_TMUX_GATE": str(root), "LOOK_READS": str(self.reads)}),
                patch.object(config, "HOME", home), patch.object(config, "CODE", root / "code"),
                *(patch.object(config, name, home / name.lower())
                  for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK")),
                patch.object(warm, "WAIT", None),
                patch.object(parsed, "FRESH", 0)):    # a run at rest is one its read kept
            patched.start()
            self.addCleanup(patched.stop)
        config.ensure_dirs()
        repo = config.CODE / "atoll"
        (repo / ".git").mkdir(parents=True)
        config.save_session(config.load(), "herdr", "opus", ["opus", "astra"],
                            {"repo": str(repo), "cwd": str(repo), "session_title": "herdr"})
        ended = time.time() - 7200
        for number in range(40):            # many runs of another seat, ended hours ago
            run = config.RUNS / f"20261113-0{number:03d}-fix-api" / "run.json"
            run.parent.mkdir()
            run.write_text(json.dumps({"run_id": run.parent.name, "state": "pass", "session": "q"}))
            os.utime(run, (ended, ended))
        self.resting = {str(run) for run in config.RUNS.glob("*/run.json")}
        self.addCleanup(self.cold)          # every cold look ended before this HOME goes

    def looker(self):
        """A looker up in this HOME, forked as the warm server forks one: its pid."""
        pid = os.fork()
        if pid == 0:
            try:
                exec(AUDIT, {})
                looker.serve()
            finally:
                os._exit(1)
        self.addCleanup(lambda: os.kill(pid, signal.SIGTERM) or os.waitpid(pid, 0))
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(config.STATE)              # its socket by its name, as the hook reaches it
        with socket.socket(socket.AF_UNIX) as probe:    # refused until it listens
            while probe.connect_ex(warm.place(str(REPO))[1] + ".look"):
                time.sleep(0.02)
        return pid

    def event(self):
        """The owner's prompt, as the seat's harness tells its hook, once the bar says `working`."""
        subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")], check=True, env=dict(
            os.environ, AGENTKIT_SESSION="herdr", TMUX="/fake/agentkit-test,1,0", TMUX_PANE="%7"),
            input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "go"}), text=True)
        while "set-titles-string\therdr · working\n" not in (
                self.log.read_text(encoding="utf-8") if self.log.exists() else ""):
            time.sleep(0.05)

    def read(self):
        """(pid, its parent, event, path) for each written down."""
        return [(int(pid), int(parent), event, path) for pid, parent, event, path in (
            line.split("\t") for line in self.reads.read_text().splitlines())]

    def cold(self, warm=()):
        """What looks opened, none of the `warm` processes' or their forks', once each has ended."""
        while looks(self.root):
            time.sleep(0.05)
        return {path for opener, parent, event, path in self.read()
                if event == "open" and not {opener, parent} & set(warm)}

    def test_a_looker_up_looks_on_the_runs_it_read(self):
        pid = self.looker()
        self.event()
        forks = {opener for opener, parent, *_ in self.read() if parent == pid}
        self.assertTrue(forks, "the looker's fork looked")
        while any(os.path.exists(f"/proc/{fork}") for fork in forks):
            time.sleep(0.05)                # each look ended, all it read written down
        forked = {(event, path) for opener, _, event, path in self.read() if opener in forks}
        self.assertEqual({path for event, path in forked if event == "open"} & self.resting, set())
        self.assertNotIn(("os.scandir", str(config.RUNS)), forked, "the runs are listed once")
        self.assertEqual(self.cold({pid, *forks}), set(), "nothing looked cold")

    def test_with_no_looker_up_the_event_is_looked_at_cold(self):
        self.event()
        self.assertLessEqual(self.resting, self.cold())

    def test_a_looker_of_an_older_install_is_not_asked(self):
        pid = self.looker()
        (config.STATE / "installed-at").write_text(str(time.time()))
        self.event()
        self.assertEqual([path for _, parent, _, path in self.read() if parent == pid], [])
        self.assertLessEqual(self.resting, self.cold({pid}))


if __name__ == "__main__":
    unittest.main()
