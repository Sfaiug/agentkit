"""A landing restarts an open menu once, and not at all when it brings no code.

Which code a process read is told by difference, never by order: `update.code_moved` compares
the modules' newest write with what the process read at its start.  Swapping in a version changes
that once, at the exchange; install.sh stamps only where there is no stamp; and a version bringing
only what no running process holds keeps the modules' times.  Here ~/agentkit is a real checkout
under a temporary HOME holding a copy of `agentkit/`, moved by the real `versions.switch`, each
move made final as a tick of the version it put live does, and each process is a real one started
from it that stays open and answers on request.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_go_live_retries_install as base
from agentkit import config, gc, versions

git = base.git
REPO = base.REPO
# install.sh's own stamp line, in an install holding only that, a server's unless ROLE says not
STAMPS = next(line for line in (REPO / "install.sh").read_text().splitlines()
              if "installed-at" in line)
INSTALL = f'#!/bin/sh\nROLE="${{ROLE:-server}}" AK="$HOME/.agentkit"\n{STAMPS}\n'
ANSWERS = """
import json, sys
sys.path.insert(0, sys.argv[1])
from agentkit import config, update
print(flush=True)
for _ in sys.stdin:
    print(json.dumps([update.outdated(), update.code_moved(), config.code_written()]), flush=True)
"""


class Open:
    """A process started from the checkout and left open."""

    def __init__(self, case):
        self.proc = subprocess.Popen([sys.executable, "-c", ANSWERS, str(case.clone)], env=case.env,
                                     cwd=case.root, text=True, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE)
        case.addCleanup(self.close)
        self.proc.stdout.readline()     # its code read

    def close(self):
        self.proc.stdin.close()
        self.proc.stdout.close()
        self.proc.wait(30)

    def ask(self):
        """(outdated, code moved), and when its code was written as it reads it now."""
        self.proc.stdin.write("\n")
        self.proc.stdin.flush()
        *told, written = json.loads(self.proc.stdout.readline())
        return tuple(told), written


class ALandingRestartsAMenuOnce(unittest.TestCase):
    def setUp(self):
        base.GoLiveRetriesInstall.setUp(self)
        seed = self.seed = self.root / "seed"
        shutil.copytree(REPO / "agentkit", seed / "agentkit",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (seed / "agentkit" / "acme.py").write_text("")
        (seed / "install.sh").write_text(INSTALL)
        self.commit("the code")
        git(self.clone, "pull", "-q")
        self.env = {"HOME": str(self.root), "PATH": os.defpath, "LANG": "C.UTF-8",
                    "PYTHONPYCACHEPREFIX": str(self.root / "pycache"),   # a checkout left clean
                    **{name: value for name, value in os.environ.items()
                       if name.startswith("GIT_")}}
        self.stamp = config.STATE / "installed-at"
        self.stamp.write_text(f"{int(time.time()) - 60}\n")

    def commit(self, message):
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", message)
        git(self.seed, "push", "-q", "origin", "main")
        return git(self.seed, "rev-parse", "HEAD")

    def change(self, name):
        """A commit on origin changing `name` and nothing else, the last move final."""
        with patch.object(config, "BEGAN", os.stat(self.clone)):
            versions.final()
        path = self.seed / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((path.read_text() if path.exists() else "") + "# changed\n")
        return self.commit(name)

    def land(self, name, before=lambda: None, after=lambda: None):
        """`name` changed and live through `versions.switch`; `before` and `after` the exchange."""
        commit, real = self.change(name), versions.exchange
        git(self.clone, "fetch", "-q", "origin", "main")

        def exchange(one, other):
            before()
            real(one, other)
            after()
        with patch.object(versions, "exchange", exchange), \
                patch.object(gc, "tmp_processes", lambda: (set(), {})):
            self.assertEqual(versions.switch(self.clone, commit), "")

    def updated(self, name):
        """`name` changed, and `startup()`'s `moved` as the menu's update reports it, live by it."""
        commit = self.change(name)
        done = subprocess.run([sys.executable, "-m", "agentkit.update", "--agentkit"], env=self.env,
                              cwd=self.clone, capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), commit)
        return json.loads(done.stdout.splitlines()[-1])["moved"]

    def install(self):
        subprocess.run([str(self.clone / "install.sh")], env=self.env, check=True, timeout=60)

    def test_code_restarts_what_is_open_at_the_exchange_and_never_again(self):
        opened, told = Open(self), []
        self.land("agentkit/acme.py", lambda: told.append(opened.ask()[0]),
                  lambda: told.append(opened.ask()[0]))
        self.assertEqual(told, [(False, False), (True, True)])
        written, stamped = opened.ask()[1], self.stamp.read_text()
        restarted = Open(self)      # the restart, its install still to run
        self.install()
        self.assertEqual(opened.ask(), ((True, True), written))
        self.assertEqual(self.stamp.read_text(), stamped)
        self.assertEqual(restarted.ask(), ((False, False), written))
        self.assertEqual(Open(self).ask(), ((False, False), written))

    def test_a_process_started_during_the_checkout_read_the_old_code(self):
        late, told = [], []
        self.land("agentkit/acme.py", lambda: (late.append(Open(self)),
                                               told.append(late[0].ask()[0])),
                  lambda: told.append(late[0].ask()[0]))
        self.assertEqual(told, [(False, False), (True, True)])

    def test_a_landing_with_nothing_a_process_runs_restarts_nothing(self):
        opened = Open(self)
        written = opened.ask()[1]
        for name in ("go/acme.go", "docs/acme.md", "tests/test_acme.py", "README.md"):
            with self.subTest(name):
                self.assertIs(self.updated(name), False)
                self.assertEqual(opened.ask(), ((False, False), written))

    def test_any_other_landing_restarts(self):
        for name in ("agentkit/harness/acme.py", "bin/acme"):
            with self.subTest(name):
                opened = Open(self)
                self.assertIs(self.updated(name), True)
                self.assertEqual(opened.ask()[0], (True, True))

    def test_a_stamp_past_the_clock_hides_no_landing(self):
        ahead = int(time.time()) + 2
        self.stamp.write_text(f"{ahead}\n")
        while time.time() <= ahead:
            time.sleep(0.05)
        for stamp, before in ((ahead, False), (int(time.time()) + 3600, True)):
            self.stamp.write_text(f"{stamp}\n")
            opened, told = Open(self), []   # the first once the clock passed its stamp
            self.land("agentkit/acme.py", lambda: told.append(opened.ask()[0]),
                      lambda: told.append(opened.ask()[0]))
            self.assertEqual(told, [(before, False), (True, True)])

    def test_a_client_with_no_stamp_is_not_outdated_and_still_restarts_on_its_own_update(self):
        self.stamp.unlink()
        self.env["ROLE"] = "client"
        opened = Open(self)
        self.assertIs(self.updated("agentkit/acme.py"), True)
        self.assertEqual(opened.ask()[0], (False, True))
        self.assertFalse(self.stamp.exists())


if __name__ == "__main__":
    unittest.main()
