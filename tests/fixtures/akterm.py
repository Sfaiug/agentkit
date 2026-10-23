"""A person's terminal for an answer-key test: ak run in a tmux pane of its own.

tmux is the terminal emulator, so what the pane shows is what a person would see, colours and
all, and keys reach the program as a person's would, through a terminal of the size asked for.
It is a server of its own, never ak's, and the program sees no TMUX variable: to ak it is the
terminal a person started it from.

    from fixtures.akbin import Home
    from fixtures.akterm import Terminal
    with Home() as home:
        menu = Terminal(home, size=(100, 40))
        menu.wait("no login")
        menu.keys("q")
"""

import shlex
import tempfile
import time
from pathlib import Path

from .akbin import AK

SERVER = "agentkit-term"
# Every row is the program's.  The server outlives its last terminal, so the next one never
# meets it on its way out ("server exited unexpectedly"); the Home's close ends it.
CONF = "set -g status off\nset -g default-terminal xterm-256color\nset -g exit-empty off\n"
# The program's exit status goes to a file, and the pane then stays as the program left it:
# tmux's own `remain-on-exit` scrolls the screen a line to say the pane is dead.  The shell
# outlives a Ctrl-C that ends the program, whose SIGINT stays its default; the program gets ak's
# colours, which the Home's NO_COLOR turns off for its piped runs.
KEEP = 'trap : INT; env -u TMUX -u TMUX_PANE -u NO_COLOR "$@"; echo $? >"$0"; exec sleep 86400'


class Terminal:
    """`args` run after the program `AK_BIN` names; `env` adds to its environment."""

    def __init__(self, home, *args, size=(100, 40), env=None):
        self.home = home
        conf = home.root / "terminal.conf"
        conf.write_text(CONF)
        self.status = Path(tempfile.mkdtemp("-terminal", dir=home.root)) / "status"   # its own
        command = shlex.join(["sh", "-c", KEEP, str(self.status),
                              *(f"{key}={value}" for key, value in (env or {}).items()),
                              AK, *args])
        done = home.tmux("-f", str(conf), "new-session", "-d", "-x", str(size[0]),
                         "-y", str(size[1]), "-c", str(home.path), "-P", "-F", "#{pane_id}",
                         command, server=SERVER)
        assert done.code == 0, done.err
        self.pane = done.out.strip()

    def keys(self, *keys):
        """Press keys by tmux's names for them: `Down`, `Enter`, `Escape`, `C-c`, `q`."""
        self._ask("send-keys", "-t", self.pane, *keys)

    def type(self, text):
        """Type text as it is, a character at a time."""
        self._ask("send-keys", "-t", self.pane, "-l", text)

    def resize(self, width, height):
        self._ask("resize-window", "-t", self.pane, "-x", str(width), "-y", str(height))

    def screen(self, colours=False):
        """What the terminal shows now; `colours` keeps the escape sequences that draw them."""
        return self._ask("capture-pane", "-p", *(["-e"] if colours else []), "-t", self.pane)

    def wait(self, shown, bound=30):
        """The screen once it shows that text, or that test of it holds; the program draws when
        it is ready, and a test that reads earlier reads nothing."""
        test = shown if callable(shown) else (lambda screen: shown in screen)
        deadline = time.monotonic() + bound
        while True:
            screen = self.screen()
            if test(screen):
                return screen
            if time.monotonic() > deadline:
                raise AssertionError(f"the terminal never showed {shown!r}; it shows:\n{screen}")
            time.sleep(0.05)

    def exit_code(self, bound=30):
        """The program's exit status once it has ended."""
        deadline = time.monotonic() + bound
        while True:
            status = self.status.read_text() if self.status.exists() else ""
            if status.endswith("\n"):
                return int(status)
            if time.monotonic() > deadline:
                raise AssertionError(f"still running after {bound} s:\n{self.screen()}")
            time.sleep(0.05)

    def _ask(self, *args):
        done = self.home.tmux(*args, server=SERVER)
        assert done.code == 0, done.err
        return done.out
