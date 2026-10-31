"""Whether each seat's product is up, told from the machine ak runs on: one page to the owner
once it stays down, and one card mentioning nobody once it is back.

A product's own pager runs on its host, so it cannot report that host, its database or itself
being down; ak's tick runs on another machine.  A project's `alive:` names a command that exits
0 while its product is up and prints why when it is not.  Hidden here: running the checks --
each tick, the `alive:` of every project a seat is filed under that the tick fetched, as its
default branch declares it, in its checkout, CEILING seconds at most --, each outage, kept
in state/alive.json from tick to tick, and the cards' wording.
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
    """The tick's pass, after `orch.fetch_projects` filled `fetched`: each seat's project read;
    while it is down its down card asked for until it is out, and once that is out, from the
    pass that ends the outage on, its back card until that is.  Down is every read failing
    since one at least DOWN ago.  A card whose moment is over is never asked for again: a pass
    ends an outage whose down card is not out with no back card, and a failing read before the
    back card is out begins a new outage.  A project the tick could not fetch counts no read,
    so ak's own connection going down never pages; one with no seat, or declaring no `alive:`,
    forgets its state."""
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
        outage = last.get(repo)     # its first failing read, and once over, its first pass
        since, back = outage if isinstance(outage, list) else (outage, None)
        name = Path(repo).name
        if not up:
            since = kept[repo] = now if since is None or back else since    # none open: begins one
            if now - since >= DOWN:
                line = (f"\U0001f534 {name} is down since <t:{int(since)}:t> · "
                        f"{(said.splitlines() or ['no output'])[-1][:CUT]}")    # 🔴
                notify.page(f"down:{repo}:{since}", name, line, line=line, owed=True)
        elif since is not None and notify.paged(f"down:{repo}:{since}"):
            back = back or now
            line = f"{name} is back since <t:{int(back)}:t>, after {lasted(back - since)}"
            if notify.page(f"back:{repo}:{since}", name, line, line=line, owed=True,
                           mention=False):
                kept[repo] = [since, back]
    if kept != last:
        orch.replace_file(_path(), json.dumps(kept).encode())


def lasted(seconds):
    """How long an outage lasted: to the minute under a day, `45 min` or `2 h 5 min`, and in
    whole days after, `3 days`."""
    minutes = int(seconds) // 60
    hours, days = minutes // 60, minutes // (24 * 60)
    if days:
        return f"{days} day{'s' * (days > 1)}"
    if hours:
        return f"{hours} h" + f" {minutes % 60} min" * bool(minutes % 60)
    return f"{minutes} min"
