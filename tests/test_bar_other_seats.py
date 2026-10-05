"""Every seat's bar names the owner's other seats that need them, and a click switches to one.

Line one's right end: `! <name> needs you` in needs-you's colour for each other seat that
needs you, then `● N working` and `✓ N done`, each only when it is not zero; a seat never
counts itself.  A changed word, or a seat stopped, rewrites every other seat's bar at once,
and an older reading never lands after a newer word.  A click on a name switches to its seat;
every bar write binds that one key on ak's own server, and the wheel over a name moves no
seat's window.  Where line one is short of room the names fold into `! 2 need you` before its
left part is cut.  Offline with `orch.tmux_out` patched, except the last case, which runs tmux
on a server of its own in this test's HOME and clicks through a pseudo-terminal.
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

from test_v4n import Sandbox
from agentkit import config, notify, orch, statusbar, terminal, watch

IDS = {"fix-api": "$0", "atlas-proxies": "$1", "web": "$2", "zeta": "$3"}
WORDS = {"fix-api": "working", "atlas-proxies": "needs you", "web": "working", "zeta": "done"}
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
            return 0, "\n".join(f"{sid}\t{name}" for name, sid in self.ids.items())
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

    def test_a_line_one_names_who_needs_you_and_counts_the_rest_never_itself(self):
        statusbar.dress("fix-api", "fable")
        named = self.options["fix-api"][statusbar.SEATS]
        self.assertEqual(drawn(named), "! atlas-proxies needs you   ● 1 working   ✓ 1 done ")
        self.assertIn(f"#[range=right]#[fg=#{NEEDS},bold]! atlas-proxies needs you"
                      "#[default]#[norange]", named)          # a click away, in its colour
        # the name is the right end's first 25 of its 51 cells, counted from the client's edge
        at = statusbar.AT
        self.assertEqual(self.options["fix-api"][statusbar.HIT],
                         f"#{{?#{{&&:#{{e|>:{at},26}},#{{e|<=:{at},51}}}},$1,}}")
        self.assertEqual(drawn(self.options["fix-api"][statusbar.FOLD]),
                         "! 1 needs you   ● 1 working   ✓ 1 done ")
        self.assertNotIn("range=", self.options["fix-api"][statusbar.FOLD])
        # the names and their lookup in one tmux command list, which no click can land inside
        whole = [args for args, _ in self.calls if statusbar.HIT in args]
        self.assertEqual({(args[3::6], args[5::6]) for args in whole},
                         {((statusbar.SEATS, statusbar.FOLD, statusbar.HIT), (";", ";"))})
        found = statusbar.seats()
        self.assertEqual(found[1], ("$1", "atlas-proxies", "needs you"))
        named, folded, hit = statusbar.others(found, "atlas-proxies")
        self.assertEqual(drawn(named), "● 2 working   ✓ 1 done ")
        self.assertEqual((named, hit), (folded, ""))
        # only the words there are, each only when it is not zero; no other seat, nothing
        self.assertEqual(drawn(statusbar.others([("$1", "a", "working"), ("$2", "b", None)],
                                                "c")[0]), "● 1 working ")
        self.assertEqual(statusbar.others([("$0", "fix-api", "needs you")], "fix-api"),
                         ("", "", ""))

    def test_b_names_are_plain_text_and_two_fold_into_one_count(self):
        found = [("$4", "a#1", "needs you"), ("$5", "b%", "needs you"), ("$6", "me", "done")]
        named, folded, _ = statusbar.others(found, "me")
        self.assertIn("! a##1 needs you", named)
        self.assertIn("! b% needs you", named)
        self.assertEqual(drawn(folded), "! 2 need you ")

    def test_c_a_changed_word_reaches_every_other_bar_as_it_is_announced(self):
        answers = {name: {"word": word, "reason": "", "since": None}
                   for name, word in WORDS.items()}
        self.stack.enter_context(patch.object(watch, "session_state",
                                              side_effect=lambda name, **_kw: answers[name]))
        watch.announce_state(self.seat("fix-api"), cfg=self.cfg)
        self.assertEqual(list(self.options), ["fix-api"])     # no change: no other bar moves
        answers["atlas-proxies"] = {"word": "working", "reason": "", "since": None}
        watch.announce_state(self.seat("atlas-proxies"), cfg=self.cfg)
        for name in ("fix-api", "web", "zeta"):
            self.assertNotIn("needs you", drawn(self.options[name][statusbar.SEATS]), name)
        self.assertEqual(drawn(self.options["fix-api"][statusbar.SEATS]),
                         "● 2 working   ✓ 1 done ")
        self.assertEqual(drawn(self.options["zeta"][statusbar.FOLD]), "● 3 working ")
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
                                              return_value=[self.seat("atlas-proxies")]))
        with redirect_stdout(io.StringIO()):
            orch.cmd_stop(["atlas-proxies"])
        self.assertNotIn("atlas-proxies", self.ids)
        for name in ("fix-api", "web", "zeta"):
            self.assertNotIn("needs you", drawn(self.options[name][statusbar.FOLD]), name)
        self.assertEqual(drawn(self.options["zeta"][statusbar.SEATS]), "● 2 working ")

    def test_e_every_bar_write_binds_the_click_on_a_name_and_nothing_else(self):
        statusbar.dress("fix-api", "fable")
        # on ak's own server, so one that was up before the names came gets it too
        self.assertIn((statusbar.CLICK, "agentkit-test"), self.calls)
        self.assertEqual(statusbar.CLICK[:3], ("bind-key", "-n", "MouseDown1StatusRight"))
        self.assertEqual(statusbar.CLICK[5], f"#{{E:{statusbar.HIT}}}")   # only over a name
        self.assertEqual([line for line in orch.tmux_conf().read_text().splitlines()
                          if re.search(r"Mouse|Wheel|Drag", line)], [])
        for value in statusbar.FORMATS:   # no range of ak's but the names
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
                    and args[:4] == ("set-option", "-t", "=fix-api:", statusbar.SEATS)):
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
        self.assertIn("! web needs you", drawn(self.options["fix-api"][statusbar.SEATS]))


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
                for name in ("fix-api", "atlas-proxies")]

    def test_g_names_fold_before_the_left_part_is_cut_and_a_click_switches(self):
        self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "fix-api", "sleep 600")
        default = self.mouse_keys()
        self.assertEqual(self.tmux("source-file", str(orch.tmux_conf()))[0], 0)
        for name in ("atlas-proxies", "web", "zeta"):
            self.tmux("new-session", "-d", "-s", name, "sleep 600")
        for name in ("fix-api", "atlas-proxies"):
            self.tmux("new-window", "-d", "-t", f"={name}:", "sleep 600")
        for name, word in WORDS.items():
            watch.seat_write(name, word=word, reason="", word_since=None)
        config.save_session(self.cfg, "fix-api", "fable", ["astra"])
        with patch.object(orch, "tmux_out", side_effect=self.tmux):
            statusbar.redress({"name": "fix-api", "legacy": False},
                              {"word": "working", "reason": ""}, cfg=self.cfg)
        # the one key bound beside tmux's own: a click where only a name is drawn
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
        whole = " ▐● working▌  fix-api  fable orchestrates "   # 41 cells and the space after
        self.assertEqual(self.width(100), whole + "! atlas-proxies needs you   ● 1 working   "
                                                  "✓ 1 done ")
        # 88 is too narrow for the names beside the whole left part, and wide enough for the fold
        self.assertEqual(self.width(88), whole + "! 1 needs you   ● 1 working   ✓ 1 done ")
        # and narrower still, the left part is cut: one `…`, the whole line the client's width
        self.assertEqual(self.width(60), " ▐● working▌  fix-a…"
                                         " ! 1 needs you   ● 1 working   ✓ 1 done ")
        # the name is columns 50 to 74 of line one, row 19: the wheel over it moves no window
        self.width(100)
        for button, window in ((64, "1"), (65, "0")):        # up from the second, down from the first
            for name in ("fix-api", "atlas-proxies"):
                self.tmux("select-window", "-t", f"={name}:{window}")
            os.write(self.pty, f"\x1b[<{button};55;19M".encode())
            time.sleep(0.3)
            self.drain()
            self.assertEqual(self.active(), [window, window])
        # a click beside the name leaves the client where it is; one on the name moves it
        for column, session in ((3, "fix-api"), (49, "fix-api"), (80, "fix-api"),
                                (52, "atlas-proxies")):
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
            return drawn(self.tmux("show-options", "-qv", "-t", "=fix-api:", statusbar.SEATS)[1])
        with patch.object(orch, "tmux_out", side_effect=self.tmux), \
                patch.object(orch, "sessions", side_effect=sessions), \
                patch.object(watch, "sync_title"), \
                patch.object(orch, "user_manager", return_value=False):
            notify.record("web", "needs", "Choose a deployment region")
            self.assertEqual(watch.announce_state(seat("web"), cfg=self.cfg, records=[])["word"],
                             "needs you")
            statusbar._write("fix-api", "fable", "working", cfg=self.cfg)
            self.assertIn("! web needs you", named())
            # renamed, its word the same: fix-api names it by its new name as rename returns
            self.assertEqual(orch.rename("web", "renamed-web"), "renamed-web")
            self.assertIn("! renamed-web needs you", named())
            # gone by hand, then opened again under its name: named again as it opens
            self.assertEqual(self.tmux("kill-session", "-t", "=renamed-web:")[0], 0)
            statusbar._write("fix-api", "fable", "working", cfg=self.cfg)
            self.assertEqual(named(), "")
            orch.start("renamed-web", self.root, ["sleep", "600"], "fable")
            self.assertIn("! renamed-web needs you", named())


if __name__ == "__main__":
    unittest.main(verbosity=2)
