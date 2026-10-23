"""A run parked on an expired login resumes by itself, where it stopped, once the login is back.

An expired login is one of the few things that page the owner, and signing in again is all the
owner should have to do: the tick asks the harness's `auth` verb, and the moment it says yes the
run goes on in the same worktree, the same round and the same conversation, and nobody hears of
it until it ends.  While the login is still out the run stays parked; if its worktree went
meanwhile, it cannot go on where it stopped and becomes an interruption instead of waiting for a
login it no longer needs.  The same holds for the turn that resolves a conflict while the run
delivers: it waits for the login, then resolves and lands.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, its turns on a fake harness from
fakeadapter.py whose `auth` verb the test logs out and back in, from a seat of akseat.py, paging
tests/fixtures/sink.py, delivering to the GitHub of fakegh.py; each tick runs in the box
`home.tick()` builds.
"""

import json
import shlex
import shutil
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.sink import Sink

LOGGED_OUT = "Not logged in · Please run /login"
LOGGED_IN = "logged in: ~/.claude/.credentials.json"
OFFLINE = "http://127.0.0.1:9"    # a refused port: the tick's public-board reads stay on loopback


def offline_home():
    home = Home()
    home.env.update(https_proxy=OFFLINE, HTTPS_PROXY=OFFLINE, no_proxy="127.0.0.1,localhost")
    return home


def park(home, seat=None):
    """A run, from that seat if named, whose executor turn finds its login gone: (claude fake,
    run dir, the run's exit code)."""
    rig = Rig(home, "widgets")
    akconfig.write(home, ["opus"])
    claude = fakeadapter.install(home, claude="work")["claude"]
    # A harness whose token expired exits at once having streamed nothing, and its `auth` verb
    # says so from then on.  The turn's box writes beside it only in the adapter's directory.
    expired = claude.dir / "expired.json"
    expired.write_text(json.dumps({"auth": [LOGGED_OUT, 1]}))
    claude.behave({"sh": shlex.join(["cp", str(expired), str(claude._file("answers"))])},
                  "work")
    task = taskfile.write(home, rig.path, "Add retry file")
    done = home.ak("run", str(task), "--no-merge", timeout=300,
                   env={"AGENTKIT_SESSION": seat} if seat else None)
    return claude, taskfile.only_run(home), done.code


def pages(home):
    """Every page the program has sent or still owes, as (seat, kind): a boxed tick has no
    loopback to reach the sink on, so what it pages waits in the outbox."""
    found = (json.loads(path.read_text())
             for path in (home.path / ".agentkit/state/notification-outbox").glob("*.json"))
    return sorted((event.get("session"), event.get("kind")) for event in found)


def record(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def wait_ended(run_dir, bound=60, states=("waiting_login", "queued", "running")):
    deadline = time.monotonic() + bound
    while record(run_dir)["state"] in states:
        if time.monotonic() > deadline:
            raise AssertionError(f"still {record(run_dir)['state']} after {bound} s")
        time.sleep(0.2)
    return record(run_dir)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class LoginBack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = offline_home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        cls.seat = Seat(cls.home, "acme")
        cls.claude, cls.run_dir, cls.code = park(cls.home, seat="acme")
        cls.parked = record(cls.run_dir)
        cls.out_tick = cls.home.tick()
        cls.after_out = record(cls.run_dir)
        cls.turns_while_out = cls.claude.n
        cls.claude.answer("auth", LOGGED_IN, 0)
        cls.dry = cls.home.ak("watch", "--dry-run")    # skips the passes the box is for
        cls.after_dry = record(cls.run_dir)
        cls.turns_after_dry = cls.claude.n
        cls.pages_before = pages(cls.home)
        cls.back_tick = cls.home.tick()
        cls.typed_to_seat = cls.seat.lines()
        cls.ended = wait_ended(cls.run_dir)

    def test_while_the_login_is_out_the_run_stays_parked_and_no_turn_runs(self):
        self.assertEqual(self.code, 1)
        self.assertEqual((self.parked["state"], self.parked["waiting_for"]),
                         ("waiting_login", "claude"))
        self.assertEqual(self.out_tick.code, 0, self.out_tick.err)
        self.assertEqual((self.after_out["state"], self.after_out["pid"]),
                         ("waiting_login", self.parked["pid"]))
        self.assertEqual(self.turns_while_out, 1)

    def test_a_dry_run_names_the_resume_it_would_start_and_starts_nothing(self):
        self.assertEqual(self.dry.code, 0, self.dry.err)
        said = [line for line in self.dry.out.splitlines() if self.run_dir.name in line]
        self.assertTrue(said and "resume" in said[0], self.dry.out)
        self.assertEqual(self.after_dry["state"], "waiting_login")
        self.assertEqual(self.turns_after_dry, 1)

    def test_once_the_auth_verb_passes_the_next_tick_resumes_the_run_to_its_end(self):
        self.assertEqual(self.back_tick.code, 0, self.back_tick.err)
        self.assertIn(self.run_dir.name, self.back_tick.out)
        self.assertEqual((self.ended["state"], self.ended["verdict"]), ("pass", "PASS"))
        self.assertNotIn("waiting_for", self.ended)

    def test_it_goes_on_in_the_same_worktree_round_and_conversation(self):
        worktree = self.parked["worktree"]
        self.assertEqual((self.ended["worktree"], self.ended["branch"]),
                         (worktree, self.parked["branch"]))
        self.assertEqual([summary["round"] for summary in self.ended["round_summaries"]], [1])
        self.assertEqual(self.parked["exec_session"], "sid-claude-1")
        executor = [turn for turn in self.claude.runs() if turn["role"] == "executor"]
        self.assertEqual(len(executor), 2, executor)
        _model, _effort, workspace, _prompt, out, *session = executor[1]["argv"]
        self.assertEqual((workspace, session), (worktree, ["sid-claude-1"]))
        self.assertEqual(Path(out).parent, self.run_dir / "round-1")
        tree = self.home.run("git", "-C", worktree, "ls-tree", "--name-only", "HEAD")
        self.assertIn("retry.txt", tree.out.split())

    def test_the_resume_pages_nobody_and_tells_the_seat_only_how_the_run_ended(self):
        # the one page is the expired login's own, sent before the owner signed in
        self.assertEqual(self.pages_before, [("acme", "needs")])
        self.assertEqual(pages(self.home), self.pages_before)
        # the boxed tick outlives the run it resumed, so the run's ending is all the seat got
        told, = self.typed_to_seat
        self.assertTrue(told.startswith(f"run {self.run_dir.name} finished PASS"), told)


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class WorktreeGone(unittest.TestCase):
    def test_a_login_back_with_its_worktree_gone_is_an_interruption_not_a_resume(self):
        home = offline_home()
        self.addCleanup(home.close)
        claude, run_dir, code = park(home)
        self.assertEqual((code, record(run_dir)["state"]), (1, "waiting_login"))
        worktree = record(run_dir)["worktree"]
        shutil.rmtree(worktree)
        claude.answer("auth", LOGGED_IN, 0)
        for _ in range(2):    # and a later tick does not take it up again
            done = home.tick()
            self.assertEqual(done.code, 0, done.err)
            state = record(run_dir)
            self.assertEqual(state["state"], "interrupted")
            self.assertNotIn("waiting_for", state)
            self.assertIn(worktree, state["interruption_reason"])
        self.assertEqual(claude.n, 1)


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ConflictFixer(unittest.TestCase):
    def test_a_conflict_fixer_whose_login_expired_waits_for_it_then_resolves_and_lands(self):
        home = offline_home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets")
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        fakes = fakeadapter.install(home, claude="work", codex="pass")
        claude, codex = fakes["claude"], fakes["codex"]
        # the review waits, so that the target moves and the login goes out before delivery
        release = codex.dir / "release"
        codex.behave({**fakeadapter.PASS, "sh": f"until [ -f {shlex.quote(str(release))} ]; "
                      "do sleep 0.1; done"}, "pass")
        claude.behave("work", {"sh": "printf 'hello\\nworld\\n' > retry.txt && git add -A && "
                               "GIT_EDITOR=true git rebase --continue",
                               "final": "Resolved.", "hand_in": [["done"]]})
        loop = home.spawn("run", str(taskfile.write(home, rig.path, "Add retry file")))
        deadline = time.monotonic() + 120
        while codex.n < 1 and loop.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        target = rig.commit({"retry.txt": "world\n"}, "Add the other retry file")
        claude.answer("auth", LOGGED_OUT, 1)
        release.write_text("")
        self.assertEqual(loop.wait(timeout=300), 1)
        run_dir = taskfile.only_run(home)
        parked = record(run_dir)
        # it parks after the review passed and before anything landed: while delivering
        self.assertEqual((parked["state"], parked["waiting_for"], parked["merged"]),
                         ("waiting_login", "claude", False))
        self.assertEqual([summary["verdict"] for summary in parked["round_summaries"]], ["PASS"])
        self.assertEqual([turn["role"] for turn in claude.runs()], ["executor"])
        claude.answer("auth", LOGGED_IN, 0)
        self.assertIn(run_dir.name, home.tick().out)
        for _ in range(10):    # the resumed run rejoins the line of runs landing on main
            state = wait_ended(run_dir, states=("waiting_login", "running"))
            if state["state"] != "waiting":
                break
            home.tick()
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        fixer = claude.runs()[1]
        _model, _effort, workspace, _prompt, out, *session = fixer["argv"]
        self.assertEqual(fixer["role"], "fixer")
        self.assertEqual((workspace, session), (parked["worktree"], ["sid-claude-1"]))
        self.assertEqual(Path(out).parent, run_dir / "round-1")
        self.assertEqual(rig.origin("show", "main:retry.txt"), "hello\nworld")
        self.assertEqual(rig.origin("rev-parse", "main^"), target)


if __name__ == "__main__":
    unittest.main()
