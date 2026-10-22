"""What a seat's pane runs, for a fake tmux that never runs it (`orch.seat_command`)."""
import shlex
from pathlib import Path


def resolved(args):
    """The spawn command's argv with its launch file replaced by the command it execs.

    Ignore the option commands around it: these fakes inspect only what the pane runs.
    Read at spawn, because the next launch of that seat rewrites the file.
    """
    if "new-session" not in args and "respawn-pane" not in args:
        return args
    from agentkit.guard import commands
    args = tuple(next(c for c in commands(args) if {"new-session", "respawn-pane"} & set(c)))
    _, path = shlex.split(args[-1])
    # the command is the file's last statement, and may run over several lines
    return (*args[:-1], Path(path).read_text().split("\nexec ", 1)[1].removesuffix("\n"))
