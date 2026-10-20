"""The owner's unsent text set aside for a line of ak's, through the editor a seat's harness hands
its composer to.

Launched with `EDITOR` as its $VISUAL (`launch_env`), a harness opens its composer in that
editor on the keys its manifest names (`[screen] editor`), and `edit` takes the step ak asked of
the pane just before (`request`, a pane option the edit clears) on what the composer holds, which
no screen draws late or cropped, and answers in that option once it is done (`answer`).  `line`
hands back ak's line, what else the composer holds kept in a tmux buffer of the pane's (`kept`,
`ASIDE`) beside any text kept before, and answers `line`.  `back` answers what the composer it is
handed after that line's Enter holds -- nothing (`sent`), the line (`unsent`) or other text -- and
over either of the first two hands the kept text back, kept on as given back (`GIVEN`): whatever
the next `line` finds in the composer then is the owner's.  Each is written whole or not at all;
a step that fails is undone and answers nothing, and tmux refusing to mark text given back leaves
it in the composer and kept, so given back twice at worst, never lost.  An ask ak gave up on
(`none`) hands the composer back as it is, to an edit its keys opened late.  Asked nothing, it
opens the owner's own editor.  It imports nothing of ak's but `host`, which imports nothing itself, as
it starts on every edit the owner opens.
"""
import contextlib
import os
import subprocess
import time
from pathlib import Path

from . import host

EDITOR = Path(__file__).resolve().parent.parent / "tools" / "aside-editor"
OWNER = "AK_OWNER_EDITOR"       # the owner's own editor, as the seat's launch found it
ASK = "@ak_aside"
FRESH = 10                      # an ask older than this was not for the edit now opened
ASIDE, GIVEN = "a", "g"         # a kept text's first letter: set aside, or given back since


def launch_env(environ):
    """The `NAME=value` words that make this editor a seat's own, with the owner's beside it --
    the one an enclosing seat's launch found, where this launch runs inside a seat."""
    owner = environ.get(OWNER, environ.get("VISUAL") or environ.get("EDITOR") or "")
    return [f"VISUAL={EDITOR}", f"EDITOR={EDITOR}", f"{OWNER}={owner}"]


def request(mode, line=""):
    """The pane option's value asking the next edit for `line`, `back` or `none`, with ak's
    line."""
    return f"{mode} {time.time():.6f} {line}"


def answer(ask, said):
    """What the edit asked with `ask` answered, read from the pane option as `said`, or None."""
    _, at, _ = ask.split(" ", 2)
    mode, _, rest = said.removesuffix("\n").partition(" ")
    then, _, word = rest.partition(" ")
    return word if mode == "did" and then == at and word else None


def kept(pane):
    """The tmux buffer that holds the text set aside from that pane, for as long as it is."""
    return f"{ASK[1:]}-{pane.lstrip('%')}"


def launched(pid, tty):
    """Whether the seat pane whose process has that id, on that terminal, was launched with this
    editor as its $VISUAL.  The harness inherits its environment from the last process down from
    there still on the pane's terminal: the launch, execed into the harness's wrapper, which
    runs the harness on a terminal of its own -- whether or not the shell tmux runs the pane's
    command in is still above it.  A tool the harness runs may have been given another, and a
    seat started before opens the owner's editor over its composer.  Each process's parent is
    read, as a kernel built without CONFIG_PROC_CHILDREN lists no task's children."""
    try:
        parents = {entry.name: str(stat.ppid) for entry in host.PROC.iterdir()
                   if entry.name.isdigit() and (stat := host.proc_stat(entry.name)) is not None}
        while pid.isdigit():
            below = [child for child, parent in parents.items()
                     if parent == pid and _stdin(child) == tty]
            if not below:
                env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
                return any(entry.startswith(b"VISUAL=")
                           and Path(os.fsdecode(entry[7:])).resolve() == EDITOR for entry in env)
            pid = below[0]
    except OSError:
        pass
    return False


def _stdin(pid):
    try:
        return os.readlink(f"/proc/{pid}/fd/0")
    except OSError:
        return None


def _tmux(*args, data=None):
    try:
        proc = subprocess.run(["tmux", *args], input=data, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _keep(name, data):
    """Whether tmux now keeps `data` in that buffer, or none where it is empty."""
    return (_tmux("load-buffer", "-b", name, "-", data=data) if data
            else _tmux("delete-buffer", "-b", name)) is not None


def _publish(path, data):
    """Whether the composer at `path` now holds `data`: written beside it and moved over it, so no
    failed write hands the harness part of either."""
    temp = path.with_name(f".{path.name}.{os.getpid()}.ak")
    try:
        mode = os.stat(path).st_mode & 0o777
        with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), "wb") as out:
            os.fchmod(out.fileno(), mode)       # the composer's own, which the umask narrows
            out.write(data)
        os.replace(temp, path)
        return True
    except OSError:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)
        return False


def edit(argv):
    """The editor's body: the file the harness hands it is its last argument."""
    pane = os.environ.get("TMUX_PANE", "")
    # read and cleared in one call: one ask moves one composer
    said = _tmux("show-options", "-pqv", "-t", pane, ASK, ";",
                 "set-option", "-pu", "-t", pane, ASK) if pane and argv else None
    mode, _, rest = (said or b"").removesuffix(b"\n").partition(b" ")
    at, _, line = rest.partition(b" ")
    try:
        fresh = time.time() - float(at) <= FRESH
    except ValueError:
        fresh = False
    if fresh and mode == b"none":
        return 0
    if fresh and mode in (b"line", b"back"):
        path, name = Path(argv[-1]), kept(pane)
        # tmux fails to save a buffer it lacks as it fails for any other reason, so only one it
        # lists is read: what cannot be read leaves both the buffer and the composer as they are
        listed = _tmux("list-buffers", "-F", "#{buffer_name}")
        stored = None if listed is None else (
            _tmux("save-buffer", "-b", name, "-") if name.encode() in listed.splitlines() else b"")
        if stored is None:
            return 0
        state, held, text = stored[:1].decode(), stored[1:], path.read_bytes()
        # the line as the harness hands it over, ending in a newline or not
        ours = bool(line) and text.rstrip() == line.rstrip()
        if mode == b"line":
            word = b"line"
            if not ours:            # a composer holding the line got it from an edit before
                keep = (ASIDE.encode() + (held + b"\n" + text if state == ASIDE else text)
                        if text.strip() else stored if state == ASIDE else b"")
                # a failed step is undone too, as tmux's server can do one its client then
                # times out on
                if not ((keep == stored or _keep(name, keep)) and _publish(path, line)):
                    _keep(name, stored)
                    return 0
        else:
            word = b"sent" if not text.strip() else b"unsent" if ours else b"other"
            if state == ASIDE and word != b"other" and _publish(path, held):
                _keep(name, GIVEN.encode() + held)
        _tmux("set-option", "-p", "-t", pane, ASK, f"did {os.fsdecode(at)} {os.fsdecode(word)}")
        return 0
    owner = os.environ.get(OWNER) or "vi"
    os.execvp("sh", ["sh", "-c", f'{owner} "$@"', owner, *argv])
