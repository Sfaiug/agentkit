#!/usr/bin/env python3
"""The rulebook one orchestrator session is launched with, written where its harness can read it.

`orchestrator.md` from the checkout, with this host's own `~/.agentkit/rules.md` after it where
there is one -- the owner's rules for this machine, which agentkit ships and writes nowhere.
Nothing is installed into the user's harness configuration: these rules reach the session whose
launch asked for them, at launch, and no other session anybody ever runs.

Usage: rulebook.py <session>

Writes ~/.agentkit/state/rulebook-<session>.md -- under $AGENTKIT_RULEBOOK_DIR instead, for a
dry run -- and prints its path; the adapter's `interactive` command line hands that path to its
harness by whatever means that harness has.
"""
import os
from pathlib import Path
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
    path = config.rulebook_path(session)
    if os.environ.get(config.RULEBOOK_DIR_ENV):
        path = Path(os.environ[config.RULEBOOK_DIR_ENV]) / path.name
    path.parent.mkdir(parents=True, exist_ok=True)
    body = text()
    if config.session_records().get(session, {}).get("unnamed"):
        body = (f"{body.rstrip()}\n\nThis seat is unnamed. As soon as the conversation tells you "
                "what the job is, name this seat with `ak orch rename --auto <name>`. Choose the "
                "shortest possible name, at most three words, saying what the work is.\n")
    path.write_text(body)
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
