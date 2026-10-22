"""A run whose reviewed branch conflicted with main waits for main to move, then lands.

A rebase conflict is main moving under passed work, never a verdict on it: the tick parks a
conflict FAIL that has rounds left `waiting` on its upstream at the sha a fetch reads, leaves it
waiting while main stands still, and resumes it on the first tick that reads another sha
there, so the work lands without anyone asking.  A conflict FAIL at its round budget stays a
FAIL, since more rounds are the owner's to give, and a waiting run whose worktree is gone is
interrupted, saying so.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, against the bare origin of gitrig.py and the GitHub of fakegh.py, with
scripted harnesses from fakeadapter.py.
"""

import json
import socket
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
NOTE = "the rebase of origin/main conflicted in 1 file(s)"


def offline(home):
    """The tick asks the public boards over HTTP and fetches the checkout it runs from: every
    proxy names a loopback port nobody listens on, and git speaks only to files."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"), GIT_ALLOW_PROTOCOL="file")


def record(run_dir):
    """The run's record; one read as it is replaced is read again."""
    for _ in range(50):
        try:
            return json.loads((run_dir / "run.json").read_text())
        except ValueError:
            time.sleep(0.1)
    return json.loads((run_dir / "run.json").read_text())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ConflictWaits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        offline(home)
        cls.rig = rig = Rig(home, "widgets")
        cls.gh = GitHub(home)
        cls.gh.grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        Seat(home, "acme")      # the tick takes up only an ending whose seat is still there
        fakeadapter.install(home, claude="work", codex="pass")
        cls.runs = {"left": cls.conflicted("Add retry file"),
                    "spent": cls.conflicted("Add notes file", rounds=1), "lost": cls.lost()}
        cls.tip = rig.head()
        cls.ticks, cls.seen = [], []
        for move in (False, False, True):
            if move:
                cls.moved = rig.commit({"README.md": "widgets\n"}, "readme")
            cls.ticks.append(home.ak("watch"))
            cls.seen.append({name: record(run_dir) for name, run_dir in cls.runs.items()})
        deadline = time.monotonic() + 120
        while (state := record(cls.runs["left"]))["state"] in ("queued", "running", "waiting"):
            assert time.monotonic() < deadline, f"the resumed run never ended: {state['state']}"
            time.sleep(0.2)
        cls.landed = state

    @classmethod
    def conflicted(cls, title, rounds=None):
        """A run launched from seat acme to merge, whose reviewed branch would not rebase onto
        main: a FAIL whose note names the conflict, one round of its budget spent."""
        task = taskfile.write(cls.home, cls.rig.path, title,
                              front={"rounds": rounds} if rounds else None)
        done = cls.home.ak("run", str(task), "--no-merge")
        assert done.code == 0, done.out + done.err
        run_dir, = [path for path in taskfile.runs(cls.home)
                    if path.name.endswith(taskfile.slug(title))]
        state = record(run_dir)
        state.update(state="fail", verdict="FAIL", merge_note=NOTE, merge_failed=False,
                     no_merge=False, launch_opts={**state["launch_opts"], "--no-merge": False},
                     launched_session="acme")
        (run_dir / "run.json").write_text(json.dumps(state))
        with (run_dir / "log.txt").open("a") as log:
            log.write(f"[12:00:00] WARN not merged: {NOTE}\n")
        return run_dir

    @classmethod
    def lost(cls):
        """A run waiting on main whose worktree has since been removed."""
        now, head = time.time(), cls.rig.head()
        state = {"run_id": "20261020-0900-beta", "title": "beta", "state": "waiting",
                 "error": NOTE, "merge_note": NOTE, "waiting_on": {"ref": "origin/main",
                                                                   "sha": head},
                 "started_at": now - 900, "finished_at": now - 120, "launched_session": "acme",
                 "repo": str(cls.rig.path), "worktree": str(cls.home.path / ".agentkit/wt/beta"),
                 "branch": "ak/beta", "base": "origin/main", "base_sha": head, "rounds": 3}
        return cls.home.write(".agentkit/runs/20261020-0900-beta/run.json", state).parent

    def test_every_tick_exits_zero(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_conflict_fail_with_rounds_left_is_parked_waiting_on_main_at_its_tip(self):
        state = self.seen[0]["left"]
        self.assertEqual((state["state"], state["error"]), ("waiting", NOTE))
        self.assertEqual((state["waiting_on"]["ref"], state["waiting_on"]["sha"]),
                         ("origin/main", self.tip))

    def test_while_main_stands_still_the_run_keeps_waiting(self):
        self.assertEqual(self.seen[1]["left"]["state"], "waiting")
        self.assertEqual(self.seen[1]["left"]["waiting_on"], self.seen[0]["left"]["waiting_on"])

    def test_once_main_moves_the_run_is_resumed_and_lands_on_it(self):
        # still waiting at the tick before main moved: the tick after the move resumed it
        self.assertEqual((self.landed["state"], self.landed["verdict"], self.landed["merged"]),
                         ("pass", "PASS", True))
        pr, = self.gh.prs()
        self.assertEqual((pr["url"], pr["head"]), (self.landed["pr"],
                                                   f"{self.rig.slug}:ak/add-retry-file"))
        self.assertEqual(self.rig.origin("rev-parse", "main^"), self.moved)
        self.assertIn("retry.txt", self.rig.files())

    def test_a_conflict_fail_at_its_round_budget_stays_a_fail(self):
        for seen in self.seen:
            self.assertEqual(seen["spent"]["state"], "fail")

    def test_a_waiting_run_whose_worktree_is_gone_is_interrupted_saying_so(self):
        state = self.seen[0]["lost"]
        self.assertEqual(state["state"], "interrupted")
        self.assertIn(str(self.home.path / ".agentkit/wt/beta"), state["interruption_reason"])


if __name__ == "__main__":
    unittest.main()
