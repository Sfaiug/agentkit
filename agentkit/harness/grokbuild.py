"""Grok Build: a launcher-issued conversation, and the session directory it opens.

Everything else about this harness is data -- adapters/grokbuild.sh and
adapters/grokbuild.toml -- so the one hook here is the one thing that needs a path rule:
where its sessions live.
"""

import os
from pathlib import Path
from urllib.parse import quote


def opened(cwd, conversation):
    """Has Grok written that conversation down yet, where it keeps them?

    One directory per workspace under its sessions, named for the url-encoded working
    directory, each conversation a directory of its own inside it.  A directory that
    exists is resumed; one that does not is opened fresh under the same id, which is what
    `--session-id` demands: a valid UUID that does not already exist.
    """
    home = Path(os.environ.get("GROK_HOME") or Path.home() / ".grok")
    return (home / "sessions" / quote(str(cwd), safe="") / str(conversation)).is_dir()
