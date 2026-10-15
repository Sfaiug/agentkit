"""Compute and render the history scoreboard of delivered work, what escaped its reviews, and
ak's cost."""

import os
from pathlib import Path
import re
import subprocess
import time
from statistics import median

from . import config, gitcall, history, record, terminal, transitions

# The parts of a merged change's hours, each second of its runs' phase rows in the first that
# holds it: a model turn, else ak's own work (a check, or a merge step, which runs from the run's
# place in its landing line), else a wait.
PARTS = (("model", ("executor", "reviewer")), ("ak", ("done-when", "merge")),
         ("waiting", tuple(f"{wait} wait" for wait in history.WAIT_COLUMNS)))

ANSWERS_FOR = 7 * 86400   # a merged change answers for its lines this long: a later change on the
                          # default branch that deletes a line it added inside this window, and
                          # does not add that line back elsewhere, rewrote it; a revert deletes
                          # every line it added.  The nearest measure ak has of what a review let
                          # through: not every rewrite is a defect, and churn falls on every
                          # reviewer's changes alike, so reviewers are compared by it

# What the board measures, row by row: the board's key, the row's label, and the parts each
# week's cell is built from, in the vision's order (quality and speed, then cost, then size).
# The owner's yes changes it (AGENTS.md, Owner rules), and tests/test_scoreboard_measures.py
# pins it, so a board that measures something else is a visible test change, never a quiet one.
MEASURES = (
    ("products", "products", ("runs", "merged", "first_round", "unmerged", "hours", "tokens")),
    ("ak", "ak", ("runs", "merged", "first_round", "unmerged", "hours", "tokens", "token_share")),
    ("intent", "intent", ("done", "hours", "live_hours")),
    ("owner", "owner", ("asked", "paged", "hours")),
    ("built", "built", ("seat_merged", "seat_first_round", "worker_merged", "worker_first_round")),
    ("waits", "waits", ("compute", "merge_hours", "lander_hours")),
    ("merged", "merged", ("model", "ak", "waiting", "seat")),
    ("parks", "parks", ("parked",)),
    ("sunk", "sunk", ("share", "tokens")),
    ("escaped", "escaped", ("merged", "escaped", "open", "unknown", "reviewers")),
    ("size", "ak size", ("code_lines", "readme_words", "agents_words")),
)

PULL_REQUEST = re.compile(r".+#\d+")   # a change named by its pull request: `owner/repo#N`

# The measures a week's loss is read from, in the vision's order -- quality, speed, cost,
# size: the words for it, the board's row, the part of that row's week (a share where two
# parts make one), whether more is worse, and how it prints (`said`).  The weekly audit's.
LOSSES = (
    ("merged changes with a line rewritten within 7 days", "escaped", ("escaped", "merged"), True, "%"),
    ("product runs ended without merging", "products", "unmerged", True, "%"),
    ("product runs merged in round 1", "products", "first_round", False, "%"),
    ("ak's runs ended without merging", "ak", "unmerged", True, "%"),
    ("ak's runs merged in round 1", "ak", "first_round", False, "%"),
    ("hours from the owner's first message to done", "intent", "hours", True, "h"),
    ("hours from the owner's first message to live", "intent", "live_hours", True, "h"),
    ("hours to merge a product run", "products", "hours", True, "h"),
    ("hours to merge a run on ak", "ak", "hours", True, "h"),
    ("run time waiting for a slot or a suite turn", "waits", "compute", True, "%"),
    ("hours a merged change spent waiting", "merged", "waiting", True, "h"),
    ("questions asked of the owner", "owner", "asked", True, "n"),
    ("cards sent to the owner", "owner", "paged", True, "n"),
    ("tokens per merged product run", "products", "tokens", True, "n"),
    ("tokens per merged run on ak", "ak", "tokens", True, "n"),
    ("ak's share of all tokens", "ak", "token_share", True, "%"),
    ("tokens spent on runs that never merged", "sunk", "share", True, "%"),
    ("runs the park stopped", "parks", "parked", True, "n"),
    ("ak's code lines", "size", "code_lines", True, "n"),
    ("ak's README words", "size", "readme_words", True, "n"),
    ("ak's AGENTS.md words", "size", "agents_words", True, "n"),
)


def reading(stats, part):
    """One measure off one week's row: None with no row; a share where `part` is (of, by)."""
    if stats is None:
        return None
    if isinstance(part, tuple):
        of, by = part
        return stats[of] / stats[by] if stats[by] else None
    return stats[part]


def said(value, form):
    """A measure's value in words: a share as a percentage, hours to a tenth, a count whole."""
    if value is None:
        return "not recorded"
    if form == "%":
        return f"{value:.0%}"
    if form == "h":
        return f"{value:.1f} hours"
    return f"{value:,.0f}"


def loss(board):
    """The week's largest loss off a two-week board: (words, this week, the week before, form)
    of the first measure in the vision's order that reads worse than the week before, else the
    first that reads at all this week; None when nothing does.  The order is the judgement:
    a quality measure a shade worse names the loss however much faster or cheaper the week
    was, since speed and cost count only while quality held (the owner, 14 Oct).  A row the
    board lacks reads as none, so a board from before a row was added answers the same way."""
    first = None
    for words, key, part, higher_worse, form in LOSSES:
        now, before = (reading(stats, part) for stats in board.get(key, (None, None)))
        if now is None:
            continue
        first = first or (words, now, before, form)
        if before is not None and (now > before if higher_worse else now < before):
            return words, now, before, form
    return first


def _git(repo, *args, ok=(0,)):
    """That repository's git output, or None when it cannot answer in time."""
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=10)
        if result.returncode in ok:
            return result.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def branch_log(repo, since):
    """The default branch's first-parent commits since `since`, oldest first, each as `sha`,
    `at` (its commit time) and the lines it added and deleted against its first parent, as
    (path, text) with the text stripped, those holding a letter or digit, a rename keyed by
    its old path for what it deleted and its new for what it added; None where git cannot
    say.  One git call per repository: the default branch is `origin/HEAD`, else `HEAD`."""
    head = _git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    out = _git(repo, *gitcall.patch_args(
        "log", "--first-parent", "--diff-merges=first-parent", "--format=commit %H %ct",
        "--since=" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since)),
        head.decode().strip() if head else "HEAD"))
    if out is None:
        return None
    # a commit's line opens it: no line of its patch starts so, a content line starting with
    # its mark, whatever bytes it holds
    parts = re.split(r"^commit (\S+) (\d+)$", out.decode("utf-8", "replace"), flags=re.M)
    commits = []
    for sha, at, patch in zip(parts[1::3], parts[2::3], parts[3::3]):
        current = {"sha": sha, "at": int(at), "added": set(), "deleted": set()}
        for old, new, lines in gitcall.patch_files(patch):
            for line in lines:
                path, text = {"+": new, "-": old}.get(line[:1]), line[1:].strip()
                if path and any(ch.isalnum() for ch in text):
                    current["added" if line[0] == "+" else "deleted"].add((path, text))
        commits.append(current)
    commits.reverse()
    return commits


def rewrote(later, added):
    """Whether that later commit deleted one of `added` without adding its text back elsewhere:
    a move is not a rewrite."""
    kept = {text for _, text in later["added"]}
    return any(text not in kept for _, text in added & later["deleted"])


def escaped(log, sha, now):
    """(rewrites, open) for the change merged as `sha` on that branch log: how many later
    commits rewrote a line it added (`rewrote`) inside `ANSWERS_FOR` of its merge, and whether
    that window is still open at `now`; None where the log does not hold the merge."""
    place = next((i for i, commit in enumerate(log) if commit["sha"] == sha), None)
    if place is None:
        return None
    merged = log[place]
    rewrites = sum(1 for later in log[place + 1:]
                   if later["at"] <= merged["at"] + ANSWERS_FOR and rewrote(later, merged["added"]))
    return rewrites, now < merged["at"] + ANSWERS_FOR


def split_hours(row):
    """A run's hours in each of `PARTS`, read from its phase rows so that no second is in two;
    zero for a run with no phase row, and None for one whose step columns count seconds its
    step rows do not hold: it began before the rows were kept.  Steps are compared alone: a
    step's column and row both read the wall clock, while a wait's column counts monotonic
    seconds that a clock correction sets apart from its row."""
    rows = [phase for phase in history.phases(row["run_id"]) if phase["ended_at"] is not None]
    kept = sum(phase["ended_at"] - phase["started_at"] for phase in rows
               if phase["phase"] in history.STEP_COLUMNS)
    if sum(row.get(column) or 0 for column in history.STEP_COLUMNS.values()) > kept + 1:
        return None
    edges = sorted({edge for row in rows for edge in (row["started_at"], row["ended_at"])})
    hours = {part: 0.0 for part, _ in PARTS}
    for start, end in zip(edges, edges[1:]):
        held = {row["phase"] for row in rows if row["started_at"] <= start and end <= row["ended_at"]}
        for part, names in PARTS:
            if held.intersection(names):
                hours[part] += (end - start) / 3600
                break
    return hours


def compute(now=None):
    """Two weeks of ended work, newest first, and the installed ak's committed size.

    Shares use all ended runs; merge time and token medians use merged runs only.
    Changed lines survive run cleanup as evidence of a merge; older, unsized merges
    need their run record. Missing token measurements never become free work. Waits share
    the run time of the ended runs that recorded them; a week of none is not recorded, and its
    landing checks' waits are not recorded while one of its rows was written without them. A run
    started again since its row ended (a resume, a delivery retry) counts waits for an attempt
    still going, so its waits wait until its row publishes the ending its record saved.
    """
    now = time.time() if now is None else now
    week = 7 * 86400

    def delivered(row):
        """Whether the run merged: its size survives run cleanup, an older merge needs its record."""
        return row.get("changed_lines") is not None or bool(
            (record.read_state(config.RUNS / row["run_id"]) or {}).get("merged"))

    def per_change(ended):
        """The median hours a change merged this week spent in model turns, in ak's own work,
        waiting, and with its seat between its runs (the wall time from its first run's start to
        its last run's end less its runs' time): every run of the change that ended in the two
        weeks, grouped by `change`, each second in one part (`split_hours`); time in no part,
        such as a park while its provider's window is spent, is in none, and a change with a run
        from before the phase rows were kept is not recorded (`split_hours`)."""
        by_change = {}
        for row in rows:
            if row.get("started_at") is not None and row["started_at"] <= row["finished_at"]:
                by_change.setdefault(row.get("change") or row["run_id"], []).append(row)
        merged = {row.get("change") or row["run_id"] for row in ended if delivered(row)}
        splits = []
        for key in merged:
            runs = by_change.get(key) or []
            parts = [split_hours(row) for row in runs]
            if not runs or None in parts:
                continue
            wall = (max(row["finished_at"] for row in runs) - min(row["started_at"] for row in runs)) / 3600
            going = sum((row["finished_at"] - row["started_at"]) / 3600 for row in runs)
            splits.append({**{part: sum(hours[part] for hours in parts) for part, _ in PARTS},
                           "seat": max(0.0, wall - going)})
        if not splits:
            return None
        return {part: median(split[part] for split in splits) for part in ("model", "ak", "waiting", "seat")}

    def settled(row):
        """Whether the run's record still ends where its row does, or is gone."""
        saved = record.read_state(config.RUNS / row["run_id"])
        return saved is None or (saved.get("state"), saved.get("finished_at")) == (
            row["final_state"], row["finished_at"])

    def git(*args):
        return _git(config.REPO, *args, ok=(0, 1) if args[0] == "grep" else (0,))

    logs = {}

    def checkout(row, saved):
        """Where that run's repository is checked out: as its record says, else by its row's
        name under `config.CODE`, else ak's own; None where nothing holds it."""
        if saved.get("repo") and Path(saved["repo"]).is_dir():
            return Path(saved["repo"])
        if row.get("repo") and (config.CODE / row["repo"]).is_dir():
            return config.CODE / row["repo"]
        return config.REPO if row.get("repo") in own_names else None

    def escapes(ended):
        """The merged changes of the week a later change rewrote inside `ANSWERS_FOR` of their
        merge (`escaped`), per reviewer, followed from each run's merge commit (its row's, else
        its record's) on its repository's branch log, read once per repository and far enough
        back to hold the window of a change merged two weeks ago: the one measure of what a
        review let through.  None with no merged run."""
        merged = [row for row in ended if delivered(row)]
        if not merged:
            return None
        found = {"merged": 0, "escaped": 0, "open": 0, "unknown": 0, "reviewers": {}}
        for row in merged:
            saved = record.read_state(config.RUNS / row["run_id"]) or {}
            sha, repo = row.get("merge_sha") or saved.get("merge_sha"), checkout(row, saved)
            if repo is not None and repo not in logs:
                logs[repo] = branch_log(repo, now - 2 * week - ANSWERS_FOR)
            answer = escaped(logs[repo], sha, now) if sha and repo is not None and logs[repo] else None
            if answer is None:
                found["unknown"] += 1
                continue
            rewrites, still = answer
            found["merged"] += 1
            found["open"] += still
            by = found["reviewers"].setdefault(row.get("reviewer") or "no reviewer", [0, 0])
            by[1] += 1
            if rewrites:
                found["escaped"] += 1
                by[0] += 1
        return found

    def who_built(ended):
        """The week's merged runs by who built the change: a seat, whose change comes as a
        pull request's review (`change` names the PR, its own or another's), or a worker, a
        task or fix run; each with the share of its merged runs that merged in round 1, None
        with none merged.  A run neither can be told of (`by_seat`) counts in neither.  None
        with no run ended."""
        if not ended:
            return None
        merged = [(by_seat(row), row) for row in ended if delivered(row)]
        stats = {}
        for kind, seat in (("seat", True), ("worker", False)):
            rounds = [row["rounds_used"] for by, row in merged if by is seat]
            stats[f"{kind}_merged"] = len(rounds)
            stats[f"{kind}_first_round"] = rounds.count(1) / len(rounds) if rounds else None
        return stats

    def by_seat(row):
        """Whether a seat built that run's change: its row names a pull request, or, on a row
        from before changes were recorded, its record does (`transitions.change_name`); None
        where neither is left to say."""
        change = row.get("change")
        if change is None:
            saved = record.read_state(config.RUNS / row["run_id"])
            if saved is None:
                return None
            change = transitions.change_name(saved)
        return bool(PULL_REQUEST.fullmatch(change or ""))

    def in_week(at, end):
        """Whether that moment falls in the week ending at `end`: the boundary between the two
        weeks is the last 7 days', as is `now`."""
        return end - week <= at and (at <= end if end == now else at < end)

    common = git("rev-parse", "--git-common-dir")
    own_names = {config.REPO.name}
    if common:
        own_names.add((config.REPO / os.fsdecode(common).strip()).resolve().parent.name)
    rows = [row for row in history.ended_runs(now - 2 * week, now)
            if row["final_state"] in ("pass", *record.FAILED, "exhausted", "not_needed")]

    held = history.parks(now - 2 * week, now)       # stopped rows: not among `rows`
    moments = history.owner(now - 2 * week, now)
    intents = history.intents_done(now - 2 * week, now)
    board, waits, merged_changes, escapes_seen = {"products": [], "ak": []}, [], [], []
    built, parks, sunk, owner, intent = [], [], [], [], []
    for end in (now, now - week):
        finished = [row for row in rows if in_week(row["finished_at"], end)]
        # A run found not needed waited and ran like any other, but delivered nothing to score.
        ended = [row for row in finished if row["final_state"] != "not_needed"]
        total_tokens = sum((row.get(role + "_tokens") or 0)
                           for row in ended for role in ("executor", "reviewer"))
        recorded = [row for row in finished
                    if row.get("slot_wait_seconds") is not None and row.get("total_seconds")
                    and settled(row)]
        run_time = sum(row["total_seconds"] for row in recorded)
        checks = [row.get("lander_wait_seconds") for row in recorded]
        waits.append({"compute": sum(row["slot_wait_seconds"] + row["suite_wait_seconds"]
                                     for row in recorded) / run_time,
                      "merge_hours": sum(row["merge_wait_seconds"] for row in recorded) / 3600,
                      "lander_hours": None if None in checks else sum(checks) / 3600}
                     if run_time else None)
        merged_changes.append(per_change(ended))
        escapes_seen.append(escapes(ended))
        built.append(who_built(ended))
        parks.append(None if held is None else {"parked": sum(in_week(at, end) for at in held)})
        # the week's tokens that bought no merge: every ended run that delivered nothing
        wasted = sum((row.get(role + "_tokens") or 0) for row in ended if not delivered(row)
                     for role in ("executor", "reviewer"))
        sunk.append({"share": wasted / total_tokens, "tokens": wasted} if total_tokens else None)
        # the owner's time: what the seats asked them, what reached them, how long they were waited on
        kinds = [(kind, waited) for at, kind, waited in moments or () if in_week(at, end)]
        answers = [waited / 3600 for kind, waited in kinds if kind == "answered"]
        owner.append(None if moments is None else {
            "asked": sum(kind == "asked" for kind, _ in kinds),
            "paged": sum(kind == "paged" for kind, _ in kinds),
            "hours": median(answers) if answers else None})
        # the time the owner feels: from their first message of an intent to its done, and to live
        if intents is None:
            intent.append(None)
        else:
            done = [each for each in intents if in_week(each["done_at"], end)]
            to_done = [(each["done_at"] - each["began_at"]) / 3600 for each in done]
            to_live = [(each["live_at"] - each["began_at"]) / 3600 for each in done
                       if each["live_at"] is not None]
            intent.append({"done": len(done), "hours": median(to_done) if to_done else None,
                           "live_hours": median(to_live) if to_live else None})
        for label in board:
            group = [row for row in ended if (row["repo"] in own_names) == (label == "ak")]
            if not group:
                board[label].append(None)
                continue
            merged = [row for row in group if delivered(row)]
            hours = [(row["finished_at"] - row["started_at"]) / 3600 for row in merged
                     if row.get("started_at") is not None and row["started_at"] <= row["finished_at"]]
            tokens = [row["executor_tokens"] + row["reviewer_tokens"] for row in merged
                      if row.get("executor_tokens") is not None and row.get("reviewer_tokens") is not None]
            stats = {"runs": len(group), "merged": len(merged),
                     "first_round": sum(row["rounds_used"] == 1 for row in merged) / len(group),
                     "unmerged": sum(row["final_state"] in (*record.FAILED, "exhausted")
                                     for row in group if row not in merged) / len(group),
                     "hours": median(hours) if hours else None,
                     "tokens": median(tokens) if tokens else None}
            if label == "ak":
                spent = sum((row.get(role + "_tokens") or 0)
                            for row in group for role in ("executor", "reviewer"))
                stats["token_share"] = spent / total_tokens if total_tokens else None
            board[label].append(stats)

    def size(ref):
        if not ref:
            return None
        code = git("grep", "-I", "-h", "--no-color", "-e", "^", ref, "--",
                   "agentkit/", "bin/", "hooks/", "adapters/", "tools/", "install.sh")
        readme, agents = (git("show", f"{ref}:{name}") for name in ("README.md", "AGENTS.md"))
        if code is None and readme is None and agents is None:
            return None

        def words(text):
            return len(text.decode("utf-8", "replace").split()) if text is not None else None
        return {"code_lines": code.count(b"\n") if code is not None else None,
                "readme_words": words(readme), "agents_words": words(agents)}

    before = git("rev-list", "--first-parent", "-1",
                 "--before=" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - week)), "HEAD")
    board["intent"] = intent
    board["owner"] = owner
    board["built"] = built
    board["waits"] = waits
    board["merged"] = merged_changes
    board["parks"] = parks
    board["sunk"] = sunk
    board["escaped"] = escapes_seen
    board["size"] = [size("HEAD"), size(before.decode().strip() if before else None)]
    return board


def render(board=None):
    """The two weeks beside each other without losing words on a phone; `board` is the one
    computed here unless the caller holds one (the weekly audit's report)."""
    board = compute() if board is None else board

    def week(stats, own):
        if stats is None:
            return "no runs ended"
        text = (f"{stats['runs']} runs ended; {stats['first_round']:.0%} merged in round 1; "
                f"{stats['unmerged']:.0%} ended without merging; ")
        if not stats["merged"]:
            text += "no merged runs"
        elif stats["hours"] is None:
            text += "merge hours unknown; "
        else:
            text += f"median {stats['hours']:g} hours to merge; "
        if stats["merged"] and stats["tokens"] is None:
            text += "median tokens per merged run unknown"
        elif stats["merged"]:
            tokens = f"{stats['tokens']:,}".removesuffix(".0")
            text += f"median {tokens} tokens per merged run"
        if own:
            share = stats["token_share"]
            text += f"; {share:.0%} of all recorded tokens" if share is not None else "; no tokens recorded"
        return text

    def waited(stats):
        if stats is None:
            return "not recorded"
        checks = ("checks' waits for a suite turn are not recorded" if stats["lander_hours"] is None
                  else f"checks waited {stats['lander_hours']:.1f} hours for a suite turn")
        return (f"{stats['compute']:.0%} of run time waiting for a slot or its own suite turn; "
                f"{stats['merge_hours']:.1f} hours in a landing line, where {checks}")

    def split(stats):
        if stats is None:
            return "no merged change"
        return (f"median hours per merged change: {stats['model']:.1f} in model turns, "
                f"{stats['ak']:.1f} ak's own work, {stats['waiting']:.1f} waiting, "
                f"{stats['seat']:.1f} with its seat between runs")

    def escapes(stats):
        if stats is None:
            return "no merged change"
        text = (f"{stats['escaped']} of {stats['merged']} merged changes had a line rewritten "
                "within 7 days")
        if stats["reviewers"]:
            text += " (" + ", ".join(f"{name} {gone} of {count}" for name, (gone, count)
                                     in sorted(stats["reviewers"].items())) + ")"
        if stats["open"]:
            text += f"; {stats['open']} merged under 7 days ago may still be"
        if stats["unknown"]:
            text += f"; {stats['unknown']} with no merge commit to follow"
        return text

    def size(stats):
        if stats is None:
            return "size unavailable"
        code = stats["code_lines"]
        return ", ".join(f"{value} {name}" if value is not None else f"{name} unknown"
                         for value, name in ((code, "code lines"),
                                             (stats["readme_words"], "README words"),
                                             (stats["agents_words"], "AGENTS.md words")))

    def built(stats):
        if stats is None:
            return "no runs ended"

        def share(kind):
            first = stats[f"{kind}_first_round"]
            return (f"{stats[f'{kind}_merged']} merged"
                    + (f", {first:.0%} in round 1" if first is not None else ""))

        return (f"by seats, through their PRs' reviews: {share('seat')}; by workers, task and "
                f"fix runs: {share('worker')}")

    def parked(stats):
        if stats is None:
            return "not recorded"
        return f"{stats['parked']} runs stopped by the park to wait on an older change's lines"

    def sunk(stats):
        if stats is None:
            return "no tokens recorded"
        return (f"{stats['share']:.0%} of the week's tokens, {stats['tokens']:,}, went to runs "
                "that never merged")

    def owner(stats):
        if stats is None:
            return "not recorded"
        text = f"{stats['asked']} questions asked, {stats['paged']} cards sent"
        if stats["hours"] is not None:
            text += f", median {stats['hours']:.1f} hours waiting for an answer"
        return text

    def intent(stats):
        if stats is None:
            return "not recorded"
        if not stats["done"]:
            return "no intent done"
        text = f"{stats['done']} intents done; median {stats['hours']:.1f} hours from the first message to done"
        if stats["live_hours"] is not None:
            text += f", {stats['live_hours']:.1f} to live"
        return text

    words = {"products": lambda stats: week(stats, False), "ak": lambda stats: week(stats, True),
             "intent": intent, "owner": owner, "built": built, "waits": waited, "merged": split,
             "parks": parked, "sunk": sunk, "escaped": escapes, "size": size}
    rows = [("", "last 7 days", "7 days before"),
            *((label, *(words[key](stats) for stats in board[key])) for key, label, _ in MEASURES)]
    room = max(1, (terminal.content_width() - 12) // 2)
    lines = terminal.wrap("Scoreboard (reported tokens; size now and 7 days ago)", terminal.content_width())
    for label, current, previous in rows:
        left, right = terminal.wrap(current, room), terminal.wrap(previous, room)
        for i in range(max(len(left), len(right))):
            lines.append(terminal.table_row(
                [label if i == 0 else "", left[i] if i < len(left) else "",
                 right[i] if i < len(right) else ""], [8, room, room]))
    return lines
