"""However many merges wait to go live, one follower process of their Home follows them all.

Black-box: AK_BIN runs against Home, Rig, GitHub, Seat and Sink.  Three passed runs, merged by
their maintainer and recorded by `ak run merge` while health is red; no turn runs, as a turn's
box would hide an AK_BIN under /tmp.  A follower is a process running `watch --live` with the
Home as its HOME, read from /proc throughout.
"""

import json
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.sink import Sink

HEALTH = 'test -e "$HOME/live-ok" || { echo deploying; exit 1; }'
SEAT = {"AGENTKIT_SESSION": "acme"}


def followers(home):
    """The pids of the processes following that Home's merges to live: not those whose parent is
    one, the commands a follower runs, which read as it from their fork until they exec."""
    mark = f"HOME={home.path}".encode()
    found = {}
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
            env = (entry / "environ").read_bytes().split(b"\0")
            parent = int((entry / "stat").read_bytes().rsplit(b")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):     # gone meanwhile, or not ours to read
            continue
        if mark in env and any(argv[at:at + 2] == [b"watch", b"--live"] for at in range(len(argv))):
            found[int(entry.name)] = parent
    return {pid for pid, parent in found.items() if parent not in found}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MergesShareOneFollower(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        self.rig = Rig(self.home, "app", files={
            "AGENTS.md": f"---\ntests: none\nhealth: {HEALTH}\nusers: none\n---\n"})
        self.github = GitHub(self.home)
        self.github.grant(self.rig.slug, "WRITE")
        akconfig.write(self.home, ["opus", "astra"])
        self.seat = Seat(self.home, "acme", cwd=self.rig.path, planned=True)
        # the most followers alive at once, from before the first merge to the end of the test
        self.most, stop = set(), threading.Event()

        def look():
            while not stop.is_set():
                self.most = max(self.most, followers(self.home), key=len)
                stop.wait(0.02)

        census = threading.Thread(target=look, daemon=True)
        census.start()
        self.addCleanup(census.join)
        self.addCleanup(stop.set)

    def merge(self, name):
        """A run of the seat's that passed review, whose PR its maintainer merged, recorded as
        merged by `ak run merge` and its ending read by the seat; its directory."""
        branch, run_id = f"add-{name}", f"20261106-1200-add-{name}"
        sha = self.rig.branch(branch, {f"{name}.txt": f"{name}\n"})
        pr = self.github.open_pr(self.rig, branch, title=f"Add {name}")
        done = self.home.run("gh", "pr", "merge", pr, "--squash", cwd=self.rig.path)
        self.assertEqual(done.code, 0, done.out + done.err)
        worktree = self.home.path / ".agentkit" / "wt" / run_id
        self.rig.git("worktree", "add", "-q", str(worktree), branch)
        task = taskfile.write(self.home, self.rig.path, f"Add {name}", done_when=("true",))
        self.home.write(f".agentkit/runs/{run_id}/task.md", task.read_text())
        self.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "title": f"Add {name}", "state": "pass", "verdict": "PASS",
            "repo": str(self.rig.path), "worktree": str(worktree), "branch": branch,
            "base": "origin/main", "target": "origin/main", "rounds": 1,
            "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                 "summary": f"added {name}"}],
            "base_sha": self.rig.git("rev-parse", f"{sha}^"),
            "launched_session": self.seat.name, "pr": pr, "delivery_sha": sha,
            "finished_at": time.time(), "executor": "opus", "reviewer": "astra",
            "review": {"executor": "opus", "reviewer": "astra",
                       "executor_provider": "anthropic", "reviewer_provider": "openai",
                       "verdict": "PASS", "returncode": 0, "done_when": True, "head_sha": sha,
                       "tree_sha": self.rig.git("rev-parse", f"{sha}^{{tree}}")}})
        for command in (("merge", run_id), ("status", run_id)):
            # Its seat reads the merge's ending, so only the deployment is left to hear.
            done = self.home.ak("run", *command, env=SEAT, timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
        return self.home.path / ".agentkit" / "runs" / run_id

    def record(self, directory):
        return json.loads((directory / "run.json").read_text())

    def until(self, ready, what, bound=120):
        deadline = time.monotonic() + bound
        while not ready():
            self.assertLess(time.monotonic(), deadline, f"never {what}; followers: {self.most}")
            time.sleep(0.05)

    def test_three_merges_waiting_to_go_live_share_one_follower_and_are_each_told_once(self):
        directories = [self.merge(name) for name in ("api", "web", "docs")]
        self.until(lambda: all(self.record(directory).get("health", {}).get("output") == "deploying"
                               for directory in directories), "probed each merge while red")
        self.assertEqual(len(self.most), 1, self.most)
        self.home.write("live-ok", "")
        notices = [f"run {directory.name} is live" for directory in directories]
        self.until(lambda: all(any(notice in line for line in self.seat.lines())
                               for notice in notices), "told the seat each run is live")
        self.until(lambda: not followers(self.home), "ended the follower", bound=60)
        for notice in notices:
            self.assertEqual(sum(notice in line for line in self.seat.lines()), 1, self.seat.lines())
        self.assertEqual(len(self.most), 1, self.most)
        self.assertEqual(self.sink.pages(), [])


if __name__ == "__main__":
    unittest.main()
