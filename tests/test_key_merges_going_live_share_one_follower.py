"""However many merges of one project wait to go live, one follower process follows them all.

Black-box: AK_BIN against Home, Rigs, GitHub and Seat.  Passed runs of two projects, api's
settings restating PATH and web's none, merged while health is red; no turn runs, as a turn's box
would hide an AK_BIN under /tmp.  A follower runs `watch --live RUN` with the Home as its HOME."""

from collections import Counter
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

AGENTS = "---\ntests: none\nhealth: live-check\nusers: none\n---\n"
HELPER = '#!/bin/sh\ntest -e "$HOME/live-ok" || { echo deploying; exit 1; }\n'   # on PATH
FORKED = 0x40   # PF_FORKNOEXEC: a fork yet to exec what it starts, running nothing of its own


def followers(home):
    """The project of each process following that Home's merges to live, as its RUN names it."""
    mark, found = f"HOME={home.path}".encode(), Counter()
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
            env = (entry / "environ").read_bytes().split(b"\0")
            flags = int((entry / "stat").read_bytes().rsplit(b")", 1)[1].split()[6])
        except (OSError, IndexError, ValueError):     # gone meanwhile, or not ours to read
            continue
        if mark in env and not flags & FORKED:
            found.update(argv[at + 2].split(b"-")[2].decode() for at in range(len(argv) - 2)
                         if argv[at:at + 2] == [b"watch", b"--live"])
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MergesShareOneFollower(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.home.fake("live-check", HELPER)
        self.home.write(".agentkit/env/api.env", f"PATH={self.home.bin}:/usr/bin:/bin\n")
        self.home.write(".agentkit/env/web.env", "TOKEN=web\n")
        self.github = GitHub(self.home)
        self.rigs = {name: Rig(self.home, name, files={"AGENTS.md": AGENTS})
                     for name in ("api", "web")}
        akconfig.write(self.home, ["opus", "astra"])
        self.seat = Seat(self.home, "acme", cwd=self.rigs["api"].path, planned=True)
        # each project's most followers alive at once, from before the first merge to the end
        self.most, stop = Counter(), threading.Event()

        def look():
            while not stop.wait(0.02):
                self.most |= followers(self.home)

        census = threading.Thread(target=look, daemon=True)
        census.start()
        self.addCleanup(lambda: stop.set() or census.join())

    def merge(self, project, name):
        """A passed run of the seat's, its merge recorded by `ak run merge`, then read; its dir."""
        rig, branch, run_id = self.rigs[project], f"add-{name}", f"20261106-1200-{project}-{name}"
        sha = rig.branch(branch, {f"{name}.txt": f"{name}\n"})
        pr = self.github.open_pr(rig, branch, title=f"Add {name}")
        done = self.home.run("gh", "pr", "merge", pr, "--squash", cwd=rig.path)
        self.assertEqual(done.code, 0, done.out + done.err)
        worktree = self.home.path / ".agentkit" / "wt" / run_id
        rig.git("worktree", "add", "-q", str(worktree), branch)
        self.home.write(f".agentkit/runs/{run_id}/task.md", "## Done when\n```bash\ntrue\n```\n")
        self.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "state": "pass", "verdict": "PASS", "repo": str(rig.path),
            "worktree": str(worktree), "branch": branch, "base": "origin/main",
            "target": "origin/main", "base_sha": rig.git("rev-parse", f"{sha}^"), "rounds": 1,
            "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True, "summary": ""}],
            "launched_session": self.seat.name, "pr": pr, "delivery_sha": sha,
            "finished_at": time.time(), "executor": "opus", "reviewer": "astra",
            "review": {"executor": "opus", "reviewer": "astra", "executor_provider": "anthropic",
                       "reviewer_provider": "openai", "verdict": "PASS", "returncode": 0,
                       "done_when": True, "head_sha": sha,
                       "tree_sha": rig.git("rev-parse", f"{sha}^{{tree}}")}})
        for command in (("merge", run_id), ("status", run_id)):
            # Its seat reads the merge's ending, so only the deployment is left to hear.
            done = self.home.ak("run", *command, env={"AGENTKIT_SESSION": "acme"}, timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
        return self.home.path / ".agentkit" / "runs" / run_id

    def until(self, ready, what, bound=120):
        deadline = time.monotonic() + bound
        while not ready():
            self.assertLess(time.monotonic(), deadline, f"never {what}; followers: {self.most}")
            time.sleep(0.05)

    def test_each_projects_merges_share_one_follower_and_each_is_told_live_once(self):
        directories = [self.merge(*run) for run in (("api", "one"), ("api", "two"), ("web", "one"))]
        self.home.write("live-ok", "")
        told = lambda: [sum(f"run {directory.name} is live" in line for line in self.seat.lines())
                        for directory in directories]
        self.until(lambda: all(told()), "told the seat each run is live")
        self.until(lambda: not followers(self.home), "ended the followers", bound=60)
        self.assertEqual(told(), [1, 1, 1], self.seat.lines())
        self.assertEqual(self.most, {"api": 1, "web": 1})


if __name__ == "__main__":
    unittest.main()
