"""What a seat's pane runs, for a fake tmux that never runs it (`orch.seat_command`)."""
import shlex
from pathlib import Path


def resolved(args):
    """The spawn command's argv with its launch file replaced by the line it execs.

    Ignore following option commands: these fakes inspect only what the pane runs.
    Read at spawn, because the next launch of that seat rewrites the file.
    """
    if "new-session" not in args and "respawn-pane" not in args:
        return args
    from agentkit.guard import commands
    args = tuple(next(commands(args)))
    _, path = shlex.split(args[-1])
    line = Path(path).read_text().splitlines()[-1]
    return (*args[:-1], line.removeprefix("exec "))
