"""v5y: every seat shows its state on its own status bar, in the menu's words; offline.

The seat's tmux status bar carries the menu row's own values -- the state word and the
last column -- written through the one writer by the tick and every menu draw; `ak run`
still writes the run tally at launch, on every state change and at the end, and a launch
says where to look.  tmux writes go through the fake seam the status-bar tests use --
`orch.tmux_out` patched -- except the real-client tests, which show the bar's text on a
throwaway `agentkit-test` server the way the isolated tmux test does.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, menu, orch, run, terminal, usage, watch

TALLY = "2 running · 1 needs a look"


def colours_on(case):
    """Colours on, the way the pinned-format tests hold the environment.

    `patch.dict` only updates, so `NO_COLOR` the sandbox sets has to go by hand;
    the sandbox restores the environment on the way out.
    """
    env = {"TERM": "xterm-256color", "LC_ALL": "C.UTF-8"}
    case.stack.enter_context(patch.dict(os.environ, env))
    os.environ.pop("NO_COLOR", None)


class Bar(Sandbox):
    def setUp(self):
        super().setUp()
        colours_on(self)

    def test_v5y_a_left_half_reads_state_and_last_column(self):
        left, right, title = orch.bar("herdr", "fable", "working", "tasks x 2/5")
        self.assertEqual(left, f" herdr · fable · {terminal.state_text('working')} · tasks x 2/5 ")
        self.assertEqual(right, " Ctrl-b m  menu ")
        self.assertEqual(title, "herdr · working")
        # the state word is the row's, from the same table
        for word in terminal.STATES:
            labelled, _, titled = orch.bar("herdr", "fable", word, "")
            self.assertIn(terminal.state_text(word), labelled)
            self.assertEqual(titled, f"herdr · {word}")

    def isolated_tmux(self):
        """Real tmux on `-L agentkit-test`, killed in cleanup, like the bar tests'."""
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        sockets = self.root / "sockets"
        sockets.mkdir()
        # Address the socket relative to its own directory, independent of the caller's
        # cwd and below sockaddr_un's limit even in a deeply nested checkout.
        env = {**os.environ, "TMUX_TMPDIR": str(sockets), "TERM": "xterm-256color"}
        env.pop("TMUX", None)
        argv = ["tmux", "-L", "agentkit-test", "-S", "agentkit-test"]

        def tmux(*args):
            return subprocess.run([*argv, *args], env=env, cwd=sockets, check=True,
                                  capture_output=True, text=True).stdout.strip()

        self.addCleanup(subprocess.run, [*argv, "kill-server"], env=env, cwd=sockets,
                        capture_output=True)
        return tmux

    def test_v5y_b_bar_is_plain_text_on_a_real_client(self):
        tmux = self.isolated_tmux()
        tmux("-f", "/dev/null", "new-session", "-d", "-s", "herdr",
             "-x", "100", "-y", "30", "sleep", "60")
        config.save_session(self.cfg, "herdr", "fable", ["opus"])
        (config.STATE / "plan-herdr.md").write_text("- [x] a\n- [ ] b\n- [ ] c\n")
        seat = {"name": "herdr", "created": time.time() - 5, "attached": False,
                "exited": False, "legacy": False, "resumable": False}
        with patch.object(orch, "tmux_out",
                          side_effect=lambda *a, **k: (0, tmux(*a))):
            orch.dress("herdr", "fable")
            menu.redress(seat, {"word": "working", "reason": "", "since": None},
                         cfg=self.cfg, records=[])
        left = tmux("show-options", "-t", "herdr", "-v", "status-left")
        right = tmux("show-options", "-t", "herdr", "-v", "status-right")
        title = tmux("show-options", "-t", "herdr", "-v", "set-titles-string")
        shown = tmux("display-message", "-p", "-t", "herdr", left)
        self.assertIn("herdr · fable", shown)
        self.assertIn("working", shown)
        self.assertIn("tasks ", shown)
        self.assertIn("1/3", shown)
        self.assertEqual(right.strip(), "Ctrl-b m  menu")
        self.assertEqual(title, "herdr · working")

    def test_v5y_j_long_reason_draws_whole_on_a_wide_client(self):
        tmux = self.isolated_tmux()
        name = "customer-portal-integration-sv"   # 30 columns, like a long checkout
        self.assertEqual(len(name), 30)
        tmux("-f", "/dev/null", "new-session", "-d", "-s", name,
             "-x", "150", "-y", "30", "sleep", "60")
        config.save_session(self.cfg, name, "fable", ["opus"])
        seat = {"name": name, "created": time.time() - 5, "attached": False,
                "exited": False, "legacy": False, "resumable": False}
        reason = "Merge the MOV helper before or after the schema lands?"
        with patch.object(orch, "tmux_out",
                          side_effect=lambda *a, **k: (0, tmux(*a))):
            orch.dress(name, "fable")
            # the length cap fits the longest true content: name, state and last, uncut
            menu.redress(seat, {"word": "needs you", "reason": reason, "since": None},
                         cfg=self.cfg, records=[])
        self.assertEqual(tmux("show-options", "-t", name, "-v", "status-left-length"),
                         "120")
        left = tmux("show-options", "-t", name, "-v", "status-left")
        shown = tmux("display-message", "-p", "-t", name, left)
        self.assertIn(f"{name} · fable → opus · ! needs you · {reason}", shown)

    def test_v5y_d_no_runs_draws_no_tally(self):
        calls = []
        with patch.object(orch, "tmux_out",
                          side_effect=lambda *a, **k: calls.append((a, k)) or (0, "")):
            orch.set_runs("herdr", None)
            orch.set_runs("herdr", "")
            orch.set_runs("herdr", menu.tally(None))
        self.assertEqual(len(calls), 3)
        for (args, _), label in zip(calls, ("None", "empty", "no runs yet")):
            with self.subTest(tally=label):
                # clearing unsets the option; no value with `0 running` is ever written
                self.assertEqual(args[:4], ("set-option", "-u", "-t", "herdr"))
                self.assertEqual(args[4], orch.RUNS_OPTION)
        left, _, _ = orch.bar("herdr", "fable", "working", "")
        self.assertNotIn("0 running", left)
        self.assertEqual(left, f" herdr · fable · {terminal.state_text('working')} ")
        # without a word yet -- a seat just started -- the bar carries no state at all
        initial, _, _ = orch.bar("herdr", "fable")
        self.assertEqual(initial, " herdr · fable ")


class Writes(Sandbox):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.stack.enter_context(patch.object(
            orch, "tmux_out",
            side_effect=lambda *a, **k: self.calls.append((a, k)) or (0, "")))

    def run_sets(self):
        """Every `@ak_runs` write, as (seat, tally-or-unset)."""
        found = []
        for args, _ in self.calls:
            if orch.RUNS_OPTION in args:
                if "-u" in args:
                    found.append((args[args.index("-t") + 1], None))
                else:
                    found.append((args[args.index("-t") + 1], args[-1]))
        return found

    def launch(self, name, owner, **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        state = {"run_id": name, "title": f"Task {name}", "state": "running",
                 "launched_session": owner, "started_at": time.time() - 60,
                 **extra}
        run.save_state(directory, state)
        return directory

    def providers_gating_astra(self):
        """Providers where astra's meter is spent: astra drops out of every order."""
        now = time.time()

        def meter(name, used, window=604800):
            return {"name": name, "used": used, "window_secs": window,
                    "resets_at": now + window / 2, "elapsed": 50, "pace": used - 50}

        def provider(name, meters):
            return {"provider": name, "meters": meters, "resets": 0, "error": None}

        providers = usage._gate_flags({
            "anthropic": provider("anthropic", [meter("weekly_all", 50),
                                                meter("weekly_scoped", 50)]),
            "openai": provider("openai", [meter("primary_window", 50)]),
            "meta": provider("meta", [meter("weekly", 55)]),
        }, now, self.cfg)
        spent = providers["openai"]["meters"][0]
        spent.update(used=100, exhausted=False)
        del spent["resets_at"]
        return usage._gate_flags(providers, now, self.cfg)

    def test_v5y_c_run_writes_option_at_launch_change_and_end(self):
        task = ("---\nrepo: none\n---\n# Ship it\n\n## Done when\n```bash\ntrue\n```\n")
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "herdr"}):
            run_dir = config.RUNS / "20260917-1200-ship-it"
            run_dir.mkdir(parents=True)
            (run_dir / "task.md").write_text(task)
            run.capture_launch(run_dir, {})
            at_launch = self.run_sets()
            run.mark_state(run_dir, "error", "boom")
            at_change = self.run_sets()
            state = run.read_state(run_dir)
            with patch.object(run, "launcher_watched", return_value=True):
                run.finish(state, run_dir, lambda line: None)
            at_end = self.run_sets()
        # the launching seat only: no other seat is ever targeted
        self.assertTrue(at_launch)
        self.assertTrue(at_change[len(at_launch):])
        self.assertTrue(at_end[len(at_change):])
        self.assertEqual({seat for seat, _ in at_end}, {"herdr"})
        # launch counts the queued run as waiting, the state change its ending
        self.assertEqual(at_launch[-1], ("herdr", "1 waiting"))
        self.assertEqual(at_change[-1], ("herdr", "1 needs you"))
        self.assertEqual(at_end[-1], ("herdr", "1 needs you"))
        # launched from no seat, nothing is written anywhere
        self.calls.clear()
        with patch.dict(os.environ, {"AGENTKIT_SESSION": ""}):
            run.capture_launch(config.RUNS / "20260917-1200-ship-it", {})
        self.assertEqual(self.run_sets(), [])

    def test_v5y_e_tick_recomputes_a_live_seat_whose_run_died(self):
        self.launch("20260917-1200-ship-it", "herdr")
        seats = [{"name": "herdr", "created": time.time() - 5, "attached": False,
                  "exited": False, "legacy": False, "resumable": False}]
        logs = []
        with patch.object(orch, "sessions", return_value=seats), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "pane_text", return_value="output\n$ "), \
                patch.object(watch, "live_state",
                             return_value={"state": "at_prompt", "rule": "fixture"}), \
                patch.object(watch.notify, "progress", return_value=False), \
                patch.object(watch, "stalled_on", return_value=None), \
                patch.object(watch, "stuck_on", return_value=False):
            watch.health(self.cfg, {"stalls": {}}, False, logs.append)
            self.assertEqual(self.run_sets()[-1], ("herdr", "1 running"))
            # the run dies without a word: the record says fail, the bar still says going
            state = run.read_state(config.RUNS / "20260917-1200-ship-it")
            state.update(state="fail", verdict="FAIL", finished_at=time.time())
            run.save_state(config.RUNS / "20260917-1200-ship-it", state)
            watch.health(self.cfg, {"stalls": {}}, False, logs.append)
            self.assertEqual(self.run_sets()[-1], ("herdr", "1 needs you"))

    def test_v5y_f_launch_line_is_printed_once(self):
        task = ("---\nrepo: none\n---\n# Ship it\n\n## Done when\n```bash\ntrue\n```\n")
        run_dir = config.RUNS / "20260917-1200-ship-it"
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text(task)
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-worktree": False, "--no-merge": False, "--bg": False}
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "herdr"}):
            run.capture_launch(run_dir, {})
            self.calls.clear()
            with patch.object(run, "pick_models", return_value=("opus", "astra")), \
                    patch.object(run, "rounds", return_value=None), \
                    patch.object(run.usage, "collect", return_value={}), \
                    redirect_stdout(io.StringIO()) as out:
                run.loop(self.cfg, run_dir, run_dir / "task.md", opts, lambda line: None)
        line = (f"run {run_dir.name} launched: Ship it (opus/astra); "
                "it counts on this bar and in the menu; you will be told when it ends")
        self.assertEqual(out.getvalue().splitlines().count(line), 1)
        # launched from no seat, the line is never printed
        with patch.dict(os.environ, {"AGENTKIT_SESSION": ""}):
            run.capture_launch(run_dir, {})
            with patch.object(run, "pick_models", return_value=("opus", "astra")), \
                    patch.object(run, "rounds", return_value=None), \
                    patch.object(run.usage, "collect", return_value={}), \
                    redirect_stdout(io.StringIO()) as out:
                run.loop(self.cfg, run_dir, run_dir / "task.md", opts, lambda line: None)
        self.assertNotIn("launched:", out.getvalue())

    def test_v5y_h_bg_parent_prints_launch_line(self):
        task = ("---\nrepo: none\n---\n# Ship it\n\n## Done when\n```bash\ntrue\n```\n")
        source = self.root / "task.md"
        source.write_text(task)
        popen = {"return_value.pid": 99999999}
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "herdr"}), \
                patch.object(run.usage, "collect", return_value={}), \
                patch.object(run.subprocess, "Popen", **popen), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.main([str(source), "--bg"]), 0)
        saved = run.read_state(max(run.run_dirs(), key=lambda d: d.name))
        line = (f"run {saved['run_id']} launched: Ship it "
                f"({saved['launch_executor']}/{saved['launch_reviewer']}); "
                "it counts on this bar and in the menu; you will be told when it ends")
        self.assertEqual(out.getvalue().splitlines().count(line), 1)
        # launched from no seat, the receipt prints but the line never does
        with patch.dict(os.environ, {"AGENTKIT_SESSION": ""}), \
                patch.object(run.usage, "collect", return_value={}), \
                patch.object(run.subprocess, "Popen", **popen), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.main([str(source), "--bg"]), 0)
        self.assertNotIn("launched:", out.getvalue())
        # the child adopts the parent's pick through the resuming validation, silently
        run_dir = config.RUNS / saved["run_id"]
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-worktree": False, "--no-merge": False, "--bg": False}
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "herdr"}), \
                patch.object(run, "pick_models", wraps=run.pick_models) as picked, \
                patch.object(run, "rounds", return_value=None), \
                patch.object(run.usage, "collect", return_value={}), \
                redirect_stdout(io.StringIO()) as out:
            run.loop(self.cfg, run_dir, run_dir / "task.md", opts, lambda line: None)
        self.assertEqual(picked.call_args[0][2:4],
                         (saved["launch_executor"], saved["launch_reviewer"]))
        self.assertTrue(picked.call_args[1].get("resuming"))
        self.assertNotIn("launched:", out.getvalue())
        self.assertNotIn("launch_executor", run.read_state(run_dir))

    def test_v5y_i_review_pr_prints_launch_line(self):
        url = "https://github.com/o/r/pull/1"
        info = {"state": "OPEN", "title": "Mend the fence", "author": "mallory",
                "baseRefName": "main", "headRefOid": "abc123"}
        wt = self.root / "repo"
        wt.mkdir()
        run_dir = config.RUNS / "20260917-1200-review-it"
        run_dir.mkdir(parents=True)
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": url,
                "--no-worktree": False, "--no-merge": False, "--bg": False}
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "herdr"}), \
                patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=wt), \
                patch.object(run, "git", return_value=""), \
                patch.object(run, "make_worktree", return_value=(wt, "ak/test")), \
                patch.object(run, "exclude_junk", return_value=None), \
                patch.object(run, "disk_pressure", return_value=False), \
                patch.object(run.usage, "collect", return_value={}), \
                patch.object(run, "review", return_value="FAIL"), \
                patch.object(run, "restore_review_checkout", return_value=None), \
                redirect_stdout(io.StringIO()) as out:
            run.capture_launch(run_dir, {"--review-pr": url})
            state = run.review_pr(self.cfg, run_dir, url, opts, lambda line: None)
        line = (f"run {run_dir.name} launched: Review PR #1: Mend the fence "
                f"({state['reviewer']} review); "
                "it counts on this bar and in the menu; you will be told when it ends")
        self.assertEqual(out.getvalue().splitlines().count(line), 1)
        # a --bg review launch names its reviewer on the seat's terminal too
        popen = {"return_value.pid": 99999999}
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "herdr"}), \
                patch.object(run, "pr_view", return_value=info), \
                patch.object(run.usage, "collect", return_value={}), \
                patch.object(run.subprocess, "Popen", **popen), \
                redirect_stdout(io.StringIO()) as out:
            rc = run.review_pr_main(
                self.cfg,
                {"--rounds": None, "--exec": None, "--review": None, "--review-pr": url,
                 "--no-worktree": False, "--no-merge": False, "--bg": True},
                {"--no-worktree": False, "--no-merge": False, "--bg": True},
                ["--review-pr", url, "--bg"], None)
        self.assertEqual(rc, 0)
        saved = run.read_state(max(run.run_dirs(), key=lambda d: d.name))
        line = (f"run {saved['run_id']} launched: Review PR #1: Mend the fence "
                f"({saved['launch_reviewer']} review); "
                "it counts on this bar and in the menu; you will be told when it ends")
        self.assertEqual(out.getvalue().splitlines().count(line), 1)

    def test_v5y_k_stale_preset_reviewer_is_repicked(self):
        # every model works but Fable, so another company is there to review in astra's place
        self.cfg["defaults"]["workers"] = [n for n in config.offered(self.cfg) if n != "fable"]
        providers = self.providers_gating_astra()
        with redirect_stderr(io.StringIO()):
            order = usage.pick_order(self.cfg, providers, quiet=True)
        self.assertNotIn("astra", order)
        task = ("---\nrepo: none\n---\n# Ship it\n\n## Done when\n```bash\ntrue\n```\n")
        run_dir = config.RUNS / "20260917-1200-ship-it"
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text(task)
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-worktree": False, "--no-merge": False, "--bg": False}
        with patch.dict(os.environ, {"AGENTKIT_SESSION": ""}):
            run.capture_launch(run_dir, {})
            state = run.read_state(run_dir)
            state.update(launch_executor="opus", launch_reviewer="astra")
            run.save_state(run_dir, state)
            with patch.object(run, "rounds", return_value=None), \
                    patch.object(run.usage, "collect", return_value=providers):
                run.loop(self.cfg, run_dir, run_dir / "task.md", opts,
                         lambda line: None)
        state = run.read_state(run_dir)
        # the executor keeps its identity; the spent reviewer is re-picked live
        self.assertEqual(state["executor"], "opus")
        self.assertNotEqual(state["reviewer"], "astra")

    def test_v5y_l_stale_preset_reviewer_is_repicked_for_review(self):
        providers = self.providers_gating_astra()
        with redirect_stderr(io.StringIO()):
            order = usage.pick_order(self.cfg, providers, role="reviewer", quiet=True)
        self.assertNotIn("astra", order)
        url = "https://github.com/o/r/pull/1"
        info = {"state": "OPEN", "title": "Mend the fence", "author": "mallory",
                "baseRefName": "main", "headRefOid": "abc123"}
        wt = self.root / "repo"
        wt.mkdir()
        run_dir = config.RUNS / "20260917-1200-review-it"
        run_dir.mkdir(parents=True)
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": url,
                "--no-worktree": False, "--no-merge": False, "--bg": False}
        with patch.dict(os.environ, {"AGENTKIT_SESSION": ""}), \
                patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=wt), \
                patch.object(run, "git", return_value=""), \
                patch.object(run, "make_worktree", return_value=(wt, "ak/test")), \
                patch.object(run, "exclude_junk", return_value=None), \
                patch.object(run, "disk_pressure", return_value=False), \
                patch.object(run.usage, "collect", return_value=providers), \
                patch.object(run, "review", return_value="FAIL"), \
                patch.object(run, "restore_review_checkout", return_value=None):
            run.capture_launch(run_dir, {"--review-pr": url})
            state = run.read_state(run_dir)
            state.update(launch_reviewer="astra")
            run.save_state(run_dir, state)
            state = run.review_pr(self.cfg, run_dir, url, opts, lambda line: None)
        self.assertNotEqual(state["reviewer"], "astra")
        self.assertNotIn("launch_reviewer", run.read_state(run_dir))

    def test_v5y_g_menu_draw_sets_each_live_seat_bar(self):
        now = time.time()
        seats = [
            {"name": "herdr", "repo": "r", "path": "p", "created": now - 5,
             "attached": False, "exited": False, "legacy": False, "resumable": False},
            {"name": "scribe", "repo": "r", "path": "p", "created": now - 5,
             "attached": False, "exited": False, "legacy": False, "resumable": False},
            {"name": "merger", "repo": "r", "path": "p", "created": now - 5,
             "attached": False, "exited": False, "legacy": False, "resumable": False},
            {"name": "old", "repo": "r", "path": "p", "created": now - 5,
             "attached": False, "exited": False, "legacy": True, "resumable": False},
        ]
        self.launch("going", "herdr")
        self.launch("legacy-going", "old")
        merged = config.RUNS / "20260917-1200-merged"
        merged.mkdir(parents=True)
        run.save_state(merged, {"run_id": merged.name, "title": "Task merged",
                                "state": "pass", "merged": True,
                                "launched_session": "merger",
                                "finished_at": time.time() - 60})
        with patch("agentkit.watch.live_state",
                   side_effect=lambda seat, **kw: {"word": "working", "since": now - 60}):
            groups = menu.projects(self.cfg, seats)
        tallies = {row[1]: row[6] for project in groups for row in project["rows"]}
        self.assertEqual(tallies["herdr"], "1 running · 0 merged")
        written = dict(self.run_sets())
        self.assertEqual(written.get("herdr"), "1 running")
        # no runs: the option is unset, never `0 running`
        self.assertIsNone(written.get("scribe"))
        # merges alone never reach a bar either: the row shows them another way
        self.assertIsNone(written.get("merger"))
        self.assertIn(("set-option", "-u", "-t", "merger", orch.RUNS_OPTION),
                      [args for args, _ in self.calls])
        self.assertIn(("set-option", "-u", "-t", "scribe", orch.RUNS_OPTION),
                      [args for args, _ in self.calls])
        # a legacy seat lives on the user's own server: nothing is written there
        self.assertNotIn("old", written)


if __name__ == "__main__":
    unittest.main(verbosity=2)
