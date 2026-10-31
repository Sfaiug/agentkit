#!/usr/bin/env python3
"""Run a seat's harness in a terminal of its own, and look at the seat whenever its screen comes
to rest, starts moving, or its harness exits.

ak compacts no seat itself: each harness's own compaction does, and two compactors on one seat
can only clash.  So nothing is typed here.  The owner's terminal and the harness's are copied
both ways (`agentkit.pty_relay`); the harness's terminal is named on the seat's pane before the
harness starts, so ak's own typing waits while the harness has input it has not read
(`watch.pane_unread`); and the stream is watched for the moments a seat's word may change.  The
name is from when ak compacted idle seats through this: the panes of seats running now name it.
"""

import argparse
import errno
import fcntl
import os
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, orch, watch
from agentkit.pty_relay import Relay

DEFAULT_HARNESS = "claude"
SETTLE = 0.5    # output stopped this long is a screen at rest: the seat is looked at
# the longest the loop sleeps with nothing moving: a harness that exited while a process it
# started still holds its terminal, or a resize, is seen by then
WAKE = 5.0


def parse_args(argv):
    parser = argparse.ArgumentParser(usage="%(prog)s [--harness NAME] -- command [args...]")
    parser.add_argument("--harness", default=DEFAULT_HARNESS)
    if "--" not in argv:
        if any(arg in ("-h", "--help") for arg in argv):
            parser.parse_args(argv)
        parser.error("missing '--' before command")
    separator = argv.index("--")
    options = parser.parse_args(argv[:separator])
    command = argv[separator + 1 :]
    if not command:
        parser.error("missing command after '--'")
    return options, command


def copy_winsize(source_fd, pty_fd):
    try:
        size = fcntl.ioctl(source_fd, termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(pty_fd, termios.TIOCSWINSZ, size)
    except OSError:
        pass


class Looks:
    """The seat looked at again when its screen comes to rest, starts moving, or its harness exits.

    That is when what a seat does changes, on every harness, hook or no hook: a question
    answered, an Esc, an error that ended a turn, a harness with no hook for any of it.  A
    screen at rest or moving says only when to look, never what the seat is doing: the rules in
    its manifest say that.  So an edge reads the pane against them first, in a thread of its
    own, so the terminal never waits on tmux, and the seat's own look (`watch.hook_look`, which
    a hook starts) runs only where that reading is not what the seat's published word was
    decided from, whoever published it (`watch.unseen`): a harness that redraws once a second
    costs a capture a redraw, never a look.  One look at a time; edges during it are one more.
    """

    def __init__(self, seat, harness, socket, pane, look=None):
        self.seat, self.harness, self.socket, self.pane = seat, harness, socket, pane
        self.look = look or self.start
        self.wake = threading.Event()
        threading.Thread(target=self.follow, daemon=True).start()

    def start(self, wait=True):
        """A look, waited for; or, as this wrapper ends, one that waits for that end instead."""
        process = watch.start_look(self.seat, ending=not wait)
        if process and wait:
            process.wait()

    def read(self):
        """What the seat's own pane shows, as `watch.pane_text` captures it."""
        try:
            proc = subprocess.run(
                orch.tmux_argv("", "-S", self.socket, "capture-pane", "-p", "-e", "-J",
                               "-t", self.pane),
                capture_output=True, encoding="utf-8", errors="replace", timeout=5,
                env=orch.tmux_env())
        except (OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout if proc.returncode == 0 else None

    def follow(self):
        while True:
            self.wake.wait()
            self.wake.clear()
            self.check()

    def check(self):
        """Read the pane, and look at the seat where its word was decided from another reading."""
        pane = self.read()
        if pane is not None and watch.unseen(self.seat, self.harness, pane):
            self.look()


def seat_looks(harness):
    """The `Looks` of the named seat this wrapper runs in, or None outside one: only a seat's own
    pane, on its own server, has a word for a look to move (`watch.hook_look` checks the same)."""
    seat = os.environ.get(config.SESSION_ENV) or ""
    socket = os.environ.get("TMUX", "").partition(",")[0]
    pane = os.environ.get("TMUX_PANE", "")
    if not seat or "/" in seat or seat in (".", "..") or not socket or not pane:
        return None
    return Looks(seat, harness, socket, pane)


def exit_code(wait_status):
    code = os.waitstatus_to_exitcode(wait_status)
    return 128 - code if code < 0 else code


def name_input_tty(path):
    """The pane owns this fact across renames; respawning its harness forgets it."""
    pane = os.environ.get("TMUX_PANE")
    server = os.environ.get("TMUX", "").partition(",")[0]
    if not os.environ.get(config.SESSION_ENV) or not pane or not server:
        return
    rc, out = orch.tmux_out("-S", server, "set-option", "-p",
                            "-t", pane, orch.INPUT_TTY_OPTION, path,
                            socket="", timeout=5)
    if rc:
        raise OSError(errno.EIO, f"cannot name the harness terminal: {out}")


def run(options, command):
    child_pid, master_fd = os.forkpty()
    if child_pid == 0:
        try:
            # Only the forkpty child has the slave fd. Publish before the harness starts.
            name_input_tty(os.ttyname(0))
            os.execvp(command[0], command)
        except OSError as exc:
            try:
                os.write(2, f"idle-compact.py: {command[0]}: {exc.strerror}\n".encode())
            finally:
                os._exit(127)

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    terminal_attrs = None
    child_status = None
    relay = None
    resize_pending = True
    forwarded_signals = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGQUIT)
    old_handlers = {}

    terminal_fd = next(
        (fd for fd in (stdin_fd, stdout_fd, sys.stderr.fileno()) if os.isatty(fd)),
        None,
    )

    def request_resize(_signum, _frame):
        nonlocal resize_pending
        resize_pending = True

    def forward_signal(signum, _frame):
        try:
            os.kill(child_pid, signum)
        except ProcessLookupError:
            pass

    try:
        if os.isatty(stdin_fd):
            terminal_attrs = termios.tcgetattr(stdin_fd)
            tty.setraw(stdin_fd, termios.TCSANOW)

        old_handlers[signal.SIGWINCH] = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, request_resize)
        for signum in forwarded_signals:
            old_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward_signal)

        # when the screen last moved, and whether it has come to rest since: each turn of the two
        # has the seat looked at again
        drawn_mono, moving = time.monotonic(), False
        looks = seat_looks(options.harness)

        def output(_data):
            nonlocal drawn_mono, moving
            drawn_mono = time.monotonic()
            if looks is not None and not moving:
                moving = True
                looks.wake.set()

        def alive():
            nonlocal resize_pending, child_status
            if resize_pending:
                if terminal_fd is not None:
                    copy_winsize(terminal_fd, master_fd)
                resize_pending = False
            if child_status is None:
                waited_pid, wait_status = os.waitpid(child_pid, os.WNOHANG)
                if waited_pid:
                    child_status = wait_status
            return child_status is None

        relay = Relay(master_fd, stdin_fd, stdout_fd, output)
        while relay.active and alive():
            relay.poll(max(0.0, drawn_mono + SETTLE - time.monotonic()) if moving else WAKE)
            if moving and time.monotonic() - drawn_mono >= SETTLE:
                moving = False
                looks.wake.set()

        relay.finish()

        if child_status is None:
            _, child_status = os.waitpid(child_pid, 0)
        if looks is not None:
            # without waiting for it, as this wrapper is ending
            looks.look(wait=False)
        return exit_code(child_status)
    finally:
        if relay is not None:
            relay.close()
        if terminal_attrs is not None:
            termios.tcsetattr(stdin_fd, termios.TCSANOW, terminal_attrs)
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        try:
            os.close(master_fd)
        except OSError:
            pass
        if child_status is None:
            try:
                os.kill(child_pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                waited_pid, _ = os.waitpid(child_pid, os.WNOHANG)
                if waited_pid:
                    break
                time.sleep(0.02)
            else:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.waitpid(child_pid, 0)
                except ChildProcessError:
                    pass


def main():
    options, command = parse_args(sys.argv[1:])
    try:
        return run(options, command)
    except Exception as exc:
        print(f"idle-compact.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
