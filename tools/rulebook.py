#!/usr/bin/env python3
"""The rulebook one orchestrator session is launched with, written where its harness can read it.

`orchestrator.md` from the checkout, with this host's own `~/.agentkit/rules.md` after it where
there is one -- the owner's rules for this machine, which agentkit ships and writes nowhere.
Nothing is installed into the user's harness configuration: these rules reach the session whose
launch asked for them, at launch, and no other session anybody ever runs.

Usage: rulebook.py <session>

Writes ~/.agentkit/state/rulebook-<session>.md and prints its path; the adapter's `interactive`
command line hands that path to its harness by whatever means that harness has.
"""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config


def text():
    """The rulebook a session receives: the repo's, then this host's own.

    Only a host that has written no rules of its own has none: a rules.md that is there and
    cannot be read is an error, never an empty one, because a session opened without rules the
    owner did write is a session working to rules nobody chose.
    """
    body = (config.REPO / "orchestrator.md").read_text()
    try:
        local = (config.HOME / "rules.md").read_text()
    except FileNotFoundError:
        return body
    return f"{body.rstrip()}\n\n{local}" if local.strip() else body


def write(session):
    """That text, under the name of the session it is for.  Its path."""
    # a name is only ever a file name here; a seat called anything else still gets its rulebook
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", " ".join(str(session).split())).strip("-.") or "seat"
    path = config.STATE / f"rulebook-{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text())
    return path


def main(argv):
    if len(argv) != 1 or argv[0].startswith("-"):
        print("usage: rulebook.py <session>", file=sys.stderr)
        return 2
    print(write(argv[0]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except OSError as exc:
        # the adapter that asked for it refuses the launch on this: a session is opened with
        # its rules or not at all
        sys.exit(f"rulebook: {exc}")
