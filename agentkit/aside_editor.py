"""The owner's unsent text set aside for a line of ak's, through the editor a seat's harness hands
its composer to.

Launched with `EDITOR` as its $VISUAL (`launch_env`), a harness opens its composer in that
editor on the keys its manifest names (`[screen] editor`), and `edit` does what ak asked of the
pane just before (`request`, a pane option the edit clears): `out` keeps the composer's text in a
tmux buffer of the pane's (`kept`) and hands back an empty composer; `back` hands the kept text
back to a composer handed over empty, and keeps it past one that holds anything.  No text is ever
dropped: a second `out` adds to what is kept.  Asked nothing, it opens the owner's own editor.
It imports nothing of ak's, as it starts on every edit the owner opens.
"""

import os
import subprocess
import time
from pathlib import Path

EDITOR = Path(__file__).resolve().parent.parent / "tools" / "aside-editor"
OWNER = "AK_OWNER_EDITOR"       # the owner's own editor, as the seat's launch found it
ASK = "@ak_aside"
FRESH = 10                      # an ask older than this was not for the edit now opened


def launch_env(environ):
    """The `NAME=value` words that make this editor a seat's own, with the owner's beside it --
    the one an enclosing seat's launch found, where this launch runs inside a seat."""
    owner = environ.get(OWNER, environ.get("VISUAL") or environ.get("EDITOR") or "")
    return [f"VISUAL={EDITOR}", f"EDITOR={EDITOR}", f"{OWNER}={owner}"]


def request(mode):
    """The pane option's value asking the next edit for `out` or `back`."""
    return f"{mode} {time.time():.0f}"


def kept(pane):
    """The tmux buffer that holds the text set aside from that pane, for as long as it is."""
    return f"{ASK[1:]}-{pane.lstrip('%')}"


def launched(pid, tty):
    """Whether the seat pane whose process has that id, on that terminal, was launched with this
    editor as its $VISUAL.  The harness inherits its environment from the last process down from
    there still on the pane's terminal: the launch, execed into the harness's wrapper, which
    runs the harness on a terminal of its own -- whether or not the shell tmux runs the pane's
    command in is still above it.  A tool the harness runs may have been given another, and a
    seat started before opens the owner's editor over its composer."""
    try:
        while pid.isdigit():
            below = [child for task in Path(f"/proc/{pid}/task").glob("*/children")
                     for child in task.read_text().split() if _stdin(child) == tty]
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


def edit(argv):
    """The editor's body: the file the harness hands it is its last argument."""
    pane = os.environ.get("TMUX_PANE", "")
    # read and cleared in one call: one ask moves one composer
    said = _tmux("show-options", "-pqv", "-t", pane, ASK, ";",
                 "set-option", "-pu", "-t", pane, ASK) if pane and argv else None
    mode, _, at = (said or b"").decode(errors="replace").strip().partition(" ")
    try:
        fresh = time.time() - float(at) <= FRESH
    except ValueError:
        fresh = False
    if fresh and mode in ("out", "back"):
        path, name = Path(argv[-1]), kept(pane)
        # tmux fails to save a buffer it lacks as it fails for any other reason, so only one it
        # lists is read: what cannot be read leaves both the buffer and the composer as they are
        listed = _tmux("list-buffers", "-F", "#{buffer_name}")
        held = None if listed is None else (
            _tmux("save-buffer", "-b", name, "-") if name.encode() in listed.splitlines() else b"")
        if held is None:
            return 0
        text = path.read_bytes()
        if mode == "out" and text.strip():
            both = b"\n".join(part for part in (held, text) if part.strip())
            if _tmux("load-buffer", "-b", name, "-", data=both) is not None:
                path.write_bytes(b"")
        # the owner can type between ak's empty read and this edit: what they typed stays as
        # it is, the kept text with ak until the composer empties again
        elif mode == "back" and held and not text:
            path.write_bytes(held)
            _tmux("delete-buffer", "-b", name)
        return 0
    owner = os.environ.get(OWNER) or "vi"
    os.execvp("sh", ["sh", "-c", f'{owner} "$@"', owner, *argv])
