"""`ak` draws its main screen at once and Esc leaves at once, whatever start-up is doing.

`menu.main` in-process on a keyboard it has taken, its four start-up steps -- the look at
origin, the Mac bridge, the boot resume and maintenance -- each a fake taking two seconds, in the
process the menu forks for them: the first frame is out within 100 ms of starting and Esc leaves
within 100 ms, with a 600 ms read of the seats still going, and every step still reaches its end;
what resume and maintenance say, and what the Mac bridge prints, lands as a notice once each is
done, and never before the first frame.  With origin ahead, the update's steps are half a second
apart: the rule under `agentkit · updating` fills through all of them while ↓ still moves the
highlight within 100 ms, then the menu opens again (os.execv, stubbed) on the seat highlighted;
with `i` open over it as it opened, on `i` again, a failed install's lines shown first; with a
key typed into `n`, once he is back on the menu.  Esc during it leaves within 100 ms and the
update still reaches its end.  Offline, in a throwaway HOME; the probe is never started, and
every thread and process the menu leaves behind is waited for before the fakes go.
"""

import json
import os
import select
import sys
import threading
import time
from contextlib import redirect_stdout
import io
from unittest.mock import patch
import unittest

from test_v4n import Sandbox
from agentkit import config, macbridge, menu, orch, terminal, update, watch

SLOW = 2.0        # what each start-up step takes
READ = 0.6        # what a read of the seats takes once the first is drawn
FRAME = 0.1       # what the first frame, a key or Esc may take
WIDTH = 90
Key = terminal.Key
STEP = 0.5        # what each of the update's own steps takes


class Keyboard:
    """A terminal the menu has taken, so keys are `terminal.Key`s and the screen is written over."""

    def take(self):
        return True

    def give(self):
        pass

    def close(self):
        pass


class Reopened(Exception):
    pass


class OpensAtOnce(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        repo = config.CODE / "acme"
        (repo / ".git").mkdir(parents=True)
        self.seats = [{"name": name, "repo": str(repo), "path": str(repo), "created": 0}
                      for name in ("fix-api", "tidy-docs", "web-portal")]
        self.gone = threading.Event()         # the test is over: every fake returns at once
        self.reads, self.ahead, self.said, self.slow, self.fails = [], False, [], SLOW, False
        self.marker = self.root / "moved"
        self.threads = set(threading.enumerate())

        def listing(*args, **kwargs):
            if self.reads:                    # the first read is the cache; any after it is slow
                self.reads.append(time.monotonic())
                self.gone.wait(READ)
            self.reads.append(time.monotonic())
            return [dict(seat) for seat in self.seats]

        # the steps run in the forked process: what they leave is files, and what they say a log
        def step(name, said=None, printed=None):
            def run(*args, log=None, **kwargs):
                time.sleep(self.slow)
                if said:
                    (log or args[-1])(said)
                if printed:
                    print(printed, file=sys.stderr)
                (self.root / name).touch()
            return run

        def behind(*args, **kwargs):
            step("origin")()
            return self.ahead

        def update_agentkit(progress=None):
            for done in range(4):         # as each of fetch, pull and install begins, then done
                progress(done, 3)
                time.sleep(STEP)
            self.marker.write_text("new")
            if self.fails:
                print("update: $ install.sh")
                print("update: install.sh exited 1")
            return int(self.fails)

        for target, name, fake in (
                (orch, "listing", listing),
                (menu, "run_records", list),
                (menu, "seat_row_state", lambda cfg, session, look=True, **facts:
                 {"word": "working", "reason": "", "since": None}),
                (menu.history, "estimate_seconds", lambda repo: 600),
                (menu, "seat_progress", lambda name: (1, 3)),
                (orch, "job_notices", lambda: []),
                (menu, "show_notices", lambda messages: self.said.append(messages)),
                (menu.Live, "probe", lambda self, now=None: False),
                (menu, "read", lambda prompt, default=None: default),
                (terminal, "Keyboard", Keyboard),
                (terminal, "sense", lambda: None),
                (terminal, "width", lambda *args: WIDTH),
                (config, "server_alias", lambda: None),
                (update, "agentkit_dir", lambda: config.REPO),
                (update, "left_as_is", lambda: ""),
                (update, "behind", behind),
                (update, "agentkit_version", lambda: "new" if self.marker.exists() else "old"),
                (update, "update_agentkit", update_agentkit),
                (macbridge, "start_background",
                 step("macbridge", printed="ak macbridge: could not start reader: offline")),
                (watch, "resume_after_boot", step("resume", "resumed fix-api after reboot")),
                (orch, "maintenance",
                 step("maintenance", "agentkit: reaped a loop whose process was gone")),
                (menu.os, "execv", self.execv)):
            self.stack.enter_context(patch.object(target, name, fake))
        self.stack.enter_context(patch.dict(menu._ESTIMATES, clear=True))
        # a stdin that never says anything, for a screen that waits on a key
        reader, self.typed = os.pipe()       # what is written to `typed` is a key pressed
        self.addCleanup(os.close, self.typed)
        self.stack.enter_context(patch.object(sys, "stdin", open(reader)))
        self.addCleanup(sys.stdin.close)
        self.addCleanup(self.settle)   # before the patches go: every thread left behind has ended

    def execv(self, path, argv):
        raise Reopened(json.loads(os.environ[menu.REOPENED]))

    def settle(self):
        """Every thread the menu left behind ended, its start-up process's reader with it."""
        self.gone.set()
        for thread in set(threading.enumerate()) - self.threads:
            thread.join(15)
            self.assertFalse(thread.is_alive(), thread)

    def menu(self, answer):
        """`ak`, each wait answered by `answer(screen, wake)` -- the screen last drawn whole, as
        lines -- or waited out on the wake pipe for a twentieth of a second when it answers None;
        what main answered, and when it started."""
        out, screens = io.StringIO(), []

        def wait_key(prompt, timeout=None, wake=None):
            text = terminal.ANSI.sub("", out.getvalue().rsplit("\033[H", 1)[-1])
            if "agentkit" in text:
                screens.append(text.splitlines())
            key = answer(screens[-1], wake)
            if key is None:
                select.select([wake] if wake is not None else [], [], [], 0.05)
            return key

        self.began = time.monotonic()
        with patch.object(menu, "wait_key", side_effect=wait_key), redirect_stdout(out):
            return menu.main([])

    def test_the_first_frame_and_esc_come_within_100_ms_behind_two_second_steps(self):
        keys, times = iter([None, Key("esc")]), []

        def answer(screen, wake):
            if times:                     # Esc once the read the first wait asked for is going
                until = time.monotonic() + 1
                while len(self.reads) < 2 and time.monotonic() < until:
                    time.sleep(0.005)
            times.append(time.monotonic())
            return next(keys)

        self.assertEqual(self.menu(answer), 0)
        left = time.monotonic()
        self.assertLess(times[0] - self.began, FRAME, "the first frame")
        self.assertLess(left - times[1], FRAME, "Esc")
        self.assertEqual(len(self.reads), 2, "the read is still going as the menu leaves")
        self.assertEqual(self.said, [])
        self.settle()                     # leaving stopped none of them half-way
        self.assertEqual(sorted(path.name for path in self.root.iterdir()
                                if path.name in ("origin", "macbridge", "resume", "maintenance")),
                         ["macbridge", "maintenance", "origin", "resume"])

    def test_what_resume_and_maintenance_say_lands_as_a_notice(self):
        times = []

        def answer(screen, wake):
            times.append(time.monotonic())
            return Key("esc") if len(self.said) == 3 else None

        self.assertEqual(self.menu(answer), 0)
        self.assertLess(times[0] - self.began, FRAME, "the first frame")
        self.assertEqual(self.said, [["ak macbridge: could not start reader: offline"],
                                     ["resumed fix-api after reboot"],
                                     ["agentkit: reaped a loop whose process was gone"]])
        self.assertGreater(len(times), 10)      # the screen answered all along

    def test_a_notice_that_lands_at_once_waits_for_the_first_frame(self):
        self.slow, seen = 0, []           # every step done the moment it starts

        def answer(screen, wake):
            seen.append(len(self.said))
            return Key("esc") if len(self.said) == 3 else None

        self.assertEqual(self.menu(answer), 0)
        self.assertEqual(seen[0], 0)
        self.assertEqual(len(self.said), 3)

    def test_an_update_fills_the_rule_while_a_key_answers_then_reopens_on_the_same_seat(self):
        self.ahead, rules, pressed = True, [], {}

        def answer(screen, wake):
            now = time.monotonic()
            header, rule = screen[:2]
            if header.startswith("agentkit · updating") and (not rules or rules[-1] != rule):
                rules.append(rule)
            lit = [line.split()[2] for line in screen if line.startswith("›")]
            if "at" in pressed and "frame" not in pressed:
                pressed["frame"] = now - pressed["at"], header[:19], lit
            if rules and "at" not in pressed:
                pressed["at"] = now
                return Key("down")
            return None

        with self.assertRaises(Reopened) as reopened:
            self.menu(answer)
        self.assertEqual(reopened.exception.args, (["tidy-docs", None],))
        self.assertEqual(rules, ["━" * 30 * done + "─" * (WIDTH - 30 * done) for done in range(4)])
        took, header, lit = pressed["frame"]
        self.assertLess(took, FRAME, "↓ during the update")
        self.assertEqual((header, lit), ("agentkit · updating", ["tidy-docs"]))
        # the new code, current: it opens on the seat that was highlighted
        self.settle()                     # forked as a fresh process forks: no thread up
        self.ahead, first = False, []
        os.environ[menu.REOPENED] = json.dumps(["tidy-docs", None])

        def again(screen, wake):
            first.append(([line.split()[2] for line in screen if line.startswith("›")],
                          screen[0][:19]))
            return Key("esc")

        self.assertEqual(self.menu(again), 0)
        self.assertEqual(first, [(["tidy-docs"], "agentkit" + " " * 11)])
        self.assertNotIn(menu.REOPENED, os.environ)

    def test_an_update_that_lands_under_a_screen_reopens_on_that_screen(self):
        self.ahead, self.fails, self.seats, opened = True, True, [], []

        def info(*args, **kwargs):        # `i`, waiting on a key until it is left
            opened.append(time.monotonic())
            while not self.reopened:
                terminal.read_key(0.05)

        def answer(screen, wake):
            return Key("char", "i") if screen[0].startswith("agentkit · updating") else None

        self.reopened = False
        with patch.object(menu, "show_info", side_effect=info), \
                self.assertRaises(Reopened) as reopened:
            self.menu(answer)
        self.assertEqual(reopened.exception.args, ([None, "char:i"],))
        self.assertEqual(len(opened), 1)
        self.assertEqual(self.marker.read_text(), "new")
        # moved, and install.sh failed after it: said before the new code opens
        self.assertEqual(self.said, [["update: $ install.sh", "update: install.sh exited 1"]])
        # the new code opens with `i` up again
        self.settle()                     # forked as a fresh process forks: no thread up
        self.ahead, self.fails, self.reopened = False, False, True
        os.environ[menu.REOPENED] = json.dumps([None, "char:i"])
        with patch.object(menu, "show_info", side_effect=info):
            self.assertEqual(self.menu(lambda screen, wake: Key("esc")), 0)
        self.assertEqual(len(opened), 2)

    def test_an_update_that_lands_under_something_typed_waits_for_the_menu(self):
        self.ahead, left = True, []

        def new(*args, **kwargs):         # `n`, `f` typed into its name, then Esc once it landed
            os.write(self.typed, b"f")
            self.assertEqual(terminal.read_key(1), Key("char", "f"))
            until = None
            while until is None or time.monotonic() < until:
                terminal.read_key(0.05)   # no reopen here: the `f` would be lost
                if until is None and self.marker.exists():
                    until = time.monotonic() + 0.5
            left.append(True)

        def answer(screen, wake):
            return Key("char", "n") if screen[0].startswith("agentkit · updating") else None

        with patch.object(menu, "new_session", side_effect=new), \
                self.assertRaises(Reopened) as reopened:
            self.menu(answer)
        self.assertEqual((left, reopened.exception.args), ([True], (["fix-api", None],)))

    def test_esc_during_the_update_leaves_at_once_and_the_update_goes_on_to_its_end(self):
        self.ahead, pressed = True, []

        def answer(screen, wake):
            if screen[0].startswith("agentkit · updating"):
                pressed.append(time.monotonic())
                return Key("esc")
            return None

        self.assertEqual(self.menu(answer), 0)
        self.assertLess(time.monotonic() - pressed[0], FRAME, "Esc during the update")
        self.assertFalse(self.marker.exists())
        until = time.monotonic() + 10
        while not self.marker.exists() and time.monotonic() < until:
            time.sleep(0.05)
        self.assertEqual(self.marker.read_text(), "new")


if __name__ == "__main__":
    unittest.main(verbosity=2)
