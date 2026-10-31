"""Whether each seat's product is up, told from the machine ak runs on: one page to the owner
once it stays down.

A product's own pager runs on its host, so it cannot report that host, its database or itself
being down; ak's tick runs on another machine.  A project's `alive:` names a command that exits
0 while its product is up and prints why when it is not.  Hidden here: running the checks --
each tick, the `alive:` of every project a seat is filed under that the tick fetched, as its
default branch declares it, in its checkout, CEILING seconds at most --, the down state, kept
in state/alive.json from tick to tick, and the card's wording.
"""

import json
import time
from pathlib import Path

from . import config, gitcall, notify, orch, watch

CEILING = 60    # a check still running then fails
DOWN = 5 * 60   # how long every read must have failed, from the first, before the owner is paged
CUT = 200       # the most of the check's last line a card carries


def _path():
    return config.STATE / "alive.json"


def tick(fetched):
    """The tick's pass, after `orch.fetch_projects` filled `fetched`: each seat's project read,
    and while it is down its card asked for until it is out.  Down is every read failing since
    one at least DOWN ago, so a pass forgets the project, and its card, sent or not, is never
    asked for again.  A project the tick could not fetch counts no read, so ak's own connection
    going down never pages; one with no seat, or declaring no `alive:`, forgets its state."""
    try:
        last = json.loads(_path().read_text())
    except (OSError, ValueError):
        last = {}
    kept = {}
    for repo in sorted({record["repo"] for record in config.session_records().values()
                        if record.get("repo")}):
        if Path(repo) not in fetched:
            if repo in last:
                kept[repo] = last[repo]
            continue
        env = gitcall.project_env(repo)
        commit = gitcall.git(repo, "rev-parse", "--verify", "--quiet", config.RULES_REF,
                             check=False, env=env)
        command = commit and gitcall.declared_at(repo, commit, "alive", env=env)
        if not command:
            continue
        now = time.time()     # when this read starts: earlier checks may have taken minutes
        up, said = watch.health_command(repo, commit, command, timeout=CEILING)
        if up:
            continue
        since = kept[repo] = last.get(repo, now)
        if now - since >= DOWN:
            line = (f"\U0001f534 {Path(repo).name} is down since <t:{int(since)}:t> · "
                    f"{(said.splitlines() or ['no output'])[-1][:CUT]}")    # 🔴
            notify.page(f"down:{repo}:{since}", Path(repo).name, line, line=line, owed=True)
    if kept != last:
        orch.replace_file(_path(), json.dumps(kept).encode())
