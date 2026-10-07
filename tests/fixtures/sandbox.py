"""A throwaway ak HOME for tests that drive ak in-process.

`Sandbox` gives each test its own HOME with ak's state directories, a fixed clock for the menu
(`time.time()` reads 10000), no real seats and fake host readings; `menu_input` scripts the
menu's reads.  Tests import it as `from fixtures.sandbox import Sandbox`.
"""

from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from agentkit import box, host, config, gc, menu, orch, terminal
from agentkit import record as run_record
from fixtures.hand_in import records


def account_home(home):
    """Give boxes a temporary passwd home too, never the caller's home and its mounts."""
    return patch.object(box.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=str(home)))


def in_account_home(argv, home, **kwargs):
    """Subprocesses need the same temporary account home, through their own passwd file."""
    with tempfile.NamedTemporaryFile(dir=home, prefix="passwd-", mode="w") as passwd:
        passwd.write(f"acme:x:{os.getuid()}:{os.getgid()}:Fixture:{home}:/bin/sh\n")
        passwd.flush()
        return subprocess.run(["bwrap", "--unshare-user", "--ro-bind", "/", "/",
                               "--dev", "/dev", "--proc", "/proc",
                               "--bind", str(REPO), str(REPO),
                               "--ro-bind", passwd.name, "/etc/passwd", "--", *argv], **kwargs)


@contextmanager
def menu_input(*, wait=None, **read_kw):
    """Scripted reads also answer waits; a silent open stdin must never strand the menu."""
    def read_key(prompt, *_args, **_kw):
        return menu.read(prompt, "")

    # A probe thread could call usage.collect after the test's mocks have gone.
    with patch.object(menu, "read", **read_kw) as read, \
            patch.object(menu, "wait_key", side_effect=wait if wait is not None else read_key), \
            patch.object(menu.Live, "probe", return_value=False):
        yield read


class Sandbox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-sandbox-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        # a menu leaves its reads, looks and maintenance going: they end before this HOME goes
        threads = set(threading.enumerate())

        def settle():
            for thread in set(threading.enumerate()) - threads:
                # enumerate includes threads whose start() is still waiting for bootstrap.
                self.assertTrue(thread._started.wait(15), f"{thread.name} did not start")
                thread.join(15)

        self.addCleanup(settle)
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root),
                                 "NO_COLOR": "1", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                                 # this HOME's OpenCode config, never the caller's: mimo is payg
                                 "OPENCODE_CONFIG_DIR": str(self.root / ".config/opencode")}))
        # the owner's commands, never those of the seat the suite happens to be started in
        os.environ.pop(config.SESSION_ENV, None)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[]))
        self.stack.enter_context(patch.object(terminal, "height", return_value=24))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=10000))
        self.stack.enter_context(patch.object(host, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.cfg = config.load()
        config.ensure_dirs()
        system_tmp = self.root / "system-tmp"
        system_tmp.mkdir(exist_ok=True)
        self.stack.enter_context(patch.object(gc, "TMP_BASE", system_tmp))
        self.stack.enter_context(patch.object(gc, "VAR_TMP_BASE", system_tmp))

    def ended(self, name, owner="gone-seat", **extra):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "title": f"Finished {name}", "state": "pass",
                 "verdict": "PASS", "launched_session": owner, "reported": False,
                 "executor": "opus", "reviewer": "astra",
                 "review": {"executor": "opus", "reviewer": "astra", "returncode": 0,
                            "executor_provider": config.model(self.cfg, "opus")["provider"],
                            "reviewer_provider": config.model(self.cfg, "astra")["provider"],
                            "verdict": "PASS", "done_when": True},
                 "finished_at": 9990, **extra}
        if "findings" in extra and "review_records" not in extra:
            state["review_records"] = records(extra["findings"])
        run_record.save_state(directory, state)
        return directory

    def rollout(self, filename, cwd, stamp, sid="thread", **extra):
        root = self.root / ".codex/sessions/2026/09/10"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"rollout-{filename}.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "cwd": str(cwd), "timestamp": stamp, "id": sid, **extra}}) + "\n")
        return path
