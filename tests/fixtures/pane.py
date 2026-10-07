"""What a seat's pane runs, for a fake tmux that never runs it (`orch.seat_command`)."""
import json
import shlex
from pathlib import Path


def resolved(args):
    """A tmux argv whose pane command is replaced by what the pane runs: the line the seat's
    launch file execs, read as tmux is asked to start it (the next launch of that seat rewrites
    the file), through the seat's boot (`harness`)."""
    if "new-session" not in args and "respawn-pane" not in args:
        return args
    _, path = shlex.split(args[-1])
    _, line = Path(path).read_text().splitlines()
    return (*args[:-1], shlex.join(harness(shlex.split(line.removeprefix("exec ")))))


def harness(words):
    """A command whose seat's boot (`orch.boot`) execs a harness, with that harness in its place:
    the boot's steps taken here as the pane takes them, the bar dressed at once."""
    if "boot" not in words or words[words.index("boot") - 1] != "orch":
        return words
    from agentkit import orch, statusbar
    at = words.index("boot")
    return [*words[:at - 3], *orch.booted(json.loads(words[at + 1]), statusbar.dress)]


class Started:
    """A stand-in for `orch.start` that boots the seat's pane here (`harness`), as tmux would
    start it, and keeps the command each harness was started with."""

    def __init__(self):
        self.commands = []

    def __call__(self, name, cwd, cmd, model):
        self.commands.append(harness(cmd))
