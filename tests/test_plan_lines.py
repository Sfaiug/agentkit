"""`ak plan add` writes an outcome with the check that proves it, only when that check fails on
the project's default branch; `--eye` lines are ticked on the owner's word, check lines never by
hand.

Offline: a throwaway HOME, a local origin and checkout, and the check run there.
"""

from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, menu, notify, orch, plan, terminal, usage, watch


class PlanLines(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: "fix-api", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1"}))
        self.stack.enter_context(patch.object(plan.os, "killpg"))
        self.repo = config.CODE / "acme"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Plan test")
        self.git("config", "user.email", "plan@localhost")
        (self.repo / "base.txt").write_text("base\n")
        self.commit("base")
        self.origin = self.root / "origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.repo), str(self.origin)],
                       check=True, capture_output=True)
        self.git("remote", "add", "origin", str(self.origin))
        self.project = plan.named(self.repo)          # how a line names this project
        self.git("fetch", "-q", "origin")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("checkout", "-q", "-b", "work")
        (self.repo / "feature.txt").write_text("done\n")
        self.commit("the work, not on main")
        config.save_session(self.cfg, "fix-api", "opus", ["opus"],
                            {"cwd": str(self.root), "repo": str(self.repo)})

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-q", "-m", message)

    def ak(self, *args):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(plan.main(list(args)), 0)
        return out.getvalue()

    @contextmanager
    def recorder(self):
        """`ak notify done` through its plan's gate, recording nothing for real: what it would
        record is `sent`'s calls."""
        with patch.object(notify, "record") as sent, \
                patch.object(notify, "transition", return_value=0), \
                patch.object(watch, "seat_write"):
            yield sent

    def plan_lines(self):
        return config.plan_path("fix-api").read_text().splitlines()

    def test_a_check_failing_on_main_is_written_and_listed(self):
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        self.assertRegex(line, r"^- \[ \] the feature exists · check: `test -f feature.txt` · "
                               + re.escape(self.project) + r" · written \d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(self.plan_lines(), [line])
        with patch.object(terminal, "width", return_value=len(line) + 10):
            self.assertEqual(self.ak().strip(), f"1  {line}")
        self.assertTrue(plan.LINE.match(line))
        self.assertEqual(len(self.git("worktree", "list", "--porcelain").split("worktree ")) - 1, 1)

    def test_the_checkout_has_no_dirty_or_untracked_seat_files(self):
        (self.repo / "base.txt").write_text("dirty\n")
        (self.repo / "untracked.txt").write_text("seat only\n")
        with self.assertRaisesRegex(config.Error, "already passes"):
            self.ak("add", "clean base", "--check",
                    'test "$(cat base.txt)" = base && test ! -e untracked.txt && '
                    'test ! -e feature.txt')
        self.assertEqual((self.repo / "base.txt").read_text(), "dirty\n")
        self.assertTrue((self.repo / "untracked.txt").exists())

    def test_the_default_branch_is_refreshed_and_is_not_assumed_to_be_main(self):
        self.git("push", "-q", "origin", "work:trunk")
        subprocess.run(["git", "-C", str(self.origin), "symbolic-ref", "HEAD", "refs/heads/trunk"],
                       check=True, capture_output=True)
        with self.assertRaisesRegex(config.Error, "already passes"):
            self.ak("add", "already on trunk", "--check", "test -f feature.txt")

    def test_no_default_branch_or_failed_fetch_refuses_to_write(self):
        subprocess.run(["git", "-C", str(self.origin), "symbolic-ref", "HEAD", "refs/heads/missing"],
                       check=True, capture_output=True)
        with self.assertRaises(config.Error):
            self.ak("add", "unknown default", "--check", "false")
        subprocess.run(["git", "-C", str(self.origin), "symbolic-ref", "HEAD", "refs/heads/main"],
                       check=True, capture_output=True)
        self.git("remote", "set-url", "origin", str(self.root / "no-repo"))
        with self.assertRaises(config.Error):
            self.ak("add", "unreadable default", "--check", "false")
        self.assertFalse(config.plan_path("fix-api").exists())

    def test_a_check_passing_on_main_proves_nothing_and_is_refused(self):
        with self.assertRaisesRegex(config.Error, "already passes on acme's default branch"):
            plan.main(["add", "the base exists", "--check", "test -f base.txt"])
        self.assertFalse(config.plan_path("fix-api").exists())
        with self.assertRaisesRegex(config.Error, "without backticks"):
            plan.main(["add", "quoted", "--check", "test `true`"])

    def test_the_check_runs_without_the_seats_variables(self):
        names = {config.SESSION_ENV, "AK_PARENT_RUN", "IDLE_COMPACT_STATE",
                 *config.seat_env_names()}
        with patch.dict(os.environ, {name: "fix-api" for name in names}):
            for name in sorted(names):
                with self.subTest(name=name):
                    self.ak("add", "only a seat would see it", "--check", f'test -n "${name}"')
        self.assertEqual(len(self.plan_lines()), len(names))

    def test_shell_startup_cannot_restore_seat_variables(self):
        startup = self.root / "startup.sh"
        startup.write_text("AGENTKIT_SESSION=fix-api\n")
        with patch.dict(os.environ, {"BASH_ENV": str(startup)}):
            self.ak("add", "only a seat would see it", "--check", 'test -n "$AGENTKIT_SESSION"')

    def test_git_variables_cannot_redirect_the_check_to_the_seats_checkout(self):
        with patch.dict(os.environ, {"GIT_DIR": str(self.repo / ".git"),
                                     "GIT_WORK_TREE": str(self.repo)}):
            with self.assertRaisesRegex(config.Error, "already passes"):
                self.ak("add", "clean branch", "--check", "git diff --quiet main HEAD")

    def test_a_check_is_not_rewritten_or_accepted_when_it_never_finishes(self):
        with self.assertRaisesRegex(config.Error, "one shell command"):
            self.ak("add", "multiple commands", "--check", "test -f feature.txt\ntrue")
        real_popen = subprocess.Popen
        with patch.object(plan.subprocess, "Popen") as popen, \
                patch.object(plan.os, "killpg") as kill:
            proc = popen.return_value
            popen.side_effect = lambda args, **kw: (proc if args[0] == "bash"
                                                   else real_popen(args, **kw))
            proc.pid = 123456789
            proc.wait.side_effect = [subprocess.TimeoutExpired("check", 600), 0]
            with self.assertRaisesRegex(config.Error, "did not finish"):
                self.ak("add", "an unfinished check proves nothing", "--check", "false")
            kill.assert_called_once_with(proc.pid, signal.SIGKILL)
        self.assertFalse(config.plan_path("fix-api").exists())
        self.assertEqual(len(self.git("worktree", "list", "--porcelain").split("worktree ")) - 1, 1)

    def test_sigterm_cleans_the_checkout_and_check_before_ending_the_command(self):
        previous = signal.getsignal(signal.SIGTERM)
        real_popen, real_run = subprocess.Popen, subprocess.run
        for stage in ("checkout", "check"):
            with self.subTest(stage=stage), patch.object(plan.subprocess, "Popen") as popen, \
                    patch.object(plan.subprocess, "run") as run, \
                    patch.object(plan.os, "killpg") as kill:
                proc = popen.return_value
                proc.pid = 123456789
                popen.side_effect = lambda args, **kw: (proc if args[0] == "bash"
                                                       else real_popen(args, **kw))

                def terminate():
                    signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

                def git(args, **kw):
                    result = real_run(args, **kw)
                    if stage == "checkout" and "add" in args:
                        terminate()
                    if "remove" in args:
                        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_IGN)
                    return result

                def wait(timeout=None, **_kw):
                    if timeout is not None:
                        terminate()
                    return 0

                run.side_effect, proc.wait.side_effect = git, wait
                with self.assertRaises(SystemExit) as ended:
                    self.ak("add", "an interrupted check proves nothing", "--check", "false")
                self.assertEqual(ended.exception.code, 128 + signal.SIGTERM)
                if stage == "check":
                    kill.assert_called_once_with(proc.pid, signal.SIGKILL)
                    self.assertEqual(proc.wait.call_count, 2)
                self.assertFalse(config.plan_path("fix-api").exists())
                self.assertEqual(list(config.TMP.glob("plan-*")), [])
                self.assertEqual(len(self.git("worktree", "list", "--porcelain")
                                     .split("worktree ")) - 1, 1)
                self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_an_eye_line_is_ticked_on_the_owners_word_and_a_check_line_never_by_hand(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        eye = self.ak("add", "the hero looks calm", "--eye").strip()
        self.assertIn(f" · your eye · {self.project} · written ", eye)
        with self.assertRaisesRegex(config.Error, "only a --eye line"):
            plan.main(["tick", "1"])
        ticked = self.ak("tick", "2").strip()
        self.assertRegex(ticked, r"^- \[x\] the hero looks calm · your eye · " + re.escape(self.project) + r" · written .+"
                                 r" · done your yes \d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(plan.LINE.match(ticked)["done"][:8], "your yes")
        with self.assertRaisesRegex(config.Error, "already done"):
            plan.main(["tick", "2"])
        with self.assertRaisesRegex(config.Error, "no plan line 3"):
            plan.main(["tick", "3"])

    def test_a_malformed_line_cannot_bypass_the_check_lines_tick_refusal(self):
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        for text in (line + " · unexpected", "- [ ] old unchecked outcome"):
            with self.subTest(text=text):
                config.plan_path("fix-api").write_text(text + "\n")
                with self.assertRaisesRegex(config.Error, "only a --eye line"):
                    self.ak("tick", "1")
                self.assertEqual(self.plan_lines(), [text])

    def test_numbered_lines_wrap_to_the_terminal_width(self):
        self.ak("add", "a calm hero", "--eye")
        self.ak("add", "a clear footer", "--eye")
        with patch.object(terminal, "width", return_value=40):
            listing = self.ak().splitlines()
        self.assertTrue(all(terminal.cells(line) <= 40 for line in listing), listing)
        self.assertIn("your eye", " ".join(listing))
        self.assertEqual([line.split()[0] for line in listing if re.match(r"\s*\d+\s+- \[", line)],
                         ["1", "2"])

    def listed(self):
        with patch.object(terminal, "width", return_value=400):
            return self.ak()

    def land_the_work(self):
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--ff-only", "work")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "work")

    def test_a_check_line_ticks_itself_once_its_check_passes_on_the_default_branch(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.assertIn("1  - [ ] the feature exists", self.listed())     # main lacks it still
        self.land_the_work()
        head = self.git("log", "-1", "--format=%h %s", "--abbrev=12", "main")
        self.assertRegex(self.listed().strip(), r"^1  - \[x\] the feature exists · check: "
                         r"`test -f feature.txt` · " + re.escape(self.project) + r" · written .+ · done " + re.escape(head) + "$")

    def test_done_waits_for_every_line_and_a_hand_tick_proves_nothing(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.ak("add", "the hero looks calm", "--eye")
        path = config.plan_path("fix-api")
        path.write_text(path.read_text().replace("- [ ] the feature", "- [x] the feature"))
        with self.recorder() as sent:
            with self.assertRaisesRegex(config.Error, r"2 plan line\(s\) still open, first: "
                                                      r"- \[ \] the feature exists"):
                notify.main(["done", "Shipped"])
            self.land_the_work()
            with self.assertRaisesRegex(config.Error, r"1 plan line\(s\) still open, first: "
                                                      r"- \[ \] the hero looks calm"):
                notify.main(["done", "Shipped"])
            self.ak("tick", "2")
            self.assertEqual(notify.main(["done", "Shipped"]), 0)
            self.assertEqual(notify.main(["done", "Shipped", "--dry-run"]), 0)
        self.assertEqual(sent.call_count, 1)            # the dry run records nothing
        self.assertEqual([plan.is_open(line) for line in self.plan_lines()], [False, False])

    def test_done_runs_every_check_again_and_reopens_what_fails_today(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.land_the_work()
        self.ak()
        path = config.plan_path("fix-api")
        path.write_text(path.read_text() + "- [x] the extra exists · check: `test -f extra.txt` · "
                        f"{self.project} · written 2026-10-03 09:00 · done 0123456789ab claimed\n")
        with self.assertRaisesRegex(config.Error, r"1 plan line\(s\) still open, first: "
                                                  r"- \[ \] the extra exists"):
            plan.require_done("fix-api")
        self.git("checkout", "-q", "main")
        self.git("rm", "-q", "feature.txt")
        self.commit("main loses the feature again")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "work")
        with self.assertRaisesRegex(config.Error, r"2 plan line\(s\) still open, first: "
                                                  r"- \[ \] the feature exists"):
            plan.require_done("fix-api")

    def test_each_check_starts_from_the_default_branch_never_from_anothers_files(self):
        self.ak("add", "the feature exists", "--check", "touch generated.txt; test -f feature.txt")
        self.ak("add", "something generated", "--check", "test -f generated.txt")
        listed = self.listed()
        self.assertIn("1  - [ ] the feature exists", listed)
        self.assertIn("2  - [ ] something generated", listed)     # never off the first's file

    def test_a_ticked_line_this_host_cannot_check_is_open_for_done(self):
        path = config.plan_path("fix-api")
        path.write_text("- [x] the remote is up · check: `true` · gone-project · written "
                        "2026-10-03 09:00 · done 0123456789ab once\n")
        with self.assertRaisesRegex(config.Error, r"1 plan line\(s\) still open, first: "
                                                  r"- \[ \] the remote is up"):
            plan.require_done("fix-api")

    def test_a_line_added_while_the_checks_run_is_kept(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.land_the_work()
        fails = plan.fails

        def meanwhile(*args):
            # another `ak plan add` writes while this check runs
            path = config.plan_path("fix-api")
            path.write_text(path.read_text() + f"- [ ] added meanwhile · your eye · {self.project} · "
                            "written 2026-10-04 21:00\n")
            return fails(*args)

        with patch.object(plan, "fails", side_effect=meanwhile):
            self.ak()
        text = self.plan_lines()
        self.assertTrue(text[0].startswith("- [x] the feature exists"))
        self.assertEqual(text[1], f"- [ ] added meanwhile · your eye · {self.project} · written 2026-10-04 21:00")

    def test_an_add_from_another_process_during_the_checks_is_kept(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.land_the_work()
        fails, writers = plan.fails, []
        add = ("import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
               "from agentkit import config, plan; "
               "[setattr(config, key, Path(value)) for key, value in json.loads(sys.argv[2]).items()]; "
               "plan.add('fix-api', 'added meanwhile')")
        places = json.dumps({key: str(getattr(config, key)) for key in
                             ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE")})

        def meanwhile(*args):
            # a seat's `ak plan add` in another process, racing this listing's write-back
            writers.append(subprocess.Popen([sys.executable, "-c", add, str(REPO), places]))
            return fails(*args)

        with patch.object(plan, "fails", side_effect=meanwhile):
            self.ak()
        for writer in writers:
            self.assertEqual(writer.wait(30), 0)
        text = self.plan_lines()
        self.assertTrue(text[0].startswith("- [x] the feature exists"))
        self.assertEqual(len(text), 2)
        self.assertIn(f"added meanwhile · your eye · {self.project}", text[1])

    def test_moving_head_or_a_submodule_never_carries_to_the_next_check(self):
        source = self.root / "sub-source"
        source.mkdir()
        for args in (("init", "-q", "-b", "main"), ("config", "user.name", "Plan test"),
                     ("config", "user.email", "plan@localhost"),
                     ("commit", "-q", "--allow-empty", "-m", "base")):
            subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
        self.git("checkout", "-q", "main")
        self.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), "sub")
        self.commit("with a submodule")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "work")
        self.ak("add", "the extra exists", "--check",
                "git checkout -q --detach work; test -f extra.txt")
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.ak("add", "the sub feature exists", "--check",
                "git -c protocol.file.allow=always submodule update --init -q; "
                "touch sub/generated.txt; test -f feature.txt")
        self.ak("add", "something generated", "--check", "test -f sub/generated.txt")
        self.listed()
        self.assertEqual([line[:5] for line in self.plan_lines()], ["- [ ]"] * 4)

    def test_a_workers_done_is_suppressed_before_any_check_runs(self):
        marker = self.root / "check-ran"
        self.ak("add", "the feature exists", "--check", f"touch {marker}; test -f feature.txt")
        marker.unlink()
        before = config.plan_path("fix-api").read_bytes()
        with patch.dict(os.environ, {"AK_RUN_ROLE": "worker", "AK_RUN_LOG": "",
                                     config.SESSION_ENV: ""}), redirect_stdout(io.StringIO()):
            self.assertEqual(notify.main(["done", "a worker's result", "--session", "fix-api"]), 0)
        self.assertFalse(marker.exists())
        self.assertEqual(config.plan_path("fix-api").read_bytes(), before)

    def test_renaming_back_keeps_the_plan_the_seat_wrote_last(self):
        config.plan_path("fix-api").write_text("- [x] an older outcome\n")
        config.rename_session("fix-api", "fix-api-2")
        os.utime(config.plan_path("fix-api-2"), (1, 1))
        latest = "- [ ] the newly required outcome\n"
        config.plan_path("fix-api").write_text(latest)  # still written under its launch name
        self.assertEqual(watch.plan_text("fix-api-2"), latest)
        config.rename_session("fix-api-2", "fix-api")
        self.assertEqual(watch.plan_text("fix-api"), latest)

    def test_a_handover_names_the_plan_the_seat_wrote_last(self):
        config.plan_path("fix-api").write_text("- [x] an older outcome\n")
        config.rename_session("fix-api", "fix-api-2")
        os.utime(config.plan_path("fix-api-2"), (1, 1))
        config.plan_path("fix-api").write_text("- [ ] the newly required outcome\n")
        self.assertIn(f"The seat's plan is at {config.plan_path('fix-api')}.",
                      orch.handover_text("fix-api-2", "opus", None))

    def test_a_handover_names_a_plan_it_cannot_read_rather_than_failing(self):
        private = self.root / "private-plan"
        private.mkdir()
        (private / "plan.md").write_text("- [ ] an outcome\n")
        config.plan_path("fix-api").symlink_to(private / "plan.md")
        private.chmod(0)
        self.addCleanup(private.chmod, 0o700)
        text = orch.handover_text("fix-api", "opus", None)
        self.assertIn("The seat's plan cannot be read", text)
        self.assertIn("ak run status", text)

    def gone_seat_with_plans(self):
        """fix-api, renamed to ship-api and back: its older plan stays under ship-api, a name
        still leading to it, and its newer one under fix-api."""
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": str(self.root)})
        config.plan_path("fix-api").write_text("- [ ] the gone seat's outcome\n")
        config.rename_session("fix-api", "ship-api")
        config.plan_path("fix-api").write_text("- [ ] the gone seat's later outcome\n")
        config.rename_session("ship-api", "fix-api")
        self.assertTrue(config.plan_path("ship-api").exists())

    def test_a_new_seat_under_a_used_name_starts_without_a_plan(self):
        # under its own name, and under a name a pointer still leads to it from
        self.gone_seat_with_plans()
        with patch.object(usage, "collect", return_value={}), \
                patch.object(orch, "launch"), redirect_stdout(io.StringIO()):
            orch.create(self.cfg, "fix-api", self.root, forced="astra", forced_workers="opus")
        self.assertEqual(watch.plan_text("fix-api"), "")

    def test_a_seat_renamed_into_a_freed_name_starts_without_a_plan(self):
        self.gone_seat_with_plans()
        config.session_path("fix-api").unlink()        # retired: record and pointer gone
        config.session_path("ship-api").unlink()
        config.save_session(self.cfg, "newer", "opus", ["opus"], {"cwd": str(self.root)})
        for name in ("ship-api", "fix-api"):
            with self.subTest(name=name):
                config.rename_session(config.resolve_session("newer"), name)
                self.assertEqual(watch.plan_text(name), "")

    def test_rename_during_done_keeps_all_requirements(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.ak("add", "the hero looks calm", "--eye")
        fails = plan.fails
        checked = []
        def meanwhile(*args):
            result = fails(*args)
            checked.append(result)
            config.rename_session("fix-api", "fix-api-renamed")
            return result
        error = None
        with patch.object(plan, "fails", side_effect=meanwhile), \
                self.recorder() as sent, \
                redirect_stdout(io.StringIO()):
            try:
                notify.main(["done", "Shipped"])
            except config.Error as exc:
                error = str(exc)
        current = config.resolve_session("fix-api")
        saved = plan.lines(current)
        self.assertEqual(len(saved), 2,
                         "done lost the renamed plan; saved=" + repr(saved) +
                         "; failed checks=" + repr(checked) + "; error=" + repr(error) +
                         "; notifications=" + str(sent.call_count))
        self.assertIn("the hero looks calm", "\n".join(saved))

    def listing(self, call="raise SystemExit(plan.main([]))"):
        """`ak plan` -- or another plan call -- in a process of its own, as another terminal."""
        places = json.dumps({key: str(getattr(config, key)) for key in
                             ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE")})
        child = ("import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                 "from agentkit import config, plan; "
                 "[setattr(config, k, Path(v)) for k, v in json.loads(sys.argv[2]).items()]; "
                 + call)
        writer = subprocess.Popen([sys.executable, "-c", child, str(REPO), places],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: writer.poll() is None and (writer.kill(), writer.communicate()))
        return writer

    def gate(self):
        """A check that holds while the feature is there until released, and its two files."""
        ready, release = self.root / "ready", self.root / "release"
        self.addCleanup(release.touch)
        return ready, release, ("if test -f feature.txt; then touch " + str(ready) +
                                "; while test ! -f " + str(release) +
                                "; do sleep 0.01; done; fi; test -f feature.txt")

    def lose_the_feature(self):
        self.git("checkout", "-q", "main")
        self.git("rm", "-q", "feature.txt")
        self.commit("main loses the feature")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "work")

    def test_a_listing_started_while_done_checks_waits_and_runs_on_main_as_it_is_then(self):
        ready, release, command = self.gate()
        self.ak("add", "the feature exists", "--check", command)
        self.land_the_work()
        branch, writer = plan.default_branch, []

        def started(repo):
            if not writer:                  # done has its plan; a listing starts meanwhile
                writer.append(self.listing())
                time.sleep(1)
                self.assertIsNone(writer[0].poll(), "the listing ran beside done")
                self.lose_the_feature()
            return branch(repo)

        with patch.object(plan, "default_branch", side_effect=started), \
                self.recorder() as sent, \
                self.assertRaisesRegex(config.Error, "still open"):
            notify.main(["done", "Shipped"])
        sent.assert_not_called()
        out, err = writer[0].communicate(timeout=30)
        self.assertEqual(writer[0].returncode, 0, out + err)
        self.assertFalse(ready.exists(), "the listing checked the main done had already left")
        self.assertTrue(self.plan_lines()[0].startswith("- [ ]"))

    def test_an_older_listing_never_lands_over_a_newer_done(self):
        ready, release, command = self.gate()
        self.ak("add", "the feature exists", "--check", command)
        self.land_the_work()
        writer = self.listing()             # it holds on main with the feature
        deadline = time.monotonic() + 15
        while not ready.exists() and writer.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready.exists(), "the listing did not reach its check")
        self.lose_the_feature()
        # done, after it: it waits for the listing, then checks the newer main
        later = self.listing("plan.require_done('fix-api')")
        time.sleep(1)
        self.assertIsNone(later.poll(), "done ran beside the listing")
        release.touch()
        out, err = writer.communicate(timeout=30)
        self.assertEqual(writer.returncode, 0, out + err)
        out, err = later.communicate(timeout=60)
        self.assertIn("still open", err)
        self.assertTrue(self.plan_lines()[0].startswith("- [ ]"))

    def test_a_rename_during_the_first_read_cannot_skip_a_failing_check(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.land_the_work()
        self.ak()                                         # ticked on the older main
        self.git("checkout", "-q", "main")
        self.git("rm", "-q", "feature.txt")
        self.commit("main loses the feature")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "work")
        aliases, renamed = config.session_aliases, []

        def rename_during_lookup():
            if not renamed:
                renamed.append(True)
                config.rename_session("fix-api", "fix-api-renamed")
            return aliases()

        with patch.object(config, "session_aliases", side_effect=rename_during_lookup), \
                self.recorder() as sent, \
                self.assertRaisesRegex(config.Error, "still open"):
            notify.main(["done", "Shipped"])
        sent.assert_not_called()

    def test_a_writer_waiting_through_a_rename_writes_to_the_renamed_plan(self):
        self.ak("add", "initial requirement", "--eye")
        places = json.dumps({key: str(getattr(config, key)) for key in
                             ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE")})
        add = ("import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
               "from agentkit import config, plan; "
               "[setattr(config, k, Path(v)) for k, v in json.loads(sys.argv[2]).items()]; "
               "plan.add('fix-api', 'queued before the rename')")
        with notify.session_lock("fix-api"):              # a rename holds the seat's lock
            writer = subprocess.Popen([sys.executable, "-c", add, str(REPO), places])
            time.sleep(1)                                 # the writer waits on it
            config.rename_session("fix-api", "fix-api-renamed")
        self.assertEqual(writer.wait(30), 0)
        text = "\n".join(plan.lines("fix-api-renamed"))
        self.assertIn("initial requirement", text)
        self.assertIn("queued before the rename", text)

    def test_a_hand_ticked_check_line_that_does_not_parse_is_open(self):
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        ticked = line.replace("- [ ]", "- [x]", 1)
        for edited in (ticked + " · unexpected", ticked.replace("check: `", "check:  `"),
                       ticked.replace("check: `", "check :`"),
                       ticked.replace(" · check: `test -f feature.txt`", ""),
                       ticked.replace("- [x]", "- [X]", 1), ticked.replace("- [x]", "-  [x]", 1),
                       ticked.replace("- [x]", "-\t[x]", 1), ticked.replace("- [x]", "* [x]", 1),
                       ticked.replace("- [x]", "1. [x]", 1), "  " + ticked.replace("- [x]", "-  [x]", 1),
                       line.replace("- [ ]", "-  [ ]", 1), line.replace("- [ ]", "- [  ]", 1),
                       line.replace("- [ ]", "- []", 1), ticked.replace("- [x]", "- [xx]", 1),
                       ticked.replace("- [x]", "- [done]", 1), ticked.replace("- [x]", "- [✔️]", 1)):
            with self.subTest(edited=edited):
                config.plan_path("fix-api").write_text(edited + "\n")
                with self.recorder() as sent, \
                        self.assertRaisesRegex(config.Error, "still open"):
                    notify.main(["done", "Shipped"])
                sent.assert_not_called()

    def test_a_renamed_plan_nothing_can_look_at_never_counts_as_done(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        config.rename_session("fix-api", "fix-api-renamed")
        private = self.root / "private-plan"
        private.mkdir()
        saved = private / "plan.md"
        config.plan_path("fix-api-renamed").replace(saved)
        config.plan_path("fix-api").symlink_to(saved)    # the old name's plan, out of reach
        private.chmod(0)
        self.addCleanup(private.chmod, 0o700)
        with self.recorder() as sent, \
                self.assertRaisesRegex(config.Error, "cannot read the plan"):
            notify.main(["done", "Shipped"])
        sent.assert_not_called()

    def test_a_verifier_started_inside_a_rename_waits_for_the_one_before_it(self):
        ready, release, command = self.gate()
        self.ak("add", "the feature exists", "--check", command)
        self.land_the_work()
        older = self.listing()             # it holds on main with the feature
        deadline = time.monotonic() + 15
        while not ready.exists() and older.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready.exists(), "the listing did not reach its check")
        self.lose_the_feature()
        entered = self.root / "entered"
        moved_lock, replace, newer = config.seat_file("verify", "fix-api"), Path.replace, []

        def during_move(source, target):
            # the new name is out, the old name's lock not yet moved: done starts now
            if source == moved_lock and not newer:
                newer.append(self.listing(
                    "original = plan._verify_held\n"
                    "def entering(*args):\n"
                    f"    Path({str(entered)!r}).touch()\n"
                    "    return original(*args)\n"
                    "plan._verify_held = entering\n"
                    "plan.require_done('fix-api')"))
                time.sleep(1)
                self.assertFalse(entered.exists(), "done ran beside the listing")
            return replace(source, target)

        with notify.session_lock("fix-api"), notify.session_lock("fix-api-renamed"), \
                patch.object(Path, "replace", during_move):
            config.rename_session("fix-api", "fix-api-renamed")
        self.assertTrue(newer, "the rename moved no verification lock")
        time.sleep(1)
        self.assertFalse(entered.exists(), "done ran beside the listing")
        release.touch()
        out, err = older.communicate(timeout=30)
        self.assertEqual(older.returncode, 0, out + err)
        out, err = newer[0].communicate(timeout=60)
        self.assertIn("still open", err)
        self.assertTrue(plan.lines("fix-api-renamed")[0].startswith("- [ ]"))

    def test_an_eye_line_needs_no_origin(self):
        self.git("remote", "remove", "origin")
        line = self.ak("add", "the hero looks calm", "--eye").strip()
        self.assertIn(f" · {self.project} · written ", line)

    def test_a_check_line_added_while_done_checks_is_proved_by_nobody(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.land_the_work()
        fails, added = plan.fails, []

        def meanwhile(*args):
            failed = fails(*args)
            if not added:                  # done has read its plan; another writer adds a line
                added.append(True)
                self.ak("add", "the extra exists", "--check", "test -f extra.txt")
            return failed

        with patch.object(plan, "fails", side_effect=meanwhile), \
                self.recorder() as sent, \
                self.assertRaisesRegex(config.Error, "the extra exists"):
            notify.main(["done", "Shipped"])
        sent.assert_not_called()

    def test_a_line_added_before_done_is_recorded_refuses_it(self):
        self.ak("add", "initial requirement", "--eye")
        self.ak("tick", "1")
        lock, added = notify.session_lock, []

        @contextmanager
        def add_first(name, *args, **kwargs):
            # the plan's checks are over; a writer gets in before done takes the lock to record
            if not added and sys._getframe(2).f_code.co_name == "shaped":
                added.append(True)
                self.ak("add", "new required outcome", "--eye")
            with lock(name, *args, **kwargs) as current:
                yield current

        with patch.object(notify, "session_lock", side_effect=add_first), \
                patch.object(menu, "run_records", return_value=[]), \
                patch.object(watch, "seat_write"), \
                patch.object(notify, "transition", return_value=0), \
                self.assertRaisesRegex(config.Error, "new required outcome"):
            notify.main(["done", "Shipped"])
        self.assertTrue(added)
        self.assertIsNone(notify.last("fix-api"))

    def other_acme(self, has_feature):
        """A second checkout named acme, with an origin of its own, filed under a seat."""
        other = self.root / "other-owner" / "acme"
        other.mkdir(parents=True)
        for args in (("init", "-q", "-b", "main"), ("config", "user.name", "Plan test"),
                     ("config", "user.email", "plan@localhost")):
            subprocess.run(["git", "-C", str(other), *args], check=True)
        (other / ("feature.txt" if has_feature else "other.txt")).write_text("another project\n")
        subprocess.run(["git", "-C", str(other), "add", "."], check=True)
        subprocess.run(["git", "-C", str(other), "commit", "-qm", "another project"], check=True)
        remote = self.root / "other-origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(other), str(remote)], check=True)
        subprocess.run(["git", "-C", str(other), "remote", "add", "origin", str(remote)], check=True)
        config.save_session(self.cfg, "z-other", "opus", ["opus"],
                            {"cwd": str(other), "repo": str(other)})

    def test_a_line_from_outside_the_code_directory_stays_on_its_checkout(self):
        # written from a checkout no name of ak's covers, then the seat is filed under
        # another checkout of that name whose main already has the feature
        original = self.root / "first-owner" / "acme"
        original.parent.mkdir()
        self.repo.rename(original)
        self.repo = original
        config.save_session(self.cfg, "fix-api", "opus", ["opus"],
                            {"cwd": str(original), "repo": str(original)})
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        self.assertIn(f" · {plan.named(original)} · written ", line)
        self.other_acme(has_feature=True)
        other = self.root / "other-owner" / "acme"
        config.save_session(self.cfg, "fix-api", "opus", ["opus"],
                            {"cwd": str(other), "repo": str(other)})
        self.listed()
        self.assertTrue(self.plan_lines()[0].startswith("- [ ]"))
        with self.assertRaisesRegex(config.Error, "still open"):
            plan.require_done("fix-api")

    def test_a_line_names_the_checkout_it_was_written_under(self):
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        self.assertIn(f" · {self.project} · written ", line)
        self.other_acme(has_feature=True)            # a seat filed under another acme
        self.listed()
        self.assertTrue(self.plan_lines()[0].startswith("- [ ]"))

    def test_a_line_naming_its_checkout_by_name_runs_in_the_seat_s_checkout_of_that_name(self):
        # written before lines named a path
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        config.plan_path("fix-api").write_text(line.replace(f" · {self.project} · ", " · acme · ") + "\n")
        self.land_the_work()
        self.listed()
        self.assertTrue(self.plan_lines()[0].startswith("- [x]"))

    def test_a_name_another_checkout_shares_is_checked_in_the_seat_s_own(self):
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        config.plan_path("fix-api").write_text(line.replace(f" · {self.project} · ", " · acme · ") + "\n")
        self.other_acme(has_feature=True)           # another acme, with an origin of its own
        self.listed()
        self.assertTrue(self.plan_lines()[0].startswith("- [ ]"))
        with self.assertRaisesRegex(config.Error, "still open"):
            plan.require_done("fix-api")

    def test_another_repository_at_the_checkout_s_old_path_proves_nothing(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        moved = self.root / "moved" / "acme"
        moved.parent.mkdir()
        self.repo.rename(moved)
        config.save_session(self.cfg, "fix-api", "opus", ["opus"],
                            {"cwd": str(moved), "repo": str(moved)})
        # another project, whose main has the feature, where the checkout was
        other = self.root / "other-owner" / "acme"
        self.other_acme(has_feature=True)
        other.rename(self.repo)
        config.save_session(self.cfg, "fix-api", "opus", ["opus"],
                            {"cwd": str(moved), "repo": str(moved)})
        self.listed()
        self.assertTrue(self.plan_lines()[0].startswith("- [ ]"))

    def test_lines_alike_are_one_check_and_share_its_result(self):
        # a check that fails the first time it runs and passes after
        counter = self.root / "check-runs"
        command = f"echo run >> {counter}; test $(wc -l < {counter}) -gt 1"
        self.ak("add", "the feature exists", "--check", command)
        line = self.plan_lines()[0]
        config.plan_path("fix-api").write_text(line + "\n" + line + "\n")
        counter.unlink()
        with self.assertRaisesRegex(config.Error, "still open"):
            plan.require_done("fix-api")
        self.assertEqual(counter.read_text().count("run"), 1)
        self.assertTrue(all(row.startswith("- [ ]") for row in self.plan_lines()))

    def test_a_line_naming_its_checkout_by_name_is_proven_after_the_seat_is_renamed(self):
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        config.plan_path("fix-api").write_text(line.replace(f" · {self.project} · ", " · acme · ") + "\n")
        self.land_the_work()
        config.rename_session("fix-api", "fix-api-renamed")
        plan.require_done("fix-api")               # the name it was launched under still reaches it

    def test_every_done_waits_for_the_plan_whoever_declares_it(self):
        # a finished job declares its seat's done too, through the same door
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        with self.recorder() as sent, self.assertRaisesRegex(notify.Refused, "still open"):
            notify.shaped("done", "job x: all 2 tasks finished", session="fix-api",
                          event_id="job:x:1")
        sent.assert_not_called()

    def test_a_checkout_with_another_branch_out_still_proves_its_line(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.land_the_work()
        self.git("checkout", "-q", "--orphan", "gh-pages")      # a root of its own
        self.listed()
        self.assertTrue(self.plan_lines()[0].startswith("- [x]"))

    def test_an_eye_line_ticked_by_hand_is_open_until_the_owner_s_yes(self):
        line = self.ak("add", "the hero looks calm", "--eye").strip()
        ticked = line.replace("- [ ]", "- [x]", 1)
        for edited in (ticked, ticked.split(" · written ")[0]):
            with self.subTest(edited=edited):
                config.plan_path("fix-api").write_text(edited + "\n")
                with self.recorder() as sent, self.assertRaisesRegex(config.Error, "still open"):
                    notify.main(["done", "Shipped"])
                sent.assert_not_called()

    def test_the_seat_is_looked_up_under_the_lock_a_rename_takes(self):
        found = []
        with notify.session_lock("fix-api"):            # a rename holds it
            looking = threading.Thread(target=lambda: found.append(plan.project_of("fix-api")))
            looking.start()
            time.sleep(0.5)
            self.assertTrue(looking.is_alive(), "the lookup ran beside the rename")
            config.rename_session("fix-api", "fix-api-renamed")
        looking.join(10)
        self.assertEqual(found, [self.repo])

    def test_an_eye_line_needs_the_owner_s_yes_and_any_written_field_is_ak_s(self):
        eye = self.ak("add", "the hero looks calm", "--eye").strip().replace("- [ ]", "- [x]", 1)
        for edited in (eye + " · done pending", eye + " · done 0123456789ab claimed",
                       "- [x] the hero looks calm · written yesterday"):
            with self.subTest(edited=edited):
                config.plan_path("fix-api").write_text(edited + "\n")
                with self.recorder() as sent, self.assertRaisesRegex(config.Error, "still open"):
                    notify.main(["done", "Shipped"])
                sent.assert_not_called()

    def test_a_check_run_in_another_repository_s_tree_proves_nothing(self):
        # the checkout is swapped for another project's between the lookup and the check
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.other_acme(has_feature=True)
        other, branch = self.root / "other-owner" / "acme", plan.default_branch
        with patch.object(plan, "default_branch", side_effect=lambda repo: branch(other)):
            self.listed()
        self.assertTrue(self.plan_lines()[0].startswith("- [ ]"))

    def test_a_remote_changed_to_another_repository_never_ticks_the_line(self):
        # its main is fetched into the same objects, the recorded root still among them
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        self.other_acme(has_feature=True)
        self.git("remote", "set-url", "origin", str(self.root / "other-origin.git"))
        self.listed()
        self.assertTrue(self.plan_lines()[0].startswith("- [ ]"))

    def test_a_rename_back_to_an_earlier_name_holds_that_name_until_its_files_follow(self):
        config.rename_session("fix-api", "fix-api-2")       # fix-api is now an old name
        renaming, real = threading.Event(), config.rename_session
        got = threading.Event()

        def writer():
            with notify.session_lock("fix-api"):
                got.set()

        def moved(old, new):
            real(old, new)
            # the record is back at fix-api: a writer reaching that name waits out the rename
            threading.Thread(target=writer, daemon=True).start()
            renaming.set()
            self.assertFalse(got.wait(0.5), "a writer took fix-api while the rename moved it")

        with patch.object(config, "rename_session", side_effect=moved), \
                patch.object(orch, "find", return_value={"name": "fix-api-2"}), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "title_record", return_value={}):
            orch.rename("fix-api-2", "fix-api", log=lambda _line: None)
        self.assertTrue(renaming.is_set())
        self.assertTrue(got.wait(10))                       # and takes it once the rename is done
        self.assertEqual(config.resolve_session("fix-api-2"), "fix-api")

    def test_an_eye_line_reopened_by_hand_is_ticked_with_one_yes(self):
        self.ak("add", "the hero looks calm", "--eye")
        self.ak("tick", "1")
        path = config.plan_path("fix-api")
        path.write_text(path.read_text().replace("- [x]", "- [ ]", 1))
        ticked = self.ak("tick", "1").strip()
        self.assertEqual(ticked.count(" · done "), 1)
        self.assertFalse(plan.is_open(ticked))

    def test_a_hand_kept_line_of_another_shape_keeps_its_box(self):
        config.plan_path("fix-api").write_text("# The plan\n\n- [x] b4 each session sees its project (#359)\n"
                                                "  - [x] the docs say `ak plan` ticks lines\n"
                                                "- see [the guide](docs/guide.md) and [x]\n")
        self.assertEqual(plan.require_done("fix-api"), set())     # nothing refused, nothing to prove

    def test_a_plan_that_cannot_be_read_never_counts_as_done(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        path = config.plan_path("fix-api")
        path.chmod(0)
        self.addCleanup(path.chmod, 0o600)
        with self.recorder() as sent, \
                self.assertRaisesRegex(config.Error, "cannot read the plan"):
            notify.main(["done", "Shipped"])
        sent.assert_not_called()

    def test_a_check_holding_the_done_words_keeps_its_line_whole(self):
        check = "grep -q ' · done ' notes.txt"
        line = self.ak("add", "notes record it", "--check", check).strip()
        self.listed()
        self.assertEqual(self.plan_lines(), [line])
        self.assertEqual(plan.LINE.match(line)["check"], check)

    def test_a_seat_filed_under_agentkit_s_own_checkout_proves_its_lines(self):
        own = Path.home() / "agentkit"
        own.mkdir()
        for args in (("init", "-q", "-b", "main"), ("config", "user.name", "Plan test"),
                     ("config", "user.email", "plan@localhost"),
                     ("commit", "-q", "--allow-empty", "-m", "base")):
            subprocess.run(["git", "-C", str(own), *args], check=True, capture_output=True)
        origin = self.root / "agentkit.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(own), str(origin)], check=True,
                       capture_output=True)
        for args in (("remote", "add", "origin", str(origin)), ("fetch", "-q", "origin"),
                     ("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")):
            subprocess.run(["git", "-C", str(own), *args], check=True, capture_output=True)
        config.save_session(self.cfg, "fix-api", "opus", ["opus"],
                            {"cwd": str(own), "repo": str(own)})
        path = config.plan_path("fix-api")
        path.write_text(f"- [ ] agentkit has it · check: `true` · {plan.named(own)} · written 2026-10-04 21:00\n")
        self.assertIn("1  - [x] agentkit has it", self.listed())

    def test_a_renamed_seats_done_reads_the_plan_it_still_writes(self):
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        config.rename_session("fix-api", "fix-api-renamed")   # the plan file moves with it
        older = config.plan_path("fix-api-renamed")
        older.write_text(f"- [x] an older plan · your eye · {self.project} · written 2026-10-01 09:00 "
                         "· done your yes 2026-10-01 10:00\n")
        os.utime(older, (1, 1))
        # the seat goes on writing its plan under the name it was launched with
        config.plan_path("fix-api").write_text(line + "\n")
        with self.assertRaisesRegex(config.Error, "the feature exists"):
            plan.require_done("fix-api-renamed")

    def test_a_line_runs_in_the_checkout_it_names_wherever_the_seat_is_filed(self):
        beta = config.CODE / "beta"
        beta.mkdir()
        origin = self.root / "beta.git"
        for args in (("init", "-q", "-b", "main"), ("config", "user.name", "Plan test"),
                     ("config", "user.email", "plan@localhost"),
                     ("commit", "-q", "--allow-empty", "-m", "base")):
            subprocess.run(["git", "-C", str(beta), *args], check=True, capture_output=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(beta), str(origin)], check=True,
                       capture_output=True)
        for args in (("remote", "add", "origin", str(origin)), ("fetch", "-q", "origin"),
                     ("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")):
            subprocess.run(["git", "-C", str(beta), *args], check=True, capture_output=True)
        config.save_session(self.cfg, "fix-api", "opus", ["opus"],
                            {"cwd": str(self.root), "repo": str(beta)})
        self.ak("add", "beta has its file", "--check", "test -f beta.txt")
        config.save_session(self.cfg, "fix-api", "opus", ["opus"],
                            {"cwd": str(self.root), "repo": str(self.repo)})
        (beta / "beta.txt").write_text("beta\n")
        for args in (("add", "."), ("commit", "-q", "-m", "beta lands"), ("push", "-q", "origin", "main")):
            subprocess.run(["git", "-C", str(beta), *args], check=True, capture_output=True)
        # filed under acme now: the line still runs in beta, the checkout it names
        self.assertRegex(self.listed(), r"1  - \[x\] beta has its file · check: `test -f beta.txt` "
                                        + "· " + re.escape(plan.named(beta)) + " · written ")

    def test_outside_a_seat_or_without_a_project_it_is_refused(self):
        with patch.dict(os.environ, {config.SESSION_ENV: ""}), \
                self.assertRaisesRegex(config.Error, "belongs to a session"):
            plan.main([])
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": str(self.root)})
        with self.assertRaisesRegex(config.Error, "filed under no project"):
            plan.main(["add", "anything", "--eye"])
        with self.assertRaisesRegex(config.Error, "usage: ak plan"):
            plan.main(["add", "anything"])


if __name__ == "__main__":
    unittest.main()
