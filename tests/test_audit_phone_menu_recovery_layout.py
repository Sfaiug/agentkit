"""Finding 7: every phone menu action stays reachable within the screen; offline.

A typo in the picker is asked again rather than closing the connection, twelve seats and a
dozen runs are paged by the terminal's height with the row numbers kept, and a seat's status
bar says the row's own words with the one key beside them.  Fake adapters stand in for every
harness, the seats
live on the agentkit-test socket in a private socket directory, and the phone is a second
tmux server beside it whose pane runs the real `ak attach --client` at 40x24 and 100x30.  No
model is called and nothing of the owner's is read or written.

Set PHONE_MENU_CAPTURES=<dir> to keep every screen the walk reads, named by terminal size and
step, for a reviewer to attach to the PR.
"""

from contextlib import ExitStack, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, run, terminal

REAL_TMUX = shutil.which("tmux")
SOCKET = "agentkit-test"
LONG_NAME = "zz-very-long-session-name-for-a-narrow-p"    # NAME_CAP characters; sorts last
STAND_IN = "stand-in harness: no model call"
LONG_REASON = ("reviewer astra died on API/transport errors 3 times and no eligible reviewer is "
               "left on another provider; waiting for review. See {}/round-1-reviewer*/stderr.log "
               "and the round summaries in result.md before deciding whether to resume")
NUMBERED = re.compile(r"^[›>]?\s*(\d+)  \S")              # a seat or run row: its number, the name
MARKED = re.compile(r"^[›>] +(\d+)  \S")                   # the highlighted seat row, and its number


class Sandbox(unittest.TestCase):
    """Temporary state under the repo, private socket directories, fake adapters, no network."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".phone-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        # the socket directories are the system temp's: a unix socket path is capped near 108
        # bytes, which a worktree's path plus `tmux-<uid>/agentkit-test` is already past
        sockets = tempfile.TemporaryDirectory(prefix="phone-tmux-")
        self.addCleanup(sockets.cleanup)
        self.seats_dir = Path(sockets.name) / "seats"
        self.phone_dir = Path(sockets.name) / "phone"
        for path in (self.seats_dir, self.phone_dir, self.root / "bin", self.root / "adapters",
                     self.home / ".agentkit" / "state"):
            path.mkdir(mode=0o700, parents=True)
        real_git = shutil.which("git")
        # nothing on the menu path pulls the checkout any more, and a `git pull` from here
        # would still not reach the network; everything else git is asked stays answered
        self.script(self.root / "bin" / "git", '#!/bin/sh\ncase " $* " in *" pull "*) exit 1 ;; esac\n'
                    f'exec {shlex.quote(real_git)} "$@"\n')
        for executable in ("gh", "claude", "codex", "muse", "curl", "ssh"):
            self.script(self.root / "bin" / executable,
                        f'#!/bin/sh\necho "{executable}: external call forbidden" >&2\nexit 97\n')
        command = shlex.join(["sh", "-c", f"echo {shlex.quote(STAND_IN)}; exec sleep 600"])
        for harness in ("claude", "codex", "muse"):
            # a Codex or Muse TUI takes no conversation id, and their adapters say so with 3
            refuse = '[ "${5:-}" = new ] && exit 3; ' if harness != "claude" else ""
            self.script(self.root / "adapters" / f"{harness}.sh", '#!/usr/bin/env bash\n'
                        'case "${1:-}" in\n'
                        '  usage) printf \'%s\\n\' \'{"meters":[],"error":"unknown: fake"}\' ;;\n'
                        f'  interactive) {refuse}printf \'%s\\n\' {shlex.quote(command)} ;;\n'
                        'esac\nexit 0\n')
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ("TMUX", "COLUMNS", "LINES", "NO_COLOR")}
        self.env.update({
            "HOME": str(self.home), "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_PARENT_RUN": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": SOCKET,
            "TMUX_TMPDIR": str(self.seats_dir), config.ADAPTER_DIR_ENV: str(self.root / "adapters"),
            "GIT_CONFIG_GLOBAL": os.devnull, "PYTHONDONTWRITEBYTECODE": "1",
            "TERM": "xterm-256color"})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, self.env, clear=True))
        self.stack.enter_context(patch.object(config, "HOME", self.home / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.home / "code"))
        self.stack.enter_context(patch.object(terminal, "height", return_value=24))
        config.ensure_dirs()
        self.cfg = config.load()

    def script(self, path, text):
        path.write_text(text)
        path.chmod(0o755)

    def runs(self, count, reason=LONG_REASON):
        """`count` runs the `r` list offers: mostly finished, two to recover, one still going."""
        now = time.time()
        for n in range(1, count + 1):
            directory = config.RUNS / f"20260911-{n:02d}-audit-run"
            directory.mkdir()
            state = {"run_id": directory.name, "state": "pass", "verdict": "PASS",
                     "title": f"Audit a phone menu with a long task title {n}",
                     "launched_session": "phone-audit" if n % 2 else None, "scratch": True,
                     "executor": "opus", "reviewer": "astra", "rounds": 3,
                     "round_summaries": [{}], "started_at": now - 600, "finished_at": now - 60}
            if n in (3, 8):
                # told already: a notice typed into the seat would change the screen under test
                state.update(state="interrupted", interrupted_at=now - 30, recovery_pending=True,
                             recovery_notified="needs",
                             interruption_reason="Run process exited or its identity changed "
                                                 "before the loop recorded a verdict.")
                state.pop("finished_at")
            if n == 3:
                # a review that ran out of providers, with the diagnostic the loop really writes
                state.update(state="exhausted", error=reason.format(directory))
            elif n == count:
                state.update(state="running", finished_at=None, **run.process_owner())
            run.save_state(directory, state)


# --- offline: the picker, the pages and the bar -----------------------------


class Picker(Sandbox):
    def test_a_typo_is_asked_again_and_what_was_answered_stands(self):
        answers, prompts = iter(["z", "8", ""]), []

        def typed(prompt):
            prompts.append(prompt)
            sys.stdout.write(prompt)
            return next(answers)
        with patch.object(terminal, "readline", side_effect=typed), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.prompt_orchestrator(self.cfg, "opus", {}, ""), "opus")
        text = out.getvalue()
        for typo in ("'z'", "'8'"):
            self.assertIn(f"not a choice: {typo}", text)
        self.assertEqual(prompts.count("Orchestrator [opus]: "), 3)
        # the choices are drawn again under each typo: on a phone they scroll off
        self.assertEqual(text.count("  1 fable · 2 opus · 3 astra · 4 spark · 5 grok · 6 gemini · 7 mimo"), 3)
        # end of input takes the default, so a script -- or a phone that hung up -- never loops
        with patch.object(terminal, "readline", return_value=None), redirect_stdout(io.StringIO()):
            self.assertEqual(orch.prompt_orchestrator(self.cfg, "astra", {}, ""), "astra")
        # the menu's `n` rides on the same orchestrator question from a pipe, and names the seat
        # for the orchestrator it was given
        answers = iter(["3", "all"])
        with patch.object(terminal, "readline", side_effect=lambda prompt:
                          (sys.stdout.write(prompt), next(answers))[1]), \
                patch.object(orch, "sessions", return_value=[]), \
                patch.object(orch.usage, "collect", return_value={}), \
                patch.object(orch, "launch"), patch.object(menu, "open_session"), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.new_session(self.cfg, dry_run=False), "astra")
        record = json.loads(config.session_path("astra").read_text())
        self.assertEqual(record["orchestrator"], "astra")
        self.assertEqual(record["workers"], config.offered(self.cfg))

    def test_model_lines_fit_forty_columns_without_splitting_an_id(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["models"]["spark"]["model"] = "muse-spark-1.3-contributor-extended-context-preview-2026-09"
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "readline", side_effect=[""]), \
                redirect_stdout(io.StringIO()) as out:
            orch.prompt_orchestrator(cfg, "fable", {}, "")
            lines = [line for line in out.getvalue().splitlines() if line.strip()]
            self.assertEqual(lines, ["  1 fable · 2 opus · 3 astra · 4 spark · 5 grok · 6 gemini · 7 mimo"])
            self.assertNotIn("claude-fable-5-1", "\n".join(lines))
            self.assertNotIn("extended-context", "\n".join(lines))
        # long names wrap between entries at forty columns, every name whole
        names = ["Company-Website-Redesign", "customer-portal-web-app", "newsletter-tool"]
        with patch.object(terminal, "width", return_value=40), \
                patch.object(terminal, "readline", side_effect=[""]), \
                redirect_stdout(io.StringIO()) as out:
            terminal.ask("Project", "none", names, zero="none", allow=lambda answer: None)
        lines = [line for line in out.getvalue().splitlines() if line.strip()]
        self.assertTrue(len(lines) > 1, lines)
        for line in lines:
            self.assertTrue(line.startswith("  "), line)
            self.assertLessEqual(terminal.cells(line), 40, line)
        for name in names + ["0 none"]:
            self.assertIn(name, out.getvalue())

    def test_the_workers_prompt_wraps_on_a_phone(self):
        seen = []

        def typed(prompt=""):
            seen.append(prompt)
            return ""

        cfg = copy.deepcopy(self.cfg)
        cfg["defaults"]["workers"] = config.offered(cfg)   # seven names: the prompt has to wrap
        with patch.object(terminal, "width", return_value=40), \
                patch.object(terminal, "readline", side_effect=typed), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.prompt_workers(cfg), config.offered(cfg))
        lines = [line for line in out.getvalue().splitlines() + seen if line.strip()]
        self.assertTrue(lines)
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)
        self.assertTrue(seen[-1].rstrip().endswith("mimo]:"), seen)
        self.assertIn("Workers", out.getvalue())


class Pages(Sandbox):
    def seats(self, count):
        return [{"name": f"seat-{n:02d}" if n < count else LONG_NAME, "created": time.time() - 5,
                 "attached": False, "exited": False, "legacy": False, "resumable": False}
                for n in range(1, count + 1)]

    def draw(self, seats, width, height, page=0, keys=menu.KEYS):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), \
                patch.object(menu, "installed", return_value="abc1234 · 15 Sep"), \
                redirect_stdout(io.StringIO()) as out:
            drawn = menu.draw(self.cfg, seats, keys, page)
        return out.getvalue().splitlines(), drawn

    @staticmethod
    def numbers(lines):
        return {int(m.group(1)) for line in lines for m in [NUMBERED.match(line)] if m}

    def test_pages_fit_the_height_and_rows_keep_their_numbers(self):
        seats = self.seats(12)
        # A seat's reason rides its own line on a phone, so a narrow page holds fewer
        # of them than it did when the row was a word and nothing else.
        for width, height, keys, size, meters, compact in (
                (40, 24, menu.KEYS, 6, False, False), (100, 30, menu.KEYS, 12, True, False),
                (40, 12, menu.KEYS, 3, False, True), (30, 14, menu.OVERLAY_KEYS, 2, False, True),
                (78, 19, menu.OVERLAY_KEYS, 8, False, False),
                (38, 22, menu.OVERLAY_KEYS, 4, False, False),
                (38, 10, menu.OVERLAY_KEYS, 1, False, True)):
            with self.subTest(width=width, height=height):
                seen, pages = set(), None
                for page in range(20):
                    lines, (drawn, pages) = self.draw(seats, width, height, page, keys)
                    if page >= pages:
                        self.assertEqual(drawn, pages - 1)     # asked past the end: the last page
                        break
                    self.assertEqual(drawn, page)
                    # the whole page, the prompt and the answer's line are within the height
                    self.assertLessEqual(len(lines) + 2, height, "\n".join(lines))
                    self.assertTrue(all(terminal.cells(line) <= width for line in lines))
                    self.assertEqual(("usage left" in "\n".join(lines)), meters)
                    # the frame header goes only while a page holds a row; past that
                    # the compact heading is the whole chrome. The commit hash left
                    # the header, so the frame reads agentkit and the clock.
                    self.assertEqual(lines[0].startswith("agentkit"), not compact)
                    if compact:
                        self.assertIn("your projects", lines[0])
                    numbers = self.numbers(lines)
                    if pages > 1 and page == 0:
                        self.assertFalse(numbers)  # collapsed project overview
                    else:
                        start = len(seen) + 1
                        self.assertEqual(numbers, set(range(start, min(12, start + size - 1) + 1)))
                    for key in ("m more", "k previous"):    # on one key line, or on two
                        self.assertEqual(any(key in line for line in lines), pages > 1, key)
                    heading = next(line for line in lines if "your projects" in line)
                    if pages > 1:
                        self.assertIn(f" {page + 1}/{pages}", heading)
                    seen |= numbers
                self.assertEqual(pages, 1 if size >= 12 else 1 + -(-12 // size))
                self.assertEqual(seen, set(range(1, 13)))
        # the popup over a seat, one seat listed: the meters give way rather than the title
        lines, drawn = self.draw(self.seats(1), 38, 14, keys=menu.OVERLAY_KEYS)
        self.assertEqual(drawn, (0, 1))
        self.assertLessEqual(len(lines) + 2, 14, "\n".join(lines))
        self.assertNotIn("usage left", "\n".join(lines))
        self.assertTrue(lines[0].startswith("agentkit"))
        # one page draws exactly what it always drew: no page keys and no range
        lines, drawn = self.draw(self.seats(3), 40, 24)
        self.assertEqual(drawn, (0, 1))
        self.assertIn("your projects · 3 need you", lines)
        self.assertNotIn("m more", "\n".join(lines))
        self.assertEqual(self.draw(self.seats(3), 40, 24, page=7)[1], (0, 1))

    def test_the_loop_turns_pages_and_answers_a_number_from_any_page(self):
        seats = self.seats(12)
        answers = iter(["m", "k", "m", "m", "m", "12", "3", "x", "11", "y", "q"])
        opened, stopped = [], []
        # short enough to page: the loop turns whole seat blocks and answers a
        # number from whichever page is up
        with patch.object(menu.orch, "listing", return_value=seats), \
                patch.object(menu.orch, "job_notices", return_value=[]), \
                patch.object(menu, "read", side_effect=lambda *_: next(answers)), \
                patch.object(menu, "wait_key", side_effect=lambda prompt,
                             timeout=None, wake=None: next(answers)), \
                patch.object(menu, "open_session", side_effect=lambda cfg, s, dry: opened.append(s["name"])), \
                patch.object(menu.orch, "cmd_stop", side_effect=lambda argv: stopped.append(argv[0])), \
                patch.object(terminal, "width", return_value=40), \
                patch.object(terminal, "height", return_value=12), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop(self.cfg), 0)
        headings = [line.strip() for line in out.getvalue().splitlines() if "your projects" in line]
        base = "your projects · 12 need you"
        self.assertEqual(headings, [f"{base} 1/5", f"{base} 2/5",
                                    f"{base} 1/5", f"{base} 2/5",
                                    f"{base} 3/5", f"{base} 4/5",
                                    f"{base} 4/5", f"{base} 4/5",
                                    f"{base} 4/5"])
        self.assertEqual(opened, [LONG_NAME, "seat-03"])   # 12 answered from the first page
        self.assertEqual(stopped, ["seat-11"])

    def test_the_menu_has_no_runs_list(self):
        self.assertFalse(hasattr(menu, "runs_listing"))
        self.assertFalse(hasattr(menu, "runs"))
        self.assertFalse(hasattr(menu, "watch_run"))
        self.assertNotIn("r runs", menu.KEYS)
        answers = iter(["r", "q"])
        with patch.object(menu.orch, "listing", return_value=[]), \
                patch.object(menu.orch, "job_notices", return_value=[]), \
                patch.object(menu, "draw", return_value=(0, 1)), \
                patch.object(menu, "read", side_effect=lambda *_: next(answers)), \
                patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop({}), 0)
        self.assertIn("not a key: 'r'", out.getvalue())


class Recovery(Sandbox):
    def test_the_menu_has_no_recovery_screen(self):
        self.assertFalse(hasattr(menu, "recover_run"))
        self.assertFalse(hasattr(menu, "RECOVER"))
        self.assertFalse(hasattr(menu, "watch_run"))
        self.assertFalse(hasattr(menu, "page"))
        self.assertFalse(hasattr(menu, "Feed"))


class Bar(Sandbox):
    def test_the_bar_is_the_row_s_values_and_the_one_key(self):
        left, right, title = orch.bar("herdr", "fable", "working", "tasks x 2/5")
        self.assertEqual(left,
                         f" herdr · fable · {terminal.state_text('working')} · tasks x 2/5 ")
        self.assertEqual(right, " Ctrl-b m  menu ")
        self.assertEqual(title, "herdr · working")
        for hint in ("Ctrl-b d", "back to menu", "menu here"):
            self.assertNotIn(hint, left + right)

    def test_reviewed_text_is_pinned_independently_of_the_renderer(self):
        # Smoke compares the installed tmux options with these same literal expectations.
        env = {**os.environ, "TERM": "xterm-256color", "LC_ALL": "C.UTF-8"}
        env.pop("NO_COLOR", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(orch.bar("herdr", "fable", "working", "tasks x 2/5"),
                             (" herdr · fable · ● working · tasks x 2/5 ",
                              " Ctrl-b m  menu ", "herdr · working"))
            self.assertEqual(orch.bar("herdr", "fable"),
                             (" herdr · fable ", " Ctrl-b m  menu ", "herdr"))


# --- the phone: real tmux at 40x24 and 100x30 -------------------------------


class Terminal:
    """A phone-sized tmux client of its own, on a socket directory beside the seats'.

    Its pane runs the real menu, and what the pane shows is what the phone would: the menu,
    then the seat the menu attaches with its status bar, then the popup over that.  Nested on
    purpose -- the outer server is the terminal and the inner one is agentkit's -- and both
    are `agentkit-test` in directories of this test's own.
    """

    def __init__(self, case, width, height):
        self.case, self.width, self.height, self.shots = case, width, height, 0
        self.label = f"{width}x{height}"       # the walk's size; a resize is named in the shot
        self.env = {**case.env, "TMUX_TMPDIR": str(case.phone_dir)}
        self.captures = os.environ.get("PHONE_MENU_CAPTURES")
        conf = case.root / "phone.conf"
        conf.write_text("set -g remain-on-exit on\n")   # a menu that exits leaves its last screen
        ak = shlex.join([sys.executable, str(REPO / "bin" / "ak"), "attach", "--client"])
        command = f"env -u TMUX TMUX_TMPDIR={shlex.quote(str(case.seats_dir))} {ak}"
        self.tmux("-f", str(conf), "new-session", "-d", "-s", "phone",
                  "-x", str(width), "-y", str(height), command)

    def tmux(self, *args, check=True):
        proc = subprocess.run(["tmux", "-L", SOCKET, *args], env=self.env, text=True,
                              capture_output=True)
        if check:
            self.case.assertEqual(proc.returncode, 0, (args, proc.stdout, proc.stderr))
        return proc.stdout

    def screen(self):
        return [line.rstrip() for line in
                self.tmux("capture-pane", "-p", "-t", "phone").rstrip("\n").split("\n")]

    def dead(self):
        return self.tmux("display-message", "-p", "-t", "phone", "#{pane_dead}").strip() == "1"

    def shot(self, what, screen):
        self.shots += 1
        if self.captures:
            slug = re.sub(r"[^a-z0-9]+", "-", what.lower()).strip("-")[:40]
            size = f"{self.width}x{self.height}"
            at = "" if size == self.label else f"at-{size}-"
            path = Path(self.captures) / f"{self.label}-{self.shots:02d}-{at}{slug}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(screen).rstrip() + "\n")

    def wait(self, ready, what, timeout=30):
        deadline = time.monotonic() + timeout
        while True:
            screen = self.screen()
            if ready(screen):
                self.shot(what, screen)
                return screen
            self.case.assertFalse(self.dead(), f"the menu exited before {what}:\n" + "\n".join(screen))
            self.case.assertLess(time.monotonic(), deadline,
                                 f"timed out waiting for {what}:\n" + "\n".join(screen))
            time.sleep(0.1)

    @staticmethod
    def inside(screen):
        """The lines inside a popup's box when one is up, else the screen itself."""
        boxed = [line.split("│")[1].rstrip() for line in screen if line.count("│") == 2]
        return boxed or screen

    def until(self, *texts, absent=(), prompt=None, timeout=30):
        """The screen once every text is on it, none of `absent` is, and `prompt` ends it."""
        def ready(screen):
            joined = "\n".join(screen)
            last = next((line for line in reversed(self.inside(screen)) if line.strip()), "")
            return (all(text in joined for text in texts) and not any(a in joined for a in absent)
                    and (prompt is None or last.endswith(prompt)))
        return self.wait(ready, " & ".join(texts) or f"prompt {prompt!r}", timeout)

    def type(self, text):
        """A line, answered with Enter: what a question under the menu reads."""
        if text:
            self.tmux("send-keys", "-t", "phone", "-l", text)
        self.tmux("send-keys", "-t", "phone", "Enter")

    def press(self, text):
        """Keys and no Enter: the menu acts on each the moment it is pressed."""
        self.tmux("send-keys", "-t", "phone", "-l", text)

    def keys(self, *keys):
        self.tmux("send-keys", "-t", "phone", *keys)

    def resize(self, width, height):
        self.width, self.height = width, height
        self.tmux("resize-window", "-t", "phone", "-x", str(width), "-y", str(height))

    def redraw(self, *texts, key="Left", prompt="q leave", tries=5):
        """`key` (an arrow that moves nothing, by default) for a redraw; again when the pane's
        pty was still being resized under it.

        tmux applies a pane's new size to its pty a moment after `resize-window`, so a key
        sent straight after may be answered at the old size, as a phone turned mid-keypress
        would be; the next one draws it right.  The screen has to fit the size as well as
        say the texts: the old layout re-wrapped by tmux may still say them.
        """
        for _ in range(tries):
            self.keys(key)
            try:
                screen = self.until(*texts, prompt=prompt, timeout=3)
            except AssertionError as exc:
                last = exc
                continue
            if len(screen) <= self.height and all(terminal.cells(l) <= self.width for l in screen):
                return screen
            last = AssertionError("drawn at the old size:\n" + "\n".join(screen))
        raise last

    def settled(self, timeout=30):
        """Wait until no popup of this fixture's is still on its way out after a switch.

        `switch-client` shows the seat before the popup's own process has finished and the
        popup has come down; a key sent in between goes to the popup and is lost.  Only
        processes with this test's HOME count: the owner's own seats may have popups up.
        """
        deadline = time.monotonic() + timeout
        home = f"HOME={self.case.home}".encode()
        while True:
            open_ = []
            for proc in Path("/proc").iterdir():
                if not proc.name.isdigit():
                    continue
                try:
                    cmdline = (proc / "cmdline").read_bytes()
                    if b"attach\0--overlay" in cmdline and home in (proc / "environ").read_bytes().split(b"\0"):
                        open_.append(proc.name)
                except OSError:
                    continue
            if not open_:
                return
            self.case.assertLess(time.monotonic(), deadline, f"popup processes still up: {open_}")
            time.sleep(0.1)


@unittest.skipUnless(REAL_TMUX, "tmux not installed")
class Phone(Sandbox):
    def setUp(self):
        super().setUp()
        for directory in (self.phone_dir, self.seats_dir):
            self.addCleanup(subprocess.run, ["tmux", "-L", SOCKET, "kill-server"],
                            env={**self.env, "TMUX_TMPDIR": str(directory)}, capture_output=True)

    def seat(self, name, orchestrator="astra"):
        """A seat on the seats server the way `ak orch` starts one, holding a stand-in."""
        config.save_session(self.cfg, name, orchestrator, ["opus"],
                            {"cwd": str(self.home), "created": time.time()})
        orch.start(name, self.home, ["sh", "-c", f"echo {shlex.quote(STAND_IN)}; exec sleep 600"],
                   orchestrator)

    def has_seat(self, name):
        return subprocess.run(["tmux", "-L", SOCKET, "has-session", "-t", f"={name}"], env=self.env,
                              capture_output=True).returncode == 0

    def fits(self, screen, width, height):
        self.assertLessEqual(len(screen), height)
        for line in screen:
            self.assertLessEqual(terminal.cells(line), width, line)

    def whole_page(self, screen, width, height, heading="your projects"):
        """A drawn page: title on the first line, the keys on the last, nothing scrolled off."""
        self.fits(screen, width, height)
        self.assertTrue(screen[0].startswith("agentkit"), "\n".join(screen))
        self.assertTrue(next(line for line in reversed(screen) if line.strip()).endswith("q leave"),
                        "\n".join(screen))
        return next(line for line in screen if heading in line)

    def popup_page(self, screen):
        """The page inside the popup: heading and keys both within the box."""
        inside = Terminal.inside(screen)
        self.assertTrue(any("your projects" in line for line in inside), "\n".join(screen))
        self.assertTrue(next(line for line in reversed(inside) if line.strip()).endswith("q close"),
                        "\n".join(screen))
        return inside

    @staticmethod
    def numbers(lines):
        return {int(m.group(1)) for line in lines for m in [NUMBERED.match(line)] if m}

    @staticmethod
    def marked(lines):
        """The number of the highlighted seat, or None where no row is highlighted."""
        return next((int(m.group(1)) for line in lines for m in [MARKED.match(line)] if m), None)

    def moved(self, phone, key, lines):
        """The screen once `key` has moved the highlight off the seat it is on in `lines`."""
        at = self.marked(lines)
        phone.keys(key)

        def ready(screen):
            inside = Terminal.inside(screen)
            last = next((line for line in reversed(inside) if line.strip()), "")
            return self.marked(inside) not in (None, at) and last.endswith(("q leave", "q close"))
        return phone.wait(ready, f"the highlight moved by {key} off {at}")

    def turned(self, phone, before):
        """The runs screen once an m/k press has taken effect: its rows changed.

        The frame title, the key line and the prompt are the same on every
        page, so waiting for them alone returns the page that is already up
        and the next press skips one; the row numbers move on every turn.
        """
        def ready(screen):
            joined = "\n".join(screen)
            last = next((line for line in reversed(screen) if line.strip()), "")
            return ("agentkit · runs" in joined and self.numbers(screen) != before
                    and last.endswith("q back:"))
        return phone.wait(ready, "the turned runs page")

    def every_page(self, phone, screen, page, of, count):
        """Move the highlight to the top seat and down to the last, collecting the row numbers
        each page shows: the page up is the one the highlight is on, so a row below a page's
        last turns it, and a row above its first turns it back.  Every seat here is in the same
        state, so the rows run in their numbers' order and the top one is 1.
        """
        while self.marked(page(screen)) != 1:
            screen = self.moved(phone, "k", page(screen))
        seen, headings = set(), []
        for _ in range(of):
            lines = page(screen)
            seen |= self.numbers(lines)
            heading = next(line for line in lines if "your projects" in line).strip()
            self.assertRegex(heading, r"your projects( · .*?)? \d+/\d+$")
            self.assertNotIn("m more", "\n".join(lines))
            if heading not in headings:
                headings.append(heading)
            if self.marked(lines) == of:
                break
            screen = self.moved(phone, "Down", lines)
        self.assertEqual(seen, set(range(1, of + 1)), headings)
        self.assertGreater(len(headings), 1)
        for _ in range(of):
            screen = self.moved(phone, "Up", page(screen))
            heading = next(line for line in page(screen) if "your projects" in line).strip()
            if heading != headings[-1]:
                break
        self.assertEqual(heading, headings[-2])
        return headings

    def stop_answered(self, phone):
        """`Stop` picked on the question `x` asks under a row: Down onto it, then Enter."""
        phone.keys("Down")
        phone.wait(lambda screen: any(re.fullmatch(r"[›>] Stop", line.strip())
                                      for line in Terminal.inside(screen)), "Stop highlighted")
        phone.keys("Enter")

    def walk(self, width, height):
        narrow = width < 60
        phone = Terminal(self, width, height)
        screen = phone.until("no sessions; n starts one", "q leave", prompt="q leave")
        self.whole_page(screen, width, height, "no sessions")
        # n, at once: one screen that fits, astra chosen below opus and every worker added
        phone.press("n")
        screen = phone.until("agentkit · new session", "Orchestrator", prompt="esc back")
        self.fits(screen, width, height)
        phone.keys("Down", "Space")
        phone.until("● Astra", prompt="esc back")
        for steps in (5, 3, 1, 1, 1):        # fable, then spark, grok, gemini and mimo
            phone.keys(*["Down"] * steps, "Space")
        screen = phone.until("■ Mimo", prompt="esc back")
        self.fits(screen, width, height)
        phone.keys("Enter")
        # the seat opens in this terminal, named for its orchestrator, and its bar keeps the key
        screen = phone.until(STAND_IN, "astra · astra", "Ctrl-b m  menu")
        self.fits(screen, width, height)
        bar = screen[-1]
        self.assertTrue(bar.endswith("Ctrl-b m  menu"), bar)
        # the popup: r renames it; q closes it; n starts a second seat and switches to it; a
        # number switches back; x stops this session, and the client falls back to the other
        phone.keys("C-b", "m")
        phone.until("q close", "1  astra", prompt="q close")
        phone.press("r")
        phone.until("Name [astra]:", prompt="Name [astra]:")
        phone.type("Phone Audit")
        screen = phone.until("q close", "1  phone-au", prompt="q close")
        record = json.loads(config.session_path("phone-audit").read_text())
        self.assertEqual((record["orchestrator"], record["workers"]),
                         ("astra", ["opus", "astra", "fable", "spark", "grok", "gemini", "mimo"]))
        self.assertNotIn("p preview", "\n".join(screen))
        phone.press("q")
        phone.until(STAND_IN, absent=["q close"])
        phone.settled()                      # its screen goes before its process does
        phone.keys("C-b", "m")
        phone.until("q close", prompt="q close")
        phone.press("n")                     # and Enter takes the defaults: opus, for opus and astra
        phone.until("agentkit · new session", prompt="esc back")
        phone.keys("Enter")
        phone.until("opus · opus", "Ctrl-b m  menu", absent=["q close"])
        phone.settled()
        self.assertTrue(self.has_seat("opus"))
        phone.keys("C-b", "m")
        phone.until("q close", "1  opus", "2  phone-au", prompt="q close")
        phone.press("2")
        phone.until("phone-audit · astra", absent=["q close"])
        phone.settled()
        phone.keys("C-b", "m")
        phone.until("q close", "1  opus", prompt="q close")
        phone.press("1")
        phone.until("opus · opus", absent=["q close"])
        phone.settled()
        phone.keys("C-b", "m")
        phone.until("q close", prompt="q close")
        phone.press("x")                     # this session's, asked under its own row
        phone.until("Stop opus and everything it runs?", "Keep", prompt="esc keep")
        self.stop_answered(phone)
        # the seat is gone, so the attach is over: the menu is back, with no ghost row
        screen = phone.until("your projects", "1  phone-audit", "q leave", prompt="q leave")
        self.whole_page(screen, width, height)
        self.assertFalse(self.has_seat("opus"))
        self.assertNotIn("2  phone-audit", "\n".join(screen))
        phone.settled()
        # eleven more seats, one named at the cap. A laptop holds all twelve on one
        # page, the reason beside the word; a phone puts each reason on its own line,
        # so the same twelve page. The capped name is cut, never wrapped. The highlight stays
        # on phone-audit, now eleventh, and the page up is the one it is on.
        for n in range(2, 12):
            self.seat(f"audit-seat-{n:02d}")
        self.seat(LONG_NAME)
        phone.keys("Left")                   # an arrow that moves nothing: a draw, and no more
        if narrow:
            screen = phone.until("your projects", "11  phone-au", prompt="q leave")
            self.assertRegex(self.whole_page(screen, width, height), r" \d+/\d+$")
        else:
            screen = phone.until("your projects", "12  zz-very-long-session-", prompt="q leave")
            self.whole_page(screen, width, height)
            self.assertEqual(self.numbers(screen), set(range(1, 13)))
        self.assertEqual(self.marked(screen), 11)
        self.assertNotIn("m more", "\n".join(screen))
        # a number is answered from whichever page is up: 12 opens the twelfth seat, its two
        # digits inside half a second, and its bar says the row's own words; past the width the
        # left half is cut, with one ellipsis, where it would reach the one key
        phone.press("12")
        if narrow:
            screen = phone.until(STAND_IN, LONG_NAME[:20], "Ctrl-b m  menu")
        else:
            screen = phone.until(STAND_IN, "Ctrl-b m  menu", "· astra")
        bar = screen[-1]
        self.fits(screen, width, height)
        if narrow:
            self.assertIn(LONG_NAME[:20], bar)
            self.assertIn("…", bar)
        else:
            self.assertIn(LONG_NAME, bar)
            # the word the row shows is on the bar too, beside the one key
            self.assertIn(f"{LONG_NAME} · astra → opus · ! needs you", bar)
        self.assertTrue(bar.endswith("Ctrl-b m  menu"), bar)
        phone.keys("C-b", "d")
        screen = phone.until("your projects", prompt="q leave")

        def full(screen):
            self.whole_page(screen, phone.width, phone.height)
            return screen
        # every number is answered where it stands, on one page or across them
        screen = full(screen)
        if not narrow:
            self.assertEqual(self.numbers(screen), set(range(1, 13)))
            self.assertNotIn("m more", "\n".join(screen))
        # the popup over a seat holds fewer rows still, and pages them the same way
        phone.press("11")                    # phone-audit, eleventh by name
        phone.until(STAND_IN, "phone-audit · astra")
        phone.keys("C-b", "m")
        screen = phone.until("q close", "your projects", " 1/", prompt="q close")
        self.every_page(phone, screen, self.popup_page, 12, 8)
        phone.press("q")
        phone.until(STAND_IN, absent=["q close"])
        phone.settled()                      # its screen goes before its process does
        phone.keys("C-b", "d")
        phone.until("your projects", prompt="q leave")
        # `c` lists the config, `i` is one screen, `r` is no key and says nothing
        phone.press("c")
        phone.until("add a model", "esc back")
        phone.press("q")
        phone.until("your projects", "q leave", prompt="q leave")
        phone.press("i")
        phone.until("you talk to one orchestrator", "esc back")
        phone.press("q")
        phone.until("your projects", "q leave", prompt="q leave")
        phone.press("r")
        screen = phone.until("your projects", "q leave", absent=["not a key"], prompt="q leave")
        # the terminal turned, then held short: the layout follows on the next redraw
        phone.resize(100, 30)
        screen = phone.redraw("12  zz-very-long-session-", "q leave")
        self.whole_page(screen, 100, 30)
        self.assertNotIn("m more", "\n".join(screen))
        phone.resize(40, 12)
        screen = phone.redraw("your projects", "/")
        # held short the frame goes compact: heading, rows, keys and prompt only
        self.fits(screen, 40, 12)
        self.assertNotIn("usage left", "\n".join(screen))
        self.every_page(phone, screen, lambda lines: lines, 12, 6)
        # the popup over a seat on that short screen fills it, and still pages rows
        phone.press("11")
        phone.until(STAND_IN, "phone-audit · astra")
        phone.keys("C-b", "m")
        screen = phone.until("q close", "1/", prompt="q close")
        self.assertIn("no project", "\n".join(Terminal.inside(screen)))
        self.every_page(phone, screen, self.popup_page, 12, 8)
        phone.press("q")
        phone.until(STAND_IN, absent=["q close"])
        phone.settled()                      # its screen goes before its process does
        phone.keys("C-b", "d")
        phone.until("your projects", prompt="q leave")
        phone.resize(width, height)
        # the frame is back at the new size, on the page the highlight is on
        screen = phone.redraw("agentkit", "your projects")
        self.whole_page(screen, width, height)
        # x stops the highlighted seat, on whichever page it is, once `Stop` answers the question
        # under its row; q leaves without a word of error
        screen = self.moved(phone, "j", screen)          # from phone-audit, eleventh, to twelfth
        self.assertEqual(self.marked(screen), 12)
        phone.press("x")
        screen = "\n".join(phone.until("everything it runs?", "Keep", prompt="esc keep"))
        if narrow:   # the name is wider than the question's room, so it breaks where it must
            self.assertIn("zz-very-long-session-name-for-a-narrow", screen)
        else:
            self.assertIn(f"Stop {LONG_NAME} and everything it runs?", screen)
        self.stop_answered(phone)
        screen = phone.until("your projects", "11 need you", absent=[LONG_NAME[:20]],
                             prompt="q leave")
        self.whole_page(screen, width, height)
        self.assertIn("11 need you", "\n".join(screen))
        self.assertFalse(self.has_seat(LONG_NAME))
        self.assertTrue(self.has_seat("phone-audit"))
        phone.press("q")
        deadline = time.monotonic() + 10
        while not phone.dead():
            self.assertLess(time.monotonic(), deadline, "\n".join(phone.screen()))
            time.sleep(0.1)
        self.assertEqual(phone.tmux("display-message", "-p", "-t", "phone",
                                    "#{pane_dead_status}").strip(), "0")

    def test_forty_columns_by_twenty_four_rows(self):
        self.walk(40, 24)

    def test_a_hundred_columns_by_thirty_rows(self):
        self.walk(100, 30)


if __name__ == "__main__":
    unittest.main()
