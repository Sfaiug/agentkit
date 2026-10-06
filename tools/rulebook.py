#!/usr/bin/env python3
"""The rulebook one orchestrator session is launched with, written where its harness can read it.

The checkout's `AGENTS.md` section `What ak is for`, where present, then `orchestrator.md`,
with this host's own `~/.agentkit/rules.md` after it where there is one -- the owner's rules
for this machine, which agentkit ships and writes nowhere -- and the `AGENTS.md` of the project
the session is filed under (`config.seat_rulebook`).
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
from agentkit import config, orch


text = config.rulebook_text


def write(session):
    """That text, under the name of the session it is for.  Its path.

    A launch reads its project's rules as merged now: it fetches them first, whichever way the
    seat opens.  Offline, it opens on the rules as last fetched; the tick fetches them later and
    the seat's next prompt names them.  A dry run fetches nothing.
    """
    repo = os.environ.get(config.SEAT_REPO_ENV)
    if repo is None:
        repo = config.session_records().get(session, {}).get("repo") or ""
    path = config.rulebook_path(session)
    if os.environ.get(config.RULEBOOK_DIR_ENV):
        path = Path(os.environ[config.RULEBOOK_DIR_ENV]) / path.name
    elif repo:
        try:
            orch.fetch_project(Path(repo))
        except config.Error:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.seat_rulebook(session, repo))
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
