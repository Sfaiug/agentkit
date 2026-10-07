#!/usr/bin/env python3
"""The rulebook one orchestrator session is launched with, written where its harness can read it.

The checkout's `AGENTS.md` section `What ak is for`, where present, then `orchestrator.md`,
with this host's own `~/.agentkit/rules.md` after it where there is one -- the owner's rules
for this machine, which agentkit ships and writes nowhere -- and the `AGENTS.md` of the project
the session is filed under (`config.seat_rulebook`).
Nothing is installed into the user's harness configuration: these rules reach the session whose
launch asked for them, at launch, and no other session anybody ever runs.

Usage: rulebook.py <session>

Prints the path of ~/.agentkit/state/rulebook-<session>.md -- under $AGENTKIT_RULEBOOK_DIR
instead, for a dry run -- which the adapter's `interactive` command line hands to its harness by
whatever means that harness has.  A launch has written the file before it asks its adapter
(`orch.command`) and names it in $AGENTKIT_RULEBOOK, which the adapter takes instead of running
this; an adapter run on its own has no such file, and this writes it.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, orch


text = config.rulebook_text
write = orch.write_rulebook


def main(argv):
    if len(argv) != 1 or argv[0].startswith("-"):
        print("usage: rulebook.py <session>", file=sys.stderr)
        return 2
    print(write(argv[0]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except config.Error as exc:
        # the adapter that asked for it refuses the launch on this: a session is opened with
        # its rules or not at all
        sys.exit(f"rulebook: {exc}")
