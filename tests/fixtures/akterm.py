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
import sys
import tempfile
import time
from pathlib import Path

from .akbin import AK, REPO

SERVER = "agentkit-term"
KEPT = ".agentkit/state/background"     # where a menu keeps its terminal's answer, light or dark
# Every row is the program's.  The server outlives its last terminal, so the next one never
# meets it on its way out ("server exited unexpectedly"); the Home's close ends it.
CONF = "set -g status off\nset -g default-terminal xterm-256color\nset -g exit-empty off\n"
# The program's exit status goes to a file, and the pane then stays as the program left it:
# tmux's own `remain-on-exit` scrolls the screen a line to say the pane is dead.  The shell
# outlives a Ctrl-C that ends the program, whose SIGINT stays its default; the program gets ak's
# colours, which the Home's NO_COLOR turns off for its piped runs.
KEEP = 'trap : INT; env -u TMUX -u TMUX_PANE -u NO_COLOR "$@"; echo $? >"$0"; exec sleep 86400'
# A page of Python ak's menu by itself, as the menu runs one: painted, on a keyboard it has taken.
PAGE = """import sys
sys.path.insert(0, {repo!r})
from contextlib import closing
from agentkit import config, menu, terminal
terminal.screens()
with closing(terminal.Keyboard()) as keyboard:
    if keyboard.take():
        terminal.sense()
    menu.{page}(config.load())
"""


def forget(home):
    """Nothing kept of any terminal's background, as where no menu has asked yet: black."""
    (home.path / KEPT).unlink(missing_ok=True)


class Terminal:
    """`args` run after `program`, by default the one `AK_BIN` names; `env` adds to its
    environment.  `page` names a page of Python ak's menu (agentkit/menu.py) to run by itself
    instead, over the Home's config: one no row opens, which no claim of Go's can reach."""

    def __init__(self, home, *args, size=(100, 40), env=None, program=AK, page=None):
        if page:
            program, args = sys.executable, ("-c", PAGE.format(repo=str(REPO), page=page))
        self.home = home
        conf = home.root / "terminal.conf"
        conf.write_text(CONF)
        self.status = Path(tempfile.mkdtemp("-terminal", dir=home.root)) / "status"   # its own
        command = shlex.join(["sh", "-c", KEEP, str(self.status),
                              *(f"{key}={value}" for key, value in (env or {}).items()),
                              program, *args])
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

    def screen(self, colours=False, copied=False, blank=False):
        """What the terminal shows now; `colours` keeps the escape sequences that draw them,
        `copied` reads it as a person's selection copies it, a line the terminal wrapped whole,
        and `blank` keeps the blank cells at each line's end."""
        return self._ask("capture-pane", "-p", *(["-e"] if colours else []),
                         *(["-J"] if copied else []), *(["-N"] if blank else []), "-t", self.pane)

    def wait(self, shown, bound=30):
        """The screen once it shows that text, or that test of it holds; the program draws when
        it is ready, and a test that reads earlier reads nothing.  tmux may be read part way
        through a draw, so what a test asserts of the screen belongs in the test it waits for."""
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
