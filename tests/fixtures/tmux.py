"""tmux's own reading of an argv, for a fake that answers as tmux 3.5a does."""


def commands(args):
    """Each command of a command list, in the order tmux runs them (`;` between them)."""
    command = []
    for word in args:
        if word == ";":
            yield tuple(command)
            command = []
        else:
            command.append(word)
    yield tuple(command)
