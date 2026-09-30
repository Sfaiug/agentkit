"""`ak` updates agentkit when it starts, behind its first draw: behind origin, the menu's
frame says `agentkit · updating` and fills the rule under it through fetch, pull and install,
then the menu starts again on the new commit; leaving it half-way, the update still goes on to
its end; offline or slow, it opens as it is at once; a checkout somebody works in is left as it
is.

Each case runs the menu in a child process whose ~/agentkit is a clone, in a temporary HOME, of
a throwaway bare origin, with a fake install.sh committed there; the child's seat listing,
maintenance and bridge are stubs, its keys a stand-in that says which commit the menu opened on
and leaves once the update has settled -- or, asked to, at its first `updating` frame.  The
update's own process and the re-exec are real: the child starts again and says so.  The real
~/agentkit, its origin and every seat are never touched.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
INSTALL = '#!/bin/sh\nsleep {}\necho installed >>"$(dirname "$0")/../installs"\n'
# The menu, with the live checkout the sandbox's clone, no seat, and its other start-up stubbed.
CHILD = r"""
import os, select, subprocess, sys, threading, time
from pathlib import Path
sys.path.insert(0, os.environ["START_REPO"])
from agentkit import config, macbridge, menu, orch, watch
print("<start>", flush=True)
cfg = config.load()                   # the shipped defaults, read before the clone stands in
config.REPO, config.load = (Path.home() / "agentkit").resolve(), lambda *args, **kwargs: cfg
watch.resume_after_boot = lambda cfg, dry_run=False, log=None: None
orch.maintenance = lambda log: None
macbridge.start_background = lambda: None
orch.listing = lambda *args, **kwargs: []
orch.job_notices = lambda: []
settled, update_first, draw, filled, waits = threading.Event(), menu.update_first, menu.draw, [], []

def settling(*args, **kwargs):
    try:
        return update_first(*args, **kwargs)
    finally:
        settled.set()

def drawing(*args, **kwargs):
    filled.append(kwargs.get("filled"))
    return draw(*args, **kwargs)

def wait_key(prompt, timeout=None, wake=None):
    if not waits:
        head = subprocess.run(["git", "-C", str(config.REPO), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        print(f"<menu at {head} after {time.monotonic() - began:.2f}>", flush=True)
    waits.append(settled.is_set())
    if os.environ.get("START_LEAVE") and filled[-1] is not None:
        print("<leaving>", flush=True)
        return ""
    if waits[-2:] == [True, True]:    # a whole wait since it settled: the menu had its chance
        return ""
    select.select([wake] if wake is not None else [], [], [], 0.05)
    return None

menu.update_first, menu.draw, menu.wait_key = settling, drawing, wait_key
menu.read = lambda prompt, default=None: default
began = time.monotonic()
sys.exit(menu.main([]))
"""
# What a worker's own run leaves in the environment; nothing here may act on that run.
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES")


class StartUpdate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-start-update-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        self.env.update({"HOME": str(self.root), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                         "TERM": "dumb", "GIT_CONFIG_NOSYSTEM": "1", "START_REPO": str(REPO),
                         "GIT_AUTHOR_NAME": "fixture", "GIT_COMMITTER_NAME": "fixture",
                         "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                         "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                         "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"})
        self.origin, self.seed, self.clone = (self.root / "origin.git", self.root / "seed",
                                              self.root / "agentkit")
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.root, "clone", "-q", str(self.origin), str(self.seed))
        self.git(self.seed, "symbolic-ref", "HEAD", "refs/heads/main")
        self.first = self.merge("first", install=INSTALL.format(0))
        self.git(self.root, "clone", "-q", str(self.origin), str(self.clone))
        self.child = self.root / "child.py"
        self.child.write_text(CHILD)

    def git(self, where, *args):
        return subprocess.run(["git", "-C", str(where), *args], check=True, capture_output=True,
                              text=True, timeout=60, env=self.env).stdout.strip()

    def merge(self, text, install=None):
        """One merge to origin's main; its commit."""
        (self.seed / "notes").write_text(text + "\n")
        if install is not None:
            (self.seed / "install.sh").write_text(install)
            (self.seed / "install.sh").chmod(0o755)
        self.git(self.seed, "add", "-A")
        self.git(self.seed, "commit", "-q", "-m", text)
        self.git(self.seed, "push", "-q", "origin", "main")
        return self.git(self.seed, "rev-parse", "HEAD")

    def start(self):
        """One `ak`: everything it printed, and the menu it opened as (commit, seconds)."""
        proc = subprocess.run([sys.executable, str(self.child)], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        opened = [line[len("<menu at "):-1].split(" after ")
                  for line in proc.stdout.splitlines() if line.startswith("<menu at ")]
        self.assertEqual(len(opened), proc.stdout.count("<start>"), proc.stdout)
        return proc.stdout, (opened[-1][0], float(opened[-1][1]))

    def installs(self):
        path = self.root / "installs"
        return len(path.read_text().splitlines()) if path.exists() else 0

    def test_behind_fills_the_rule_and_starts_on_the_new_commit(self):
        new = self.merge("second", install=INSTALL.format(0.5))
        self.env["COLUMNS"] = "90"
        out, (head, _) = self.start()
        lines = out.splitlines()
        # the rule under the header, a third more of it heavy as each of fetch, pull and install
        # begins, and all of it once install is done: each drawn as the menu comes round to it
        rules = ["━" * 30 * done + "─" * (90 - 30 * done) for done in range(4)]
        drawn = [n for n, line in enumerate(lines)
                 if lines[n - 1].startswith("agentkit · updating")]
        seen = list(dict.fromkeys(lines[n] for n in drawn))
        self.assertEqual(seen, sorted(seen, key=rules.index), out)
        self.assertLessEqual(set(seen), set(rules), out)
        self.assertIn(rules[2], seen, out)                      # install, half a second long
        self.assertEqual(out.count("<start>"), 2, out)          # it started again
        self.assertLess(drawn[-1], len(lines) - 1 - lines[::-1].index("<start>"))
        self.assertEqual(head, new)
        self.assertEqual(self.installs(), 1)
        out, (head, _) = self.start()                           # current: nothing to do
        self.assertNotIn("updating", out)
        self.assertEqual((head, self.installs()), (new, 1))

    def test_leaving_during_the_update_leaves_it_to_go_on_to_its_end(self):
        new = self.merge("second", install=INSTALL.format(1))
        self.env["START_LEAVE"] = "1"
        out, (head, _) = self.start()
        self.assertIn("<leaving>", out)
        self.assertEqual(out.count("<start>"), 1, out)          # gone, not started again
        self.assertEqual(self.installs(), 0)                    # install.sh still going
        until = time.monotonic() + 30
        while self.installs() == 0 and time.monotonic() < until:
            time.sleep(0.1)
        self.assertEqual((self.git(self.clone, "rev-parse", "HEAD"), self.installs()), (new, 1))
        del self.env["START_LEAVE"]
        out, (head, _) = self.start()                           # the next `ak` is on it
        self.assertNotIn("updating", out)
        self.assertEqual((head, self.installs()), (new, 1))

    def test_an_origin_that_never_answers_opens_the_menu_at_once(self):
        self.merge("second")
        hang = self.root / "hang"
        hang.write_text("#!/bin/sh\nsleep 60\n")
        hang.chmod(0o755)
        self.git(self.clone, "remote", "set-url", "origin", "ssh://origin.invalid/agentkit.git")
        self.env["GIT_SSH_COMMAND"] = str(hang)     # a network that takes the packets and no more
        out, (head, seconds) = self.start()
        self.assertLess(seconds, 1)
        self.assertNotIn("updating", out)
        self.assertEqual((head, self.installs()), (self.first, 0))

    def test_a_dirty_checkout_is_left_as_it_is(self):
        self.merge("second")
        (self.clone / "notes").write_text("somebody's edit\n")
        out, (head, _) = self.start()
        self.assertNotIn("updating", out)
        self.assertEqual(out.count("<start>"), 1)
        self.assertEqual((head, self.installs()), (self.first, 0))
        self.assertEqual((self.clone / "notes").read_text(), "somebody's edit\n")


if __name__ == "__main__":
    unittest.main()
