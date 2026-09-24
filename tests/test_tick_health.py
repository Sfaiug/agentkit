"""The three-minute tick looks after itself: one at a time, a bounded log, no traceback on gh.

Offline: every pass of the tick is stubbed, the crontab is a shim on PATH over a temporary
directory, and the log under test is this test's own file -- the real crontab and the real
~/.agentkit/tmp/watch.log are never read or written here.
"""

from contextlib import ExitStack, contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import browser, config, notify, orch, run, usage, watch


class TickHealth(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".tick-health-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": "",
        }))
        # which streams the log owns outlives a roll, so it outlives a process; each test is
        # its own tick and must not inherit the streams the last one stood on
        self.stack.enter_context(patch.object(watch, "LOG_OWNED", set()))
        config.ensure_dirs()

    def stub_tick(self):
        """Every pass of the tick except the ones a test is about, so nothing leaves the box."""
        for where, name in ((notify, "retry_pending"), (notify, "tick_cards"),
                            (watch, "resume_after_boot"), (watch, "health"),
                            (watch, "recover_runs"), (watch, "resume_exhausted"),
                            (watch, "revive_seats"), (run, "schedule_gc"),
                            (orch, "stamp"), (orch, "sweep"), (usage, "collect")):
            self.stack.enter_context(patch.object(where, name))
        self.stack.enter_context(patch.object(run, "reap", lambda _dir, state: state))
        self.tidy = self.stack.enter_context(patch.object(browser, "tidy"))
        self.incoming = self.stack.enter_context(patch.object(watch, "incoming"))
        self.outgoing = self.stack.enter_context(patch.object(watch, "outgoing"))
        self.gh = self.stack.enter_context(
            patch.object(watch, "gh_json", return_value=({"login": "owner"}, "")))

    def tick(self, *argv):
        """One `ak watch`, with what it printed."""
        out = io.StringIO()
        with redirect_stdout(out):
            code = watch.main(list(argv))
        return code, out.getvalue()

    @contextmanager
    def as_cron(self):
        """Stand where cron stands: `>>watch.log 2>&1`, both streams appending to the log file.

        Handles of this test's own, never the process's descriptors: the real watch.log is
        nowhere near any of this.  Leaving is the end of that tick, so it forgets the streams
        it stood on -- the ones it hands back belong to the test runner.
        """
        out, err = watch.log_path().open("a"), watch.log_path().open("a")
        saved = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            yield out
        finally:
            sys.stdout, sys.stderr = saved
            watch.LOG_OWNED.clear()
            out.close()
            err.close()

    def hold_the_lock(self, pid=4242, since=None):
        """Another tick, as far as this one can tell: its own fd, flocked, with its own stamp."""
        import fcntl
        path = watch.tick_lock_path()
        handle = path.open("a+")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write(f"{pid}\n")
        handle.flush()
        if since is not None:
            os.utime(path, (since, since))
        return handle

    def seat_state(self, name):
        """What every screen would say about that seat, off the one ladder and no tmux."""
        return watch.session_state(name, session={"name": name}, live={}, records=[])

    def raw_run(self, name, receipt):
        """A run.json exactly as given: a receipt is only ever as complete as its stage."""
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "run.json").write_text(
            receipt if isinstance(receipt, str) else json.dumps(receipt))
        return directory

    def a_run(self, name, seat, **fields):
        """A started run of that seat's, with a delivery ahead of it unless told otherwise."""
        return self.raw_run(name, {"run_id": name, "state": "running", "title": "a job",
                                   "launched_session": seat, "no_merge": False,
                                   "repo": str(self.root / "code"), **fields})

    def cron_block(self):
        """Section (g) of install.sh, run as the installer runs it on a server."""
        source = (REPO / "install.sh").read_text()
        start = source.index("# --- (g) server or client")
        return source[start:source.index("\n# --- ", start + 1)]

    def install_cron(self, existing):
        """Run that block with a crontab shim; what the crontab holds afterwards, and what
        the installer said."""
        binaries = self.root / "bin"
        binaries.mkdir(exist_ok=True)
        table = self.root / "crontab.txt"
        table.write_text(existing)
        shim = binaries / "crontab"
        shim.write_text("#!/bin/sh\n"
                        f'if [ "$1" = "-l" ]; then cat {shlex.quote(str(table))}; '
                        f'else cat >{shlex.quote(str(table))}; fi\n')
        shim.chmod(0o755)
        prelude = (f"set -euo pipefail\nROLE=server\nSANDBOX=0\nALIAS=\nAK={shlex.quote(str(self.root))}\n"
                   f"REPO={shlex.quote(str(REPO))}\nBIN={shlex.quote(str(binaries))}\n"
                   f"NPM_PREFIX={shlex.quote(str(self.root))}\n"
                   'have() { command -v "$1" >/dev/null 2>&1; }\nnote() { echo "$@"; }\n')
        (self.root / "state").mkdir(exist_ok=True)
        proc = subprocess.run(["bash", "-c", prelude + self.cron_block()], text=True,
                              capture_output=True,
                              env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return table.read_text(), proc.stdout

    # --- one tick at a time ---------------------------------------------------

    def test_a_second_tick_says_who_has_the_lock_and_exits_zero_doing_nothing(self):
        self.stub_tick()
        self.hold_the_lock(pid=4242, since=time.time() - 7 * 60)
        code, said = self.tick()
        self.assertEqual(code, 0)
        self.assertIn("tick already running (pid 4242, for 7 min)", said)
        self.assertNotIn("WARN", said)
        notify.retry_pending.assert_not_called()
        watch.health.assert_not_called()
        self.gh.assert_not_called()
        self.tidy.assert_not_called()

    def test_a_tick_holding_the_lock_past_thirty_minutes_is_warned_about_too(self):
        self.stub_tick()
        self.hold_the_lock(pid=99, since=time.time() - watch.TICK_HUNG - 60)
        code, said = self.tick()
        self.assertEqual(code, 0)
        self.assertIn("tick already running (pid 99, for 31 min)", said)
        self.assertIn("WARN", said)
        self.assertIn("31 min", said.split("WARN", 1)[1])

    def test_the_lock_is_free_again_for_the_next_tick_and_names_this_process(self):
        self.stub_tick()
        self.assertIsNone(watch.tick_running())
        code, said = self.tick()
        self.assertEqual(code, 0)
        self.assertNotIn("tick already running", said)
        self.assertEqual(watch.tick_lock_path().read_text().strip(), str(os.getpid()))
        self.assertIsNone(watch.tick_running())   # main let it go on the way out
        self.assertEqual(self.tick()[0], 0)

    # --- a bounded log --------------------------------------------------------

    def test_the_log_rolls_over_to_one_kept_generation_past_five_megabytes(self):
        log, kept = watch.log_path(), watch.log_path().with_name(watch.LOG_KEPT)
        log.write_bytes(b"x" * (watch.LOG_MAX - 10))
        with self.as_cron():
            watch.tick_log("under the limit")       # nothing to roll yet
            self.assertFalse(kept.exists())
            self.assertTrue(log.exists())
            watch.tick_log("after the roll")        # the file is past the limit now
            self.assertEqual(watch.log_path().read_text(), "after the roll\n")
            print("and the reason it died", file=sys.stderr, flush=True)
        # the lines written before the roll went with the generation they belong to, and both
        # streams followed the rename: nothing lands in a file the next tick will not find
        self.assertTrue(kept.read_bytes().startswith(b"x"))
        self.assertTrue(kept.read_bytes().endswith(b"under the limit\n"))
        self.assertEqual(log.read_text(), "after the roll\nand the reason it died\n")
        # one generation and no more, and a log under the limit is left where it is
        log.write_bytes(b"z" * (watch.LOG_MAX + 1))
        with self.as_cron():
            watch.tick_log("rolled again")
            watch.tick_log("and not again")
        self.assertTrue(kept.read_bytes().startswith(b"z"))
        self.assertEqual(log.read_text(), "rolled again\nand not again\n")
        self.assertEqual(sorted(p.name for p in log.parent.iterdir()),
                         [watch.LOG_NAME, watch.LOG_KEPT])

    def test_the_log_of_a_tick_that_is_not_cron_is_never_renamed_under_it(self):
        self.stub_tick()
        log = watch.log_path()
        log.write_bytes(b"x" * (watch.LOG_MAX + 1))
        for argv in ((), ("--dry-run",)):
            with self.subTest(argv=argv):
                self.assertEqual(self.tick(*argv)[0], 0)   # printing into a buffer, not the log
                self.assertEqual(log.stat().st_size, watch.LOG_MAX + 1)
                self.assertFalse(log.with_name(watch.LOG_KEPT).exists())

    def test_a_dry_run_renames_nothing_even_printing_into_an_oversized_log(self):
        self.stub_tick()
        log, kept = watch.log_path(), watch.log_path().with_name(watch.LOG_KEPT)
        kept.write_text("the generation from before\n")
        log.write_bytes(b"x" * (watch.LOG_MAX + 1))
        with self.as_cron():
            self.assertEqual(watch.main(["--dry-run"]), 0)
        self.assertEqual(kept.read_text(), "the generation from before\n")
        self.assertTrue(log.read_bytes().startswith(b"x"))
        self.assertIn("lock free", log.read_text(errors="replace"))
        self.assertGreater(log.stat().st_size, watch.LOG_MAX)   # appended to, never rolled

    def test_a_tick_that_cannot_have_the_lock_still_bounds_the_log_it_writes_into(self):
        # A tick hung holding the lock writes nothing more; the ticks piling up behind it are
        # the only thing still appending, so the bound has to be theirs to apply.
        self.stub_tick()
        log = watch.log_path()
        log.write_bytes(b"x" * (watch.LOG_MAX + 1))
        self.hold_the_lock(pid=5, since=time.time() - 60)
        with self.as_cron():
            self.assertEqual(watch.main([]), 0)
        self.assertEqual(log.with_name(watch.LOG_KEPT).stat().st_size, watch.LOG_MAX + 1)
        self.assertEqual(log.read_text(), "tick already running (pid 5, for 1 min)\n")

    def test_a_writer_rejoins_the_live_log_after_another_tick_rolls_it(self):
        log, kept = watch.log_path(), watch.log_path().with_name(watch.LOG_KEPT)
        log.write_bytes(b"x" * (watch.LOG_MAX + 1))
        with self.as_cron():
            # another tick rolls the file this one is holding open, before it has said a word
            log.replace(kept)
            log.write_text("the other tick's fresh log\n")
            watch.tick_log("mine, written after somebody else rolled it")
            print("and mine on stderr", file=sys.stderr, flush=True)
            self.assertEqual(log.read_text(), "the other tick's fresh log\n"
                             "mine, written after somebody else rolled it\nand mine on stderr\n")
            self.assertEqual(kept.stat().st_size, watch.LOG_MAX + 1)   # not a byte more
            # and this writer is bounding the live log again, not the generation behind it
            log.write_bytes(b"y" * (watch.LOG_MAX + 1))
            watch.tick_log("rolled by me this time")
        self.assertTrue(kept.read_bytes().startswith(b"y"))
        self.assertEqual(log.read_text(), "rolled by me this time\n")

    def test_a_writer_left_on_an_unlinked_generation_still_rejoins_the_live_log(self):
        log, kept = watch.log_path(), watch.log_path().with_name(watch.LOG_KEPT)
        log.write_bytes(b"x" * (watch.LOG_MAX + 1))
        with self.as_cron():
            watch.tick_log("mine, before either roll")
            # two more rolls while this writer says nothing: the file it holds is not the live
            # log, is not the kept generation either, and has no name left at all
            for generation in ("second", "third"):
                log.replace(kept)
                log.write_text(f"the {generation} roll's fresh log\n")
            watch.tick_log("mine, from an inode nobody can name")
            print("and mine on stderr", file=sys.stderr, flush=True)
        self.assertEqual(log.read_text(), "the third roll's fresh log\n"
                         "mine, from an inode nobody can name\nand mine on stderr\n")

    def test_two_writers_that_both_saw_it_oversized_roll_it_only_once(self):
        # The interleaving the lock is for: one writer is already past the size check when
        # another rolls.  Rolling again would put the fresh log where the kept generation
        # goes, unlink the generation, and leave the first writer holding nothing.
        import fcntl
        log, kept = watch.log_path(), watch.log_path().with_name(watch.LOG_KEPT)
        log.write_bytes(b"x" * (watch.LOG_MAX + 1))
        rolled = []
        with self.as_cron(), watch.log_lock_path().open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)        # the other writer is mid-roll
            other = threading.Thread(target=lambda: rolled.append(watch.rotate_log()))
            other.start()
            time.sleep(0.2)                         # ... and this one is waiting on the lock
            self.assertTrue(other.is_alive(), "the roll was not serialised")
            log.replace(kept)                       # what the other writer's roll comes to
            log.write_text("the other writer's fresh log\n")
            fcntl.flock(held, fcntl.LOCK_UN)
            other.join(timeout=10)
            self.assertEqual(rolled, [False])       # it looked again and left the log alone
            watch.tick_log("mine, after waiting for the lock")
        self.assertEqual(kept.stat().st_size, watch.LOG_MAX + 1)    # the generation survived
        self.assertEqual(log.read_text(), "the other writer's fresh log\n"
                                          "mine, after waiting for the lock\n")

    # --- a reinstall owns its line -------------------------------------------

    def test_a_reinstall_removes_a_commented_out_copy_of_its_own_line(self):
        live = ("*/3 * * * * PATH=/x /repo/bin/ak watch >>/ak/tmp/watch.log 2>&1 "
                "# agentkit watch")
        keep = "0 5 * * * /usr/bin/backup"
        for paused in (f"#{live}", f"# {live}", live.replace("# agentkit", "#agentkit"),
                       live.replace("# agentkit watch", "##  agentkit   watch")):
            with self.subTest(paused=paused):
                table, said = self.install_cron(f"{keep}\n{paused}\n")
                lines = table.strip().splitlines()
                self.assertEqual(len(lines), 2, table)
                self.assertEqual(lines[0], keep)
                self.assertIn("# agentkit watch", lines[1])
                self.assertFalse(lines[1].startswith("#"), lines[1])
                self.assertIn("every three minutes", said)

    def test_a_crontab_that_already_holds_only_the_live_line_is_left_as_it_is(self):
        table, _ = self.install_cron("")
        self.assertEqual(len(table.strip().splitlines()), 1, table)
        again, said = self.install_cron(table)
        self.assertEqual(again, table)
        self.assertIn("already installed", said)

    # --- a logged-out gh ------------------------------------------------------

    def test_a_logged_out_gh_skips_only_the_github_passes_and_says_one_line(self):
        self.stub_tick()
        self.gh.return_value = (None, "To get started with GitHub CLI, please run:  gh auth login")
        self.a_run("00-going", "atoll")
        self.a_run("01-merged", "beta", state="pass", merged=True)
        code, said = self.tick()
        self.assertEqual(code, 0)
        self.assertIn("gh is not logged in; PR checks skipped", said)
        self.incoming.assert_not_called()
        self.outgoing.assert_not_called()
        # everything else on the tick still ran, the browser tidy included
        self.tidy.assert_called_once()
        watch.health.assert_called_once()
        watch.recover_runs.assert_called_once()
        run.schedule_gc.assert_called_once()
        # and the seat whose run is waiting to push is told why, once gh is asked for
        self.assertEqual(watch.load_state()["gh_out"]["seats"], ["atoll"])
        blocked = self.seat_state("atoll")
        self.assertEqual(blocked["word"], "needs you")
        self.assertEqual(blocked["reason"], "gh login expired: run `gh auth login`")
        # its run is merged, so it pushes nothing more and hears nothing about gh
        self.assertNotIn("beta", watch.load_state()["gh_out"]["seats"])
        self.assertNotIn("gh login", self.seat_state("beta")["reason"])

    def test_only_the_runs_that_still_owe_github_a_push_put_the_word_on_their_seat(self):
        repo = str(self.root / "code")
        # A queued receipt carries what its preflight settled; one written before preflight
        # ran -- or by an install whose preflight did not settle it -- has only its options.
        held = {"going": dict(state="running", repo=repo, no_merge=False),
                "review": dict(state="running", repo=repo, no_merge=True,
                               review_pr="https://x/pull/1"),
                "retry": dict(state="pass", verdict="PASS", repo=repo, merge_failed=True),
                "queued": dict(state="queued", no_merge=False,
                               launch_opts={"--no-merge": False, "--bg": True}),
                "queued-bare": dict(state="queued",
                                    launch_opts={"--no-merge": False, "--bg": True})}
        clear = {"scratch": dict(state="running", repo=None, scratch=True, no_merge=True),
                 "local": dict(state="running", repo=repo, no_merge=True),
                 "merged": dict(state="pass", verdict="PASS", repo=repo, merged=True),
                 "maintainer": dict(state="pass", verdict="PASS", repo=repo, merge_failed=False,
                                    pr="https://x/pull/9"),
                 "failed": dict(state="fail", verdict="FAIL", repo=repo),
                 "queued-local": dict(state="queued", no_merge=True,
                                      launch_opts={"--no-merge": True, "--bg": True}),
                 # `repo: none` without --no-merge: the task decides, and preflight wrote it
                 "queued-scratch": dict(state="queued", no_merge=True,
                                        launch_opts={"--no-merge": False, "--bg": True}),
                 "queued-old": dict(state="queued", launch_opts={}),
                 "starting": dict(state="running", launch_opts={"--no-merge": True})}
        for number, (seat, receipt) in enumerate({**held, **clear}.items()):
            name = f"{number:02d}-{seat}"
            self.raw_run(name, {"run_id": name, "launched_session": seat, **receipt})
        self.assertEqual(watch.pushing_seats(), sorted(held))

    def test_a_launch_settles_what_it_will_deliver_before_it_waits_for_a_slot(self):
        """`repo: none` and `--no-merge` both push nothing, and the receipt has to say so.

        Only the process that launched the run can resolve the repository a task inherits
        when it names none, so the answer is written in its preflight, not by the loop that
        runs rounds later -- and `ak watch` reads the receipt all through the queue wait.
        """
        opts = {"--review-pr": None, "--no-merge": False, "--no-worktree": False,
                "--rounds": None, "--bg": False}
        for name, flag in (("asked-to-merge", False), ("told-not-to", True)):
            with self.subTest(name=name):
                directory = self.raw_run(f"q-{name}", {"run_id": f"q-{name}", "state": "queued",
                                                       "launched_session": name,
                                                       "launch_opts": {**opts, "--no-merge": flag}})
                (directory / "task.md").write_text(
                    "---\nrepo: none\nrounds: 1\n---\n# A queued job\n\n"
                    "## Done when\n```bash\ntrue\n```\n")
                run.save_state(directory, run.read_state(directory))   # silence and ceiling
                run.preflight(directory, {**opts, "--no-merge": flag}, lambda _: None)
                self.assertIs(run.read_state(directory)["no_merge"], True)
        # so the queue wait puts the word on nobody: neither of them will ever push
        self.assertEqual(watch.pushing_seats(), [])

    def test_a_malformed_receipt_cannot_take_the_logged_out_tick_down_with_it(self):
        self.stub_tick()
        self.gh.return_value = (None, "HTTP 401: Bad credentials (https://api.github.com/user)")
        self.a_run("00-going", "atoll")
        # everything retry_command reads, except the run id it then indexes the receipt by
        self.raw_run("01-no-id", {"state": "pass", "merge_failed": True, "repo": "/x",
                                  "launched_session": "beta"})
        self.raw_run("02-not-json", "{ half a receipt")
        self.raw_run("03-not-a-dict", "[]")
        code, said = self.tick()
        self.assertEqual(code, 0)
        self.assertIn("gh is not logged in", said)
        self.assertEqual(watch.load_state()["gh_out"]["seats"], ["atoll"])

    def test_a_github_that_is_merely_unavailable_is_not_a_login_to_fix(self):
        self.stub_tick()
        self.a_run("00-going", "atoll")
        for why in ("gh timed out", "gh: [Errno 2] No such file or directory: 'gh'",
                    "gh printed no JSON (Expecting value: line 1 column 1)",
                    "dial tcp: lookup api.github.com: no such host",
                    # a rate limit is a 403 answered to credentials that are perfectly good
                    "HTTP 403: API rate limit exceeded for user ID 1 "
                    "(https://api.github.com/user)"):
            with self.subTest(why=why):
                self.gh.return_value = (None, why)
                code, said = self.tick()
                self.assertEqual(code, 0)
                self.assertIn("WARN GitHub is unavailable; PR checks skipped", said)
                self.assertNotIn("gh is not logged in", said)
                self.incoming.assert_not_called()
                self.assertNotIn("gh_out", watch.load_state())
                self.assertNotIn("gh login", self.seat_state("atoll")["reason"])

    def test_a_gh_that_is_logged_in_again_clears_the_expiry_from_every_seat(self):
        self.stub_tick()
        self.gh.return_value = (None, "HTTP 401: Bad credentials (https://api.github.com/user)")
        self.a_run("00-going", "atoll")
        self.tick()
        self.assertIn("gh login expired", self.seat_state("atoll")["reason"])
        # an outage while it is expired can neither confirm the expiry nor clear it
        self.gh.return_value = (None, "gh timed out")
        self.tick()
        self.assertIn("gh login expired", self.seat_state("atoll")["reason"])
        self.gh.return_value = ({"login": "owner"}, "")
        self.tick()
        self.assertNotIn("gh_out", watch.load_state())
        self.assertNotIn("gh login", self.seat_state("atoll")["reason"])
        self.incoming.assert_called_once()

    # --- what --dry-run says about both ---------------------------------------

    def test_dry_run_prints_the_lock_state_and_the_log_size_beside_its_preview(self):
        self.stub_tick()
        watch.log_path().write_bytes(b"x" * (2 * 1024 * 1024))
        code, said = self.tick("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("lock free", said)
        self.assertIn("watch.log 2.0 MB of 5 MB", said)
        self.hold_the_lock(pid=77, since=time.time() - 4 * 60)
        code, said = self.tick("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("lock held by pid 77 for 4 min", said)
        # asking never takes the lock, and never creates one where no tick has run
        self.assertTrue(watch.tick_lock_path().exists())
        watch.tick_lock_path().unlink()
        self.assertIsNone(watch.tick_running())
        self.assertFalse(watch.tick_lock_path().exists())

    # --- a job whose launcher died --------------------------------------------

    def test_a_tick_relaunches_a_job_whose_launcher_died_once_and_a_dry_run_only_names_it(self):
        self.stub_tick()
        cfg = config.load()
        workers = cfg["defaults"]["workers"]
        config.save_session(cfg, "atoll", workers[0], workers[:1])
        job_dir = config.JOBS / "20260923-2000-job"
        job_dir.mkdir(parents=True)
        run.save_job(job_dir, {"job_id": job_dir.name, "seat": "atoll", "finished_at": None,
                               "started_at": time.time(), "pid": 99999999, "opts": {},
                               "cwd": str(self.root),
                               "tasks": [{"name": "a.md", "state": "queued", "after": [],
                                          "run_id": None}]})
        started = []

        def placed(argv, unit, env, output, **kwargs):
            # nothing starts: the launcher it hands back is this process, alive as long as
            # the test, so the next tick finds the job's launcher there
            kwargs["placement"].update(scope=unit)
            started.append(argv)
            return os.getpid()

        with patch.object(orch, "start_in_slice", side_effect=placed):
            code, said = self.tick("--dry-run")
            self.assertEqual(code, 0)
            self.assertIn(f"would relaunch job {job_dir.name}: launcher gone; session atoll "
                          "exists", said)
            self.assertEqual(started, [])
            code, said = self.tick()
            self.assertEqual(code, 0)
            self.assertIn(f"relaunched job {job_dir.name}: launcher gone", said)
            self.assertEqual(started, [[sys.executable, str(config.REPO / "bin" / "ak"),
                                        "run", "resume", job_dir.name]])
            # relaunched is alive: the next tick leaves it to itself
            code, said = self.tick()
            self.assertNotIn("relaunch", said)
            self.assertEqual(len(started), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
