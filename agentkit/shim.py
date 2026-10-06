"""The body every PATH shim shares (tmux-shim, gh-shim, ...): find the real binary, engage only for
a seat's own by-hand call, ask the guard, else exec the real one.

It imports only the standard library at the top, and the guard lazily inside a try, so a guard that
cannot import -- a pre-3.11 python shadowing `tomllib`, a checkout caught mid-update -- still execs
the real binary.  A shim that fails loudly is a seat that cannot work.
"""

import os
import sys
from pathlib import Path


def real(name, invoked):
    """The first `name` on PATH in a directory AFTER this shim's own, never the shim itself.

    Starting after the shim's own directory (matched by real path) means a wrapper placed ahead of
    the shim -- one that calls through to the shim -- is never chosen, which would loop; a wrapper
    between the shim and the real binary is chosen, so it chains.  If the shim's directory is not on
    PATH (it was invoked by an absolute path), the whole PATH is searched.
    """
    me = Path(invoked).resolve()
    mine = os.path.realpath(Path(invoked).parent)
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    after = parts
    for i, part in enumerate(parts):
        if os.path.realpath(part) == mine:
            after = parts[i + 1:]
            break
    for part in after:
        cand = Path(part) / name
        if cand.is_file() and os.access(cand, os.X_OK) and cand.resolve() != me:
            return str(cand)
    return None


def run(name, refusal):
    """Run a seat's `name` through its guard, or exec the real one.  `refusal` names the guard
    function to ask (`refusal` for tmux, `gh_refusal` for gh).  A seat with no record, a worker
    (AK_RUN_ROLE=worker), and every failure run the real binary unchanged."""
    invoked = Path(sys.argv[0] if os.path.basename(sys.argv[0]) == name else __file__)
    args = sys.argv[1:]
    real_bin = real(name, invoked)
    if real_bin is None:
        sys.stderr.write(f"{name}-shim: no real {name} on PATH\n")
        return 127
    if os.environ.get("AGENTKIT_SESSION") and os.environ.get("AK_RUN_ROLE") != "worker":
        try:
            from . import guard
            reason = getattr(guard, refusal)(args, real_bin)
        except Exception:                 # a guard that will not import stops no seat's command
            reason = None
        if reason:
            sys.stderr.write(reason + "\n")
            return 1
    os.execv(real_bin, [real_bin, *args])
