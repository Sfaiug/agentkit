"""Project menus and their shared state language, from fixed offline state."""

from contextlib import chdir, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import config, menu, notify, orch, run, terminal, usage, watch


class Projects(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                      {"state": seat.get("live", "working"), "rule": "fixture",
                                       "since": 9100, "began": 9100, "evidence": ""}))
        # Nothing here reads the checkout's git history.  `menu.installed` -- what the menu's
        # loop reads on the way in -- is pinned to a fixed string, and `config.REPO` is a
        # directory with no history at all: an unpacked tarball outside this one, holding the
        # `config.default.toml` `config.load` falls back to and nothing else.  The screens are
        # the same in a fresh clone, in a tarball and in a checkout with commits.
        no_history = tempfile.TemporaryDirectory(prefix=".v4z-no-history-")
        self.addCleanup(no_history.cleanup)
        shutil.copy(REPO / "config.default.toml", Path(no_history.name) / "config.default.toml")
        self.stack.enter_context(patch.object(config, "REPO", Path(no_history.name)))
        self.stack.enter_context(patch.object(menu, "installed", return_value="abc1234 · 15 Sep"))
        self.stack.enter_context(patch.object(menu.time, "strftime", return_value="14:02"))
        for name in ("ATOLL", "agentkit", "newsletter-tool"):
            directory = config.CODE / name
            directory.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", "-b", "main", str(directory)], check=True)
        (config.CODE / "not-a-checkout").mkdir()
        self.seats = []
        for name, repo, live in (("atoll-fix", "ATOLL", "working"),
                                  ("atoll-plan", "ATOLL", "asking"),
                                  ("menu", "agentkit", "at_prompt"),
                                  ("rent", "newsletter-tool", "at_prompt")):
            path = str(config.CODE / repo)
            self.seats.append({"name": name, "repo": path, "path": path, "live": live, "created": 9000})
            config.save_session(self.cfg, name, "fable", ["opus"], {"repo": path, "cwd": path})
        self.running("atoll-run", "ATOLL", "atoll-fix", title="Repair the importer")
        self.running("menu-run", "agentkit", "menu", title="Group the menu", state="interrupted",
                     interrupted_at=9700)
        self.running("scratch-run", None, None, title="Write release notes", state="pass", finished_at=9940)
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [{"name": "weekly_all", "used": 79}]},
            "openai": {"meters": [{"name": "weekly", "used": 31, "window_secs": 604800}], "resets": 2},
            "meta": {"meters": [{"name": "weekly", "used": 50, "window_secs": 604800}]}}}))

    def running(self, name, repo, owner, **fields):
        return self.ended(name, owner=owner, repo=str(config.CODE / repo) if repo else None,
                          started_at=9100, rounds=3, round_summaries=[{}], **run.process_owner(),
                          **{"state": "running", "finished_at": None, **fields})

    def draw(self, width=100, height=30, page=0, keys=menu.KEYS):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), redirect_stdout(io.StringIO()) as out:
            pagination = menu.draw(self.cfg, self.seats, keys, page)
        return out.getvalue(), pagination

    def test_a_three_projects_match_real_renderer_fixtures_at_100_and_40(self):
        for width, height in ((100, 30), (40, 30)):
            screen, pages = self.draw(width, height)
            self.assertEqual(screen, (REPO / f"tests/fixtures/v4z-{width}.txt").read_text())
            self.assertEqual(pages, (0, 1))
            # A heading is the basename in accent; how many need him is said once,
            # on the top line.
            self.assertIn("\nATOLL\n", screen)
            self.assertIn("\nagentkit\n", screen)
            self.assertNotIn("seats", screen)
            self.assertIn("your projects · 3 need you", screen)
            # ... and each of those three rows says the word once, in its state column
            self.assertEqual(screen.count("needs you"), 3)
            # A run makes no project: not a scratch one, and not `not-a-checkout`.
            self.assertNotIn("scratch ·", screen)
            self.assertNotIn("not-a-checkout", screen)
            self.assertNotIn("merged", screen)
            self.assertNotIn("opus/astra", screen)
            # v5ay: `menu` is live, so its unfinished run was handed back to the seat
            # itself; only an ending no seat could be told sends him to a run's number.
            self.assertNotIn("run menu-run interrupted: press", screen)
            self.assertTrue(all(terminal.cells(line) <= width for line in screen.splitlines()))
            self.assertLessEqual(len(screen.splitlines()) + 2, height)

    def test_a_the_snapshots_never_read_the_checkout_s_git_history(self):
        self.assertFalse((config.REPO / ".git").exists())
        self.assertEqual([path.name for path in config.REPO.iterdir()], ["config.default.toml"])
        ran = []

        def command(argv, *args, **kwargs):
            # A draw talks to tmux -- it reads each seat's screen and publishes its word --
            # and never to git: the title is read once, before the first draw, and no number
            # of rows after it goes back to the checkout's history.
            ran.append(list(argv))
            self.assertNotIn("git", argv[0], argv)
            return subprocess.CompletedProcess(argv, 1, "", "")

        with patch.object(menu.subprocess, "run", side_effect=command):
            for width, height in ((100, 30), (40, 30)):
                screen, _ = self.draw(width, height)
                self.assertEqual(screen, (REPO / f"tests/fixtures/v4z-{width}.txt").read_text())
                # The frame is `agentkit` and the clock: the pinned version reaches no fixture.
                self.assertTrue(screen.startswith("agentkit "), screen[:40])
                self.assertNotIn("abc1234", screen)
        self.assertTrue(ran)   # the seats were looked at and their bars published

    def test_overview_is_read_only_in_worker_and_orchestrator_sessions(self):
        # One draw settles what each seat is -- the classifier's record and the word it
        # began -- because that is the one thing a screen writes. Every draw after it,
        # in any role at any width, changes nothing at all.
        self.draw(100, 30)
        before = {path: path.read_bytes() for directory in (config.RUNS, config.STATE)
                  for path in directory.rglob("*") if path.is_file()}
        for role in ("worker", "orchestrator", ""):
            with self.subTest(role=role), patch.dict(os.environ, {"AK_RUN_ROLE": role}), \
                    patch.object(run, "reap", side_effect=AssertionError("draw reconciled a run")):
                for width, height in ((100, 30), (40, 30)):
                    screen, _ = self.draw(width, height)
                    self.assertEqual(screen, (REPO / f"tests/fixtures/v4z-{width}.txt").read_text())
        after = {path: path.read_bytes() for directory in (config.RUNS, config.STATE)
                 for path in directory.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_b_rollups_reuse_row_precedence_across_seats(self):
        groups = {project["name"]: project for project in menu.projects(self.cfg, self.seats)}
        self.assertEqual(groups["ATOLL"]["word"], "needs you")
        self.assertEqual(groups["agentkit"]["word"], "needs you")
        self.assertNotIn("scratch", groups)
        self.assertEqual(menu.rollup(["working", "done"]), "working")
        self.assertEqual(menu.rollup(["done", "done"]), "done")
        self.assertEqual(menu.rollup(["needs you", "working", "done"]), "needs you")
        self.assertEqual(menu.run_progress({"state": "fail"})[2], "FAIL")
        self.assertIn("✗ FAIL", "\n".join(terminal.seats(
            [menu.run_row(1, Path("failure"), {"state": "fail"})], 100)))

    @staticmethod
    def numbered(screen):
        return {name: int(number) for number, name in re.findall(r"^\s*(\d+)  (\S+)", screen, re.M)}

    def test_c_numbers_survive_repeat_draws_state_changes_and_pages_and_match_discord(self):
        # Put the first alphabetical seat in the last project: visual order is not numbering.
        self.seats[0]["repo"] = str(config.CODE / "newsletter-tool")
        first = self.numbered(self.draw()[0])
        self.assertEqual(first, self.numbered(self.draw()[0]))
        self.seats[0]["live"] = "asking"
        self.seats[1]["live"] = "at_prompt"
        self.assertEqual(first, self.numbered(self.draw()[0]))
        seen = {}
        pages = self.draw(40, 12)[1][1]
        for page in range(pages):
            screen, _ = self.draw(40, 12, page)
            seen.update(self.numbered(screen))
        self.assertEqual(set(first.values()), set(seen.values()))
        for name, number in seen.items():
            self.assertTrue(next(original for original in first if first[original] == number)
                            .startswith(name.rstrip("…")))
        with patch.object(orch, "sessions", return_value=self.seats):
            for name, number in first.items():
                self.assertEqual(notify.session_number(name), number)
        with patch.object(orch, "listing", return_value=self.seats), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "read", side_effect=["m", "4", "q"]), \
                patch.object(menu, "open_session") as opened, \
                patch.object(terminal, "height", return_value=12), redirect_stdout(io.StringIO()):
            menu.loop(self.cfg, dry_run=True)
            self.assertEqual(opened.call_args.args[1]["name"], "rent")

    def test_d_short_screens_fold_the_usage_block_and_keep_every_key_on_phone(self):
        # No run row at any height: the menu at rest is the projects and their seats.
        full = self.draw(100, 30)[0]
        self.assertNotIn("↳", full)
        self.assertIn("usage left", full)
        folded, pages = self.draw(100, 18)
        # The usage block gives way first, and every seat keeps its row.
        self.assertNotIn("usage left", folded)
        self.assertNotIn("↳", folded)
        self.assertIn("atoll-fix", folded)
        self.assertEqual(pages, (0, 1))
        collapsed, pages = self.draw(40, 12)
        # Short phones page the seats; headers stay.
        self.assertNotIn("↳", collapsed)
        self.assertIn("ATOLL", collapsed)
        self.assertGreater(pages[1], 1)
        for keys in (menu.KEYS, menu.OVERLAY_KEYS):
            for width, height in ((40, 12), (38, 10), (30, 14), (40, 24)):
                for page in range(self.draw(width, height, keys=keys)[1][1]):
                    screen, (_, pages) = self.draw(width, height, page, keys)
                    self.assertLessEqual(len(screen.splitlines()) + 2, height, screen)
                    self.assertTrue(all(terminal.cells(line) <= width for line in screen.splitlines()), screen)
                    for key in (keys + ("   " + menu.PAGE_KEYS if pages > 1 else "")).split("   "):
                        self.assertIn(key, screen)

    def test_project_headers_fit_even_when_the_state_and_counts_fill_the_width(self):
        for word in terminal.STATES:
            project = {"name": "長い名前-project", "word": word, "rows": [None] * 100, "runs": [None]}
            for width in range(1, 61):
                with self.subTest(word=word, width=width):
                    self.assertLessEqual(terminal.cells(menu.project_header(project, width)), width)
        project = {"name": "ATOLL", "word": "needs you", "rows": [None] * 2, "runs": []}
        self.assertIn("! needs you", menu.project_header(project, 28))

    def test_very_short_pages_keep_each_number_once_and_leave_room_for_the_prompt(self):
        # the overlay's four keys wrap to a line more than the menu's at tiny widths,
        # so its shortest screens stand a line taller; the room for the prompt is the same
        sizes = {menu.KEYS: ((40, 7), (30, 8), (61, 6), (28, 8)),
                 menu.OVERLAY_KEYS: ((40, 8), (30, 9), (61, 6), (28, 9))}
        for keys in (menu.KEYS, menu.OVERLAY_KEYS):
            for width, height in sizes[keys]:
                with self.subTest(width=width, height=height, keys=keys):
                    numbers = []
                    pages = self.draw(width, height, keys=keys)[1][1]
                    for page in range(pages):
                        screen, _ = self.draw(width, height, page, keys)
                        self.assertLessEqual(len(screen.splitlines()) + 2, height, screen)
                        self.assertTrue(all(terminal.cells(line) <= width for line in screen.splitlines()), screen)
                        numbers += list(self.numbered(screen).values())
                        for key in (keys + "   " + menu.PAGE_KEYS).split("   "):
                            self.assertIn(key, screen)
                    self.assertEqual(sorted(numbers), list(range(1, len(self.seats) + 1)))

    def test_e_n_asks_models_names_the_seat_for_its_orchestrator_and_opens_in_code(self):
        prompts = []
        answers = iter(["", ""])
        def answer(prompt):
            prompts.append(prompt)
            sys.stdout.write(prompt)
            return next(answers)
        repo = config.CODE / "ATOLL"
        child = repo / "src"
        child.mkdir()
        with patch.object(Path, "cwd", return_value=child), \
                patch.object(terminal, "readline", side_effect=answer), \
                patch.object(usage, "collect", return_value={}), \
                patch.object(orch, "fresh_command", return_value=(["fake"], None)), \
                patch.object(orch, "launch") as launch, patch.object(menu, "open_session"), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.new_session(self.cfg, False), "opus")
        self.assertEqual(prompts, ["Orchestrator [opus]: ", "Workers [opus astra]: "])
        self.assertNotIn("Project [", out.getvalue())
        self.assertNotIn("not-a-checkout", out.getvalue())
        record = config.load_session(self.cfg, "opus")
        self.assertIsNone(record["repo"])
        self.assertEqual(record["cwd"], str(config.CODE))
        self.assertEqual(launch.call_args.args[2], config.CODE)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-q", "--allow-empty", "-m", "fixture"],
                       check=True)
        previous = Path.cwd()
        try:
            os.chdir(repo)
            self.assertEqual(run.task_repo({}, self.root / "task.md"), repo)
            self.assertEqual(run.default_base(repo, lambda _: None), "main")
        finally:
            os.chdir(previous)
        with patch.object(orch, "maintenance"), patch.object(orch, "resume") as resume, \
                patch.object(orch, "prompt_workers", side_effect=AssertionError("must resume")):
            orch.main(["opus"])
            resume.assert_called_once()
        with patch.object(Path, "cwd", return_value=repo), patch.object(orch, "maintenance"), \
                patch.object(terminal, "readline", return_value="0"), \
                patch.object(usage, "collect", return_value={}), \
                patch.object(orch, "fresh_command", return_value=(["fake"], None)), \
                patch.object(orch, "launch") as launch, patch.object(orch, "attach"), \
                redirect_stdout(io.StringIO()):
            orch.main(["opus", "--model", "astra", "--workers", "opus"])
        self.assertEqual(config.load_session(self.cfg, "opus")["repo"], str(repo))
        self.assertEqual(launch.call_args.args[2], repo)
        with patch.object(orch, "listing", return_value=self.seats), redirect_stdout(io.StringIO()) as out:
            orch.cmd_list([])
        self.assertRegex(out.getvalue(), r"atoll-fix\s+ATOLL\s+")

    def test_f_legacy_records_infer_majority_once_including_none_and_renamed_owners(self):
        config.save_session(self.cfg, "legacy", "fable", ["opus"])
        config.save_session(self.cfg, "unassigned", "fable", ["opus"])
        self.running("old-a", "ATOLL", "legacy")
        self.running("old-b", "ATOLL", "legacy")
        self.running("old-c", "agentkit", "legacy")
        config.rename_session("legacy", "renamed")
        with patch.object(run, "read_state", wraps=run.read_state) as read, \
                patch.object(config, "ensure_dirs", side_effect=AssertionError("inference prepared directories")):
            found = orch.session_projects(config.session_records())
            self.assertGreater(read.call_count, 0)
        self.assertEqual(found["renamed"], str(config.CODE / "ATOLL"))
        self.assertIn("repo", config.load_session(self.cfg, "unassigned"))
        self.assertIsNone(found["unassigned"])
        before = config.session_path("renamed").read_bytes()
        with patch.object(run, "run_dirs", side_effect=AssertionError("inference repeated")):
            orch.session_projects(config.session_records())
        self.assertEqual(config.session_path("renamed").read_bytes(), before)

    def test_cli_none_keeps_external_checkout_cwd_and_menu_none_opens_code(self):
        repo = self.root / "external"
        child = repo / "src"
        child.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "feature", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-q", "--allow-empty", "-m", "fixture"],
                       check=True)
        with chdir(child), patch.object(orch, "maintenance"), \
                patch.object(usage, "collect", return_value={}), \
                patch.object(orch, "fresh_command", return_value=(["fake"], None)), \
                patch.object(orch, "launch") as launch, patch.object(orch, "attach"), \
                redirect_stdout(io.StringIO()):
            orch.main(["external-seat", "--model", "fable", "--workers", "opus"])
            record = config.load_session(self.cfg, "external-seat")
            self.assertIsNone(record["repo"])
            self.assertEqual(record["cwd"], str(child))
            self.assertEqual(launch.call_args.args[2], child)
            self.assertEqual(run.task_repo({}, self.root / "task.md"), repo)
            self.assertEqual(run.default_base(repo, lambda _: None), "feature")
            with patch.object(terminal, "readline", side_effect=["", ""]), \
                    patch.object(menu, "open_session"), redirect_stdout(io.StringIO()):
                self.assertEqual(menu.new_session(self.cfg, False), "opus")
            self.assertEqual(launch.call_args.args[2], config.CODE)
            self.assertIsNone(config.load_session(self.cfg, "opus")["repo"])

    def test_invalid_selection_flags_fail_before_project_input_or_record_changes(self):
        for flags in (("--model", "missing"), ("--model", "astra", "--workers", "sol"),
                      ("--workers", "sol")):
            with self.subTest(flags=flags), patch.object(usage, "collect", return_value={}), \
                    patch.object(terminal, "readline") as answer, \
                    patch.object(orch, "fresh_command", side_effect=AssertionError("invalid flag launched")), \
                    redirect_stdout(io.StringIO()) as out:
                with self.assertRaisesRegex(config.Error, "(--workers|unknown model)"):
                    orch.main(["invalid", "--dry-run", *flags])
                answer.assert_not_called()
                self.assertEqual(out.getvalue(), "")
                self.assertFalse(config.session_path("invalid").exists())

    def test_g_glyph_and_colour_truecolor_256_8_no_color_dumb_non_tty_and_c_locale(self):
        with patch.object(sys.stdout, "isatty", return_value=True), patch("curses.setupterm"), \
                patch("curses.tigetnum", return_value=256) as colours:
            for setting in ("truecolor", "24bit"):
                with patch.dict(os.environ, {"TERM": "xterm", "COLORTERM": setting}, clear=True):
                    self.assertEqual(terminal.styled("! needs you", "needs you"),
                                     "\033[1;38;2;249;226;175m! needs you\033[0m")
            with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
                self.assertEqual(terminal.styled("working", "working"), "\033[38;5;111mworking\033[0m")
                colours.return_value = 8
                self.assertEqual(terminal.styled("FAIL", "FAIL"), "\033[31mFAIL\033[0m")
                for env in ({"NO_COLOR": ""}, {"TERM": "dumb"}):
                    with patch.dict(os.environ, env):
                        self.assertEqual(terminal.styled("working", "working"), "working")
                with patch.object(sys.stdout, "isatty", return_value=False):
                    self.assertEqual(terminal.styled("working", "working"), "working")
            with patch.dict(os.environ, {"LANG": "C"}, clear=True):
                for word in terminal.STATE_STYLES:
                    self.assertTrue(terminal.state_label(word).isascii())
                    self.assertIn(word, terminal.state_label(word))
            with patch.dict(os.environ, {"LANG": "en_US.UTF-8"}, clear=True):
                self.assertEqual(terminal.state_label("working"), "● working")
        env = {key: value for key, value in os.environ.items() if key not in ("LC_ALL", "LC_CTYPE")}
        proc = subprocess.run([sys.executable, "-c", "from agentkit import terminal; print(terminal.state_label('working'))"],
                              env={**env, "LANG": "C", "PYTHONPATH": str(REPO)},
                              cwd=REPO, check=True, capture_output=True, text=True)
        self.assertEqual(proc.stdout, "* working\n")

    def test_h_status_bar_and_title_are_plain_text_in_isolated_tmux(self):
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
        self.addCleanup(subprocess.run, [*argv, "kill-server"], env=env, cwd=sockets, capture_output=True)
        tmux("-f", "/dev/null", "new-session", "-d", "-s", "state", "-x", "100", "-y", "30", "sleep", "60")
        config.save_session(self.cfg, "state", "fable", ["opus"])
        seat = {"name": "state", "created": 9000, "attached": False,
                "exited": False, "legacy": False, "resumable": False}
        with patch.dict(os.environ, {key: value for key, value in env.items() if key != "NO_COLOR"}, clear=True), \
                patch.object(orch, "tmux_out", side_effect=lambda *args, **kw: (0, tmux(*args))):
            orch.dress("state", "fable")
        left = tmux("show-options", "-t", "state", "-v", "status-left")
        right = tmux("show-options", "-t", "state", "-v", "status-right")
        title = tmux("show-options", "-t", "state", "-v", "set-titles-string")
        self.assertEqual(left, "state · fable")   # the helper strips the padding
        self.assertEqual(right, "Ctrl-b m  menu")
        self.assertEqual(title, "state")
        self.assertNotIn("#[", left + right + title)
        self.assertIn('terminal-features ",*:RGB"', orch.tmux_conf().read_text())
        with patch.dict(os.environ, {key: value for key, value in env.items() if key != "NO_COLOR"}, clear=True), \
                patch.object(orch, "tmux_out", side_effect=lambda *args, **kw: (0, tmux(*args))):
            for word in terminal.STATES:
                menu.redress(seat, {"word": word, "reason": f"why {word}", "since": None},
                             cfg=self.cfg, records=[])
                label = terminal.state_text(word)
                shown = tmux("display-message", "-p", "-t", "state",
                             tmux("show-options", "-t", "state", "-v", "status-left"))
                self.assertIn(label, shown)
                self.assertEqual(tmux("show-options", "-t", "state", "-v", "set-titles-string"),
                                 f"state · {word}")

    def test_status_bar_check_can_run_from_another_working_directory(self):
        result = subprocess.run([sys.executable, str(REPO / "tests/test_v4z.py"),
                                 "Projects.test_h_status_bar_and_title_are_plain_text_in_isolated_tmux"],
                                cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_projects_carry_no_runs_and_records_hide_smoke(self):
        self.running("smoke-secret", "ATOLL", "atoll-fix",
                     task=str(config.TMP / "smoke-20260923-110800" / "task.md"))
        self.running("live-ending", "ATOLL", "atoll-fix", state="pass", finished_at=9990)
        gone = self.running("gone-ending", "ATOLL", "gone", state="pass", finished_at=9990)
        runs = [state["title"] for project in menu.projects(self.cfg, self.seats)
                for _, state in project["runs"]]
        self.assertEqual(runs, [])
        names = {d.name for d, _ in menu.run_records()}
        self.assertNotIn("smoke-secret", names)
        self.assertIn("live-ending", names)
        self.assertIn("gone-ending", names)


if __name__ == "__main__":
    if sys.argv[1:] == ["--fixtures"]:
        test = Projects()
        test.setUp()
        try:
            for width, height in ((100, 30), (40, 30)):
                (REPO / f"tests/fixtures/v4z-{width}.txt").write_text(test.draw(width, height)[0])
        finally:
            test.doCleanups()
    else:
        unittest.main(verbosity=2)
