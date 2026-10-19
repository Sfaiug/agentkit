"""The owner's unsent text set aside for a line of ak's, through the editor a seat's harness hands
its composer to.

Launched with `EDITOR` as its $VISUAL (`launch_env`), a harness opens its composer in that
editor on the keys its manifest names (`[screen] editor`), and `edit` does what ak asked of the
pane just before (`request`, a pane option the edit clears): `out` keeps the composer's text in a
tmux buffer of the pane's (`kept`) and hands back an empty composer; `back` hands the kept text
back, ahead of whatever the composer holds by then.  No text is ever dropped: a second `out` adds
to what is kept.  Asked nothing, it opens the owner's own editor.  It imports nothing of ak's, as
it starts on every edit the owner opens.
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


def launched(pid):
    """Whether the harness in the seat pane whose process has that id -- under it, as every
    seat's runs under its launch script and idle-compact.py -- was started with this editor as
    its $VISUAL: one started before opens the owner's editor over its composer."""
    stack, seen = [pid] if pid.isdigit() else [], set()
    while stack:
        each = stack.pop()
        if each in seen:
            continue
        seen.add(each)
        try:
            env = Path(f"/proc/{each}/environ").read_bytes().split(b"\0")
            stack += [child for task in Path(f"/proc/{each}/task").glob("*/children")
                      for child in task.read_text().split()]
        except OSError:
            continue
        if any(entry.startswith(b"VISUAL=") and Path(os.fsdecode(entry[7:])).resolve() == EDITOR
               for entry in env):
            return True
    return False


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
        text, held = path.read_bytes(), _tmux("save-buffer", "-b", name, "-") or b""
        both = b"\n".join(part for part in (held, text) if part.strip())
        if mode == "out" and text.strip():
            if _tmux("load-buffer", "-b", name, "-", data=both) is not None:
                path.write_bytes(b"")
        elif mode == "back" and held:
            path.write_bytes(both)
            _tmux("delete-buffer", "-b", name)
        return 0
    owner = os.environ.get(OWNER) or "vi"
    os.execvp("sh", ["sh", "-c", f'{owner} "$@"', owner, *argv])
