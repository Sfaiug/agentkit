"""Every seat's bar says how many of the owner's other seats need them, and a click goes there.

Line one's right end, the owner's design (14 Oct 2026): `! 2 other seats need you` in
needs-you's colour, bold, while any other seat needs you, and nothing otherwise; a seat never
counts itself, and where line one is short of room it folds to `! 2 need you` before anything
is cut.  A changed word, or a seat stopped, rewrites every other seat's bar at once,
and an older reading never lands after a newer word.  A click on it switches to the first of
them; every bar write binds that one key on ak's own server, and the wheel over it moves no
seat's window.  Offline with
`orch.tmux_out` patched, except the last cases, which run tmux on a server of their own in
this test's HOME and click through a pseudo-terminal.
"""

from contextlib import redirect_stdout
import fcntl
import io
import os
import re
import shutil
import signal
import struct
import subprocess
import termios
import threading
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, notify, orch, statusbar, terminal, watch
from agentkit.guard import commands

IDS = {"fix-api": "$0", "orbit-proxies": "$1", "web": "$2", "zeta": "$3"}
WORDS = {"fix-api": "working", "orbit-proxies": "needs you", "web": "working", "zeta": "done"}
NEEDS = terminal.STATE_STYLES["needs you"][2]


def drawn(value):
    """An option's text as tmux draws it: styles dropped, the doubled `#` single."""
    return re.sub(r"#\[[^\]]*\]", "", value).replace("##", "#")


class OtherSeats(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        os.environ.pop("AGENTKIT_SESSION", None)   # the owner stops a seat, not the seat running this
        self.options, self.calls, self.ids = {}, [], dict(IDS)
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        for name, word in WORDS.items():
            watch.seat_write(name, word=word, reason="", word_since=None)

    def tmux(self, *args, socket=None, **_kw):
        self.calls.append((args, socket))
        if args[:2] == ("list-sessions", "-F"):
            return 0, "\n".join(f"{sid}:{name}:1" for name, sid in self.ids.items())
        if args[0] == "kill-session":
            del self.ids[args[-1].lstrip("=")]
        command = []
        for word in (*args, ";"):            # a command list, as tmux takes one
            if word != ";":
                command.append(word)
                continue
            if command[:1] == ["set-option"]:   # each seat's own options, by its exact target
                self.assertRegex(command[2], r"^=[^:]+:$")
                self.options.setdefault(command[2][1:-1], {})[command[3]] = command[-1]
            command = []
        return 0, ""

    def seat(self, name, **extra):
        return {"name": name, "path": "", "created": 0, "attached": False, "exited": False,
                "legacy": False, "resumable": False, **extra}

    def test_a_line_one_counts_who_else_needs_you_never_itself(self):
        statusbar.dress("fix-api", "fable")
        needing = self.options["fix-api"][statusbar.NEED]
        self.assertEqual(drawn(needing), "! 1 other seat needs you ")
        self.assertIn(f"#[range=right]#[fg=#{NEEDS},bold]! 1 other seat needs you"
                      "#[default]#[norange]", needing)          # a click away, in its colour
        # its 24 cells and the space after them, counted from the client's edge
        at = statusbar.AT
        self.assertEqual(self.options["fix-api"][statusbar.HIT],
                         f"#{{?#{{&&:#{{e|>:{at},1}},#{{e|<=:{at},25}}}},$1,}}")
        # each seat's count and its lookup side by side in one tmux command list, which no
        # click can land inside
        (sent,) = [args for args, _ in self.calls if statusbar.HIT in args]
        ends = (statusbar.NEED, statusbar.FOLD, statusbar.HIT)
        self.assertEqual([command[2:4] for command in commands(sent) if command[3] in ends],
                         [[f"={name}:", option] for name in IDS for option in ends])
        found = statusbar.seats()
        self.assertEqual(found[1], ("$1", "orbit-proxies", "needs you"))
        # working and done seats are no one's business on another bar, nor a seat itself
        self.assertEqual(statusbar.others(found, "orbit-proxies"), ("", "", ""))
        self.assertEqual(statusbar.others([("$0", "fix-api", "needs you")], "fix-api"),
                         ("", "", ""))

    def test_b_two_are_one_count_and_the_click_goes_to_the_first(self):
        found = [("$4", "a#1", "needs you"), ("$5", "b%", "needs you"), ("$6", "me", "done")]
        needing, folded, hit = statusbar.others(found, "me")
        self.assertEqual(drawn(needing), "! 2 other seats need you ")
        self.assertEqual(drawn(folded), "! 2 need you ")
        self.assertTrue(hit.endswith(",$4,}"), hit)

    def test_c_a_changed_word_reaches_every_other_bar_as_it_is_announced(self):
        answers = {name: {"word": word, "reason": "", "since": None}
                   for name, word in WORDS.items()}
        self.stack.enter_context(patch.object(watch, "session_state",
                                              side_effect=lambda name, **_kw: answers[name]))
        watch.announce_state(self.seat("fix-api"), cfg=self.cfg)
        self.assertEqual(list(self.options), ["fix-api"])     # no change: no other bar moves
        answers["orbit-proxies"] = {"word": "working", "reason": "", "since": None}
        watch.announce_state(self.seat("orbit-proxies"), cfg=self.cfg)
        for name in ("fix-api", "web", "zeta"):
            self.assertEqual(self.options[name][statusbar.NEED], "", name)
        # every read and write on ak's own server, each bar's options on its own seat only
        for args, socket in self.calls:
            self.assertEqual(socket, "agentkit-test")
            self.assertIn(args[0], ("list-sessions", "set-option", "bind-key"))
        # a legacy seat lives on the owner's own server: nothing is read or written for it
        self.calls.clear()
        answers["web"] = {"word": "done", "reason": "", "since": None}
        watch.announce_state(self.seat("web", legacy=True), cfg=self.cfg)
        self.assertEqual(self.calls, [])

    def test_d_a_stopped_seat_leaves_every_other_bar_at_once(self):
        self.stack.enter_context(patch.object(orch, "sessions",
                                              return_value=[self.seat("orbit-proxies")]))
        with redirect_stdout(io.StringIO()):
            orch.cmd_stop(["orbit-proxies"])
        self.assertNotIn("orbit-proxies", self.ids)
        for name in ("fix-api", "web", "zeta"):
            self.assertEqual(self.options[name][statusbar.NEED], "", name)

    def test_e_every_bar_write_binds_the_click_on_a_name_and_nothing_else(self):
        statusbar.dress("fix-api", "fable")
        # on ak's own server, so one that was up before the names came gets it too
        writes = [(args, socket) for args, socket in self.calls if args[0] != "list-sessions"]
        self.assertTrue(writes)
        for args, socket in writes:
            self.assertEqual((args[-len(statusbar.CLICK):], socket),
                             (statusbar.CLICK, "agentkit-test"))
        self.assertEqual(statusbar.CLICK[:3], ("bind-key", "-n", "MouseDown1StatusRight"))
        self.assertEqual(statusbar.CLICK[5], f"#{{E:{statusbar.HIT}}}")   # only over the count
        self.assertEqual([line for line in orch.tmux_conf().read_text().splitlines()
                          if re.search(r"Mouse|Wheel|Drag", line)], [])
        for value in statusbar.FORMATS:   # no range of ak's but the count
            self.assertNotIn("range=", value)

    def test_f_an_older_reading_never_lands_after_a_newer_word(self):
        answers = {name: {"word": word, "reason": "", "since": None}
                   for name, word in WORDS.items()}
        self.stack.enter_context(patch.object(watch, "session_state",
                                              side_effect=lambda name, **_kw: answers[name]))
        paused, go = threading.Event(), threading.Event()

        def tmux(*args, **kw):
            # fix-api's own write, which read the seats before web came to need you, waits
            if (threading.current_thread().name == "older"
                    and args[:4] == ("set-option", "-t", "=fix-api:", statusbar.NEED)):
                paused.set()
                go.wait(10)
            return self.tmux(*args, **kw)
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=tmux))
        older = threading.Thread(target=watch.announce_state, name="older",
                                 args=(self.seat("fix-api"),), kwargs={"cfg": self.cfg})
        older.start()
        self.assertTrue(paused.wait(10))
        answers["web"] = {"word": "needs you", "reason": "", "since": None}
        newer = threading.Thread(target=watch.announce_state, name="newer",
                                 args=(self.seat("web"),), kwargs={"cfg": self.cfg})
        newer.start()
        deadline = time.monotonic() + 10
        while watch.seat_read("web").get("word") != "needs you":
            self.assertLess(time.monotonic(), deadline, "web never announced")
            time.sleep(0.02)
        time.sleep(0.3)        # web's writes have had all the time they need, had they not waited
        go.set()
        older.join(10)
        newer.join(10)
        self.assertEqual(drawn(self.options["fix-api"][statusbar.NEED]), "! 2 other seats need you ")


class OnTmux(Sandbox):
    """tmux 3.5a itself, on a server in this test's HOME, with a client in a pseudo-terminal."""

    def setUp(self):
        super().setUp()
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.sockets = self.root / "sockets"
        self.sockets.mkdir()
        # the socket named from its own directory: below sockaddr_un's limit in any checkout
        self.env = {**os.environ, "TMUX_TMPDIR": str(self.sockets), "TERM": "xterm-256color"}
        self.env.pop("TMUX", None)
        self.argv = ["tmux", "-S", "agentkit-test"]
        self.addCleanup(subprocess.run, [*self.argv, "kill-server"], env=self.env,
                        cwd=self.sockets, capture_output=True)

    def tmux(self, *args, **_kw):
        done = subprocess.run([*self.argv, *args], env=self.env, cwd=self.sockets,
                              capture_output=True, text=True, timeout=10)
        return done.returncode, (done.stdout + done.stderr).rstrip("\n")

    def mouse_keys(self):
        """Every mouse binding the server has, in every key table."""
        return sorted(line for line in self.tmux("list-keys")[1].splitlines()
                      if re.search(r"Mouse|Wheel|Drag", line))

    def drain(self):
        """Read what the client draws, so it never blocks on a full terminal."""
        try:
            while os.read(self.pty, 65536):
                pass
        except (BlockingIOError, OSError):
            pass

    def until(self, check, what):
        deadline = time.monotonic() + 10
        while not check():
            self.assertLess(time.monotonic(), deadline, what)
            self.drain()
            time.sleep(0.05)

    def width(self, columns):
        fcntl.ioctl(self.pty, termios.TIOCSWINSZ, struct.pack("HHHH", 20, columns, 0, 0))
        self.client.send_signal(signal.SIGWINCH)
        self.until(lambda: self.tmux("list-clients", "-F", "#{client_width}")[1] == str(columns),
                   f"the client never became {columns} wide")
        name = self.tmux("list-clients", "-F", "#{client_name}")[1]
        return drawn(self.tmux("display-message", "-p", "-c", name, "-t", "=fix-api:",
                               statusbar.FORMATS[0])[1])

    def active(self):
        """Which window each of the two seats with two has up."""
        return [self.tmux("display-message", "-p", "-t", f"={name}:", "#{window_index}")[1]
                for name in ("fix-api", "orbit-proxies")]

    def test_g_the_count_folds_before_the_left_part_is_cut_and_a_click_switches(self):
        self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "fix-api", "sleep 600")
        default = self.mouse_keys()
        self.assertEqual(self.tmux("source-file", str(orch.tmux_conf()))[0], 0)
        for name in ("orbit-proxies", "web", "zeta"):
            self.tmux("new-session", "-d", "-s", name, "sleep 600")
        for name in ("fix-api", "orbit-proxies"):
            self.tmux("new-window", "-d", "-t", f"={name}:", "sleep 600")
        for name, word in WORDS.items():
            self.tmux("set-option", "-t", f"={name}:", orch.MARK, "1")
            watch.seat_write(name, word=word, reason="", word_since=None)
        config.save_session(self.cfg, "fix-api", "fable", ["astra"])
        with patch.object(orch, "tmux_out", side_effect=self.tmux):
            statusbar.redress({"name": "fix-api", "legacy": False},
                              {"word": "working", "reason": ""}, cfg=self.cfg)
        # the one key bound beside tmux's own: a click where only the count is drawn
        added = sorted(set(self.mouse_keys()) - set(default))
        self.assertEqual([line.split()[3] for line in added], ["MouseDown1StatusRight"], added)
        self.assertEqual(sorted(set(default) - set(self.mouse_keys())), [])
        self.pty, terminal_end = os.openpty()
        self.addCleanup(os.close, self.pty)
        fcntl.ioctl(terminal_end, termios.TIOCSWINSZ, struct.pack("HHHH", 20, 100, 0, 0))
        self.client = subprocess.Popen([*self.argv, "attach", "-t", "=fix-api:"],
                                       stdin=terminal_end, stdout=terminal_end,
                                       stderr=terminal_end, env=self.env, cwd=self.sockets,
                                       start_new_session=True)
        os.close(terminal_end)
        self.addCleanup(self.client.wait, 10)
        self.addCleanup(self.client.kill)
        os.set_blocking(self.pty, False)
        self.until(lambda: self.tmux("list-clients", "-F", "#{client_session}")[1] == "fix-api",
                   "the client never attached")
        whole = " ● working   fix-api   Fable 5.1 "   # 32 cells and the space after
        self.assertEqual(self.width(100), whole + "! 1 other seat needs you ")
        # narrower, the count folds beside the whole left part, and only then is that cut: one
        # `…`, the whole line the client's width
        self.assertEqual(self.width(50), whole.rstrip() + " ! 1 needs you ")
        self.assertEqual(self.width(30), " ● working   f… ! 1 needs you ")
        # the count is columns 76 to 99 of line one, row 19: the wheel over it moves no window
        self.width(100)
        for button, window in ((64, "1"), (65, "0")):        # up from the second, down from the first
            for name in ("fix-api", "orbit-proxies"):
                self.tmux("select-window", "-t", f"={name}:{window}")
            os.write(self.pty, f"\x1b[<{button};85;19M".encode())
            time.sleep(0.3)
            self.drain()
            self.assertEqual(self.active(), [window, window])
        # a click beside the count leaves the client where it is; one on it moves it
        for column, session in ((3, "fix-api"), (49, "fix-api"), (70, "fix-api"),
                                (85, "orbit-proxies")):
            os.write(self.pty, f"\x1b[<0;{column};19M\x1b[<0;{column};19m".encode())
            self.until(lambda: self.tmux("list-clients", "-F",
                                         "#{client_session}")[1] == session,
                       f"a click at column {column} never reached {session}")
            time.sleep(0.3)
            self.assertEqual(self.tmux("list-clients", "-F", "#{client_session}")[1], session)

    def test_h_a_renamed_or_reopened_seat_is_named_on_every_other_bar_at_once(self):
        for name, word in (("fix-api", "working"), ("web", "needs you")):
            self.assertEqual(self.tmux("-f", "/dev/null", "new-session", "-d", "-s", name,
                                       "sleep 600")[0], 0)
            config.save_session(self.cfg, name, "fable", ["astra"])
            watch.seat_write(name, word=word, reason="", word_since=None)

        def sessions():
            return [{"name": line.partition("\t")[2], "legacy": False, "path": str(self.root),
                     "exited": False}
                    for line in self.tmux("list-sessions", "-F",
                                          "#{session_id}\t#{session_name}")[1].splitlines()]

        def seat(name):
            return next(found for found in sessions() if found["name"] == name)

        def named():
            return drawn(self.tmux("show-options", "-qv", "-t", "=fix-api:", statusbar.NEED)[1])
        with patch.object(orch, "tmux_out", side_effect=self.tmux), \
                patch.object(orch, "sessions", side_effect=sessions), \
                patch.object(watch, "sync_title"), \
                patch.object(orch, "user_manager", return_value=False):
            notify.record("web", "needs", "Choose a deployment region")
            self.assertEqual(watch.announce_state(seat("web"), cfg=self.cfg, records=[])["word"],
                             "needs you")
            statusbar._write("fix-api", "fable", "working", cfg=self.cfg)
            self.assertIn("! 1 other seat needs you", named())
            # renamed, its word the same: fix-api counts it still as rename returns
            self.assertEqual(orch.rename("web", "renamed-web"), "renamed-web")
            self.assertIn("! 1 other seat needs you", named())
            # gone by hand, then opened again under its name: counted again as it opens
            self.assertEqual(self.tmux("kill-session", "-t", "=renamed-web:")[0], 0)
            statusbar._write("fix-api", "fable", "working", cfg=self.cfg)
            self.assertEqual(named(), "")
            orch.start("renamed-web", self.root, ["sleep", "600"], "fable")
            self.assertIn("! 1 other seat needs you", named())


if __name__ == "__main__":
    unittest.main(verbosity=2)
