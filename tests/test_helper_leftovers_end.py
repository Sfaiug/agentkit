"""Each helper ak starts without `bin/ak` marks itself as it starts, under its own name, and once
it is gone the tick's sweep ends what it left in its session, naming it.

The helpers, each started the way ak starts it, its start caught at `Popen` where it is one and
run then: the harness update and agentkit's (`python3 -m agentkit.update`), the background
cleanup (`python3 -m agentkit.retention collect`), the seat look (`watch.start_look`, and the one
hooks/seat-state.sh starts), the menu's seat stop (`menu.teardown`), and the warm server's reader
(`warm._read`), forked as the server forks it.  Each runs under PROBE, a sitecustomize whose
`owner.mark` writes down the mark it made and what the process is, and ends it there: none of its
work runs.  The sweep then reads a fake /proc (`host.PROC`) holding a `sleep` the helper left in
its session.
"""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.clock import Clock  # noqa: E402
from fixtures.sandbox import REPO, Sandbox  # noqa: E402
from agentkit import config, gc, host, menu, owner, update, warm, watch  # noqa: E402

INHERITED = "4026531836 4242 777 4200 ak watch"   # another's mark: none of them runs under it
# REPO and SAID come first, set where it is written
PROBE = """
import json, os, sys
sys.path.insert(0, REPO)
from agentkit import owner
made = owner.mark


def mark(name):
    made(name)
    with open("/proc/self/stat") as stat:
        start = stat.read().rsplit(")", 1)[1].split()[19]
    own = f"{os.stat('/proc/self/ns/pid').st_ino} {os.getpid()} {start} {os.getsid(0)} {name}"
    with open(SAID, "a") as said:
        said.write(json.dumps({"mark": os.environ.get(owner.MARK), "own": own}) + "\\n")
    os._exit(0)


owner.mark = mark
"""


class HelperLeftoversEnd(Sandbox):
    def setUp(self):
        super().setUp()
        self.said, site = self.root / "said.jsonl", self.root / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(f"REPO, SAID = {str(REPO)!r}, {str(self.said)!r}\n"
                                               + PROBE)
        self.stack.enter_context(patch.dict(os.environ, {
            owner.MARK: INHERITED, "PYTHONPATH": str(site),
            "TMUX": "/tmp/tmux-1/default,1,0", "TMUX_PANE": "%1"}))

    def made(self, name):
        """The mark the helper made, once it is down, asserted to name that process as `name`."""
        deadline = time.monotonic() + 60
        while not self.said.exists():
            self.assertLess(time.monotonic(), deadline, f"the {name} made no mark")
            time.sleep(0.05)
        said = json.loads(self.said.read_text())
        self.assertEqual(said["mark"], said["own"])
        self.assertEqual(said["mark"].split(" ", 4)[4], name)
        return said["mark"]

    def started(self, start, name):
        """`start`'s one start, run as it was asked for: the mark its helper made."""
        caught = []
        with patch.object(subprocess, "Popen",
                          lambda argv, **kw: caught.append((argv, kw)) or SimpleNamespace(pid=0)), \
                patch.object(update, "agentkit_dir", return_value=config.REPO):
            start()
        [(argv, kw)] = caught
        self.assertNotIn(owner.MARK, kw["env"])      # what starts it starts it unmarked
        subprocess.run(argv, **kw, timeout=120)
        return self.made(name)

    def swept(self, mark):
        """The sweep, while the helper that made `mark` runs and once it is gone, over a `sleep`
        it left in its session: a signal ends it."""
        _, pid, start, session, name = mark.split(" ", 4)
        proc, log, stat = self.root / "proc", [], host.proc_stat
        self.stack.enter_context(patch.object(host, "PROC", proc))
        self.stack.enter_context(patch.object(host, "proc_stat", lambda pid: stat(pid, proc)))
        self.stack.enter_context(patch.object(owner, "time", Clock(lambda _: None)))
        self.stack.enter_context(patch.object(owner, "_send", lambda pid, *_: not shutil.rmtree(
            proc / str(pid))))
        left = int(pid) + 1
        for row in (pid, left):
            (proc / str(row)).mkdir(parents=True)
            (proc / str(row) / "stat").write_text(f"{row} (sleep) S 1 {row} {session}"
                                                  f"{' 0' * 15} {start}")
            (proc / str(row) / "cmdline").write_text("sleep\x00600\x00")
            (proc / str(row) / "environ").write_text(f"HOME={os.environ['HOME']}\0"
                                                     f"{owner.MARK}={mark}\0")
        owner.sweep(log.append)
        self.assertEqual(log, [])                    # its helper runs
        shutil.rmtree(proc / pid)
        owner.sweep(log.append)
        self.assertEqual(log, [f"TERM to sleep 600 (pid {left}), which a gone `{name}` "
                               f"(pid {pid}) left running"])

    def test_the_harness_update(self):
        self.swept(self.started(lambda: update.start("claude"), "harness update"))

    def test_agentkit_s_update(self):
        self.swept(self.started(menu.update_first, "agentkit update"))

    def test_the_background_cleanup(self):
        self.swept(self.started(lambda: gc.schedule_gc(print), "background cleanup"))

    def test_the_seat_look_the_stop_hook_starts(self):
        self.swept(self.started(lambda: watch.start_look("acme"), "seat look"))

    @unittest.skipUnless(shutil.which("jq"), "no jq, which hooks/seat-state.sh reads with")
    def test_the_seat_look_the_seat_s_hook_starts(self):
        subprocess.run(["bash", REPO / "hooks" / "seat-state.sh"], text=True, timeout=120,
                       input=json.dumps({"hook_event_name": "Notification",
                                         "notification_type": "idle_prompt"}),
                       env={**owner.unmarked(), "AGENTKIT_SESSION": "acme", "AK_RUN_ROLE": ""})
        self.swept(self.made("seat look"))

    def test_the_seat_stop(self):
        self.swept(self.started(lambda: menu.stop_behind("acme", True), "seat stop"))

    def test_the_menu_reader(self):
        with patch.object(owner, "mark", owner.mark):     # what the probe puts there goes after
            exec(PROBE, {"REPO": str(REPO), "SAID": str(self.said)})
            reader = os.fork()
            if reader == 0:
                try:
                    warm._read(os.open(os.devnull, os.O_WRONLY))
                finally:
                    os._exit(1)
        self.addCleanup(os.waitpid, reader, 0)
        self.addCleanup(os.kill, reader, signal.SIGKILL)    # a reader that never marks reads on
        self.swept(self.made("menu reader"))


if __name__ == "__main__":
    unittest.main()
