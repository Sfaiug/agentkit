"""What a seat's pane runs, for a fake tmux that never runs it (`orch.seat_command`)."""
import shlex
from pathlib import Path


def resolved(args):
    """A tmux argv whose pane command, the seat's launch file, is replaced by the line it execs,
    read as tmux is asked to start it: the next launch of that seat rewrites the file."""
    if "new-session" not in args and "respawn-pane" not in args:
        return args
    _, path = shlex.split(args[-1])
    _, line = Path(path).read_text().splitlines()
    return (*args[:-1], line.removeprefix("exec "))
