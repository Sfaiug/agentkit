"""Compute and render the history scoreboard of delivered work, what broke after its reviews,
and ak's cost."""

import os
import re
import subprocess
import time
from statistics import median

from . import config, history, record, seat_tokens, terminal, transitions

# The parts of a merged change's hours, each second of its runs' phase rows in the first that
# holds it: a model turn, else ak's own work (a check, or a merge step, which runs from the run's
# place in its landing line), else a wait.
PARTS = (("model", ("executor", "reviewer")), ("ak", ("done-when", "merge")),
         ("waiting", tuple(f"{wait} wait" for wait in history.WAITS)))

# What the board measures, row by row: the board's key, the row's label, and the parts each
# week's cell is built from, in the vision's order (quality and speed, then cost, then size).
# tests/test_scoreboard_measures.py pins it, so a board that measures something else is a visible
# test change, never a quiet one.
MEASURES = (
    ("products", "products", ("runs", "merged", "first_round", "unmerged", "hours", "tokens")),
    ("ak", "ak", ("runs", "merged", "first_round", "unmerged", "hours", "tokens", "token_share")),
    ("tokens", "tokens", ("total_tokens", "seat_tokens", "not_counted")),
    ("intent", "intent", ("measured", "hours", "live", "live_hours", "answer_share")),
    ("owner", "owner", ("asked", "paged", "hours")),
    ("built", "built", ("seat_merged", "seat_first_round", "worker_merged", "worker_first_round")),
    ("waits", "waits", ("compute", "merge_hours", "lander_hours")),
    ("merged", "merged", ("model", "ak", "waiting", "seat")),
    ("checks", "checks", ("suites", "hours")),
    ("parks", "parks", ("parked",)),
    ("conflicts", "conflicts", ("share", "files")),
    ("sunk", "sunk", ("share", "tokens")),
    ("broke", "broke", ("merged", "after_merge", "landing", "flakes", "unknown")),
    ("pairs", "review pairs", ("self", "self_landing", "same_provider", "same_provider_landing", "other_landing")),
    ("findings", "findings", ("blocking", "disputed", "conceded", "raised_again", "let_go", "let_go_broke")),
    ("size", "ak size", ("code_lines", "readme_words", "agents_words")),
)

PULL_REQUEST = re.compile(r".+#\d+")   # a change named by its pull request: `owner/repo#N`

# The measures a week's loss is read from, in the vision's order -- quality, speed, cost,
# size: the words for it, the board's row, the part of that row's week (a share where two
# parts make one), whether more is worse, and how it prints (`said`).  The weekly audit's.
LOSSES = (
    ("merged changes that broke main or live after merge", "broke", ("after_merge", "merged"), True, "%"),
    ("merged changes whose tests went red at landing", "broke", ("landing", "merged"), True, "%"),
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

    def changes(ended):
        """Every run ended in the two weeks of each change merged this week, grouped by change."""
        by_change = {}
        for row in rows:
            if row.get("started_at") is not None and row["started_at"] <= row["finished_at"]:
                by_change.setdefault(row.get("change") or row["run_id"], []).append(row)
        merged = {row.get("change") or row["run_id"] for row in ended if history.merged(row)}
        return [by_change.get(key) or [] for key in merged]

    def per_change(changes):
        """The median hours a merged change spent in model turns, in ak's own work, waiting,
        and with its seat between runs (its first start to last end less its runs' time), each
        second in one part (`split_hours`); time in no part, such as a park, is in none, and a
        change from before the phase rows were kept is not recorded (`split_hours`)."""
        splits = []
        for runs in changes:
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

    def checked(changes):
        """Suite runs and summed check hours per merged change; no rows means not recorded."""
        run_ids = {row["run_id"] for runs in changes for row in runs}
        pieces = [row for row in check_rows if row["run_id"] in run_ids]
        if not pieces:
            return None
        suites = {(row["run_id"], row["round"], row["kind"], row["tree"]) for row in pieces
                  if row["command"].startswith("AK_SHARD=")}
        seconds = sum(row["finished_at"] - row["started_at"] for row in pieces
                      if row["finished_at"] is not None and row["started_at"] is not None)
        return {"suites": len(suites) / len(changes), "hours": seconds / 3600 / len(changes)}

    def settled(row):
        """Whether the run's record still ends where its row does, or is gone."""
        saved = record.read_state(config.RUNS / row["run_id"])
        return saved is None or (saved.get("state"), saved.get("finished_at")) == (
            row["final_state"], row["finished_at"])

    def collided(ended, end):
        """Merged changes that ever conflicted, and files by their conflicts' own dates."""
        merged = {(row["repo"], row.get("change") or row["run_id"]) for row in ended
                  if row.get("changed_lines") is not None}
        seen = {(row["repo"], row["change"]) for row in conflict_rows
                if row["at"] <= end and (end == now or row["at"] < end)}
        counts = {}
        for row in conflict_rows:
            if in_week(row["at"], end):
                key = row["repo"], row["path"]
                count, added = counts.get(key, (0, True))
                counts[key] = count + 1, added and row["added_only"] == 1
        files = sorted(((*key, count, added) for key, (count, added) in counts.items() if count >= 2),
                       key=lambda file: (-file[2], file[0], file[1]))[:3]
        return {"share": len(merged & seen) / len(merged) if merged else None,
                "files": files} if merged or counts else None

    def git(*args):
        return _git(config.REPO, *args, ok=(0, 1) if args[0] == "grep" else (0,))

    def breaks(ended):
        """The merged changes of the week that broke after review passed them: their tests red
        at landing, or main's checks or live health after their merge, as each run's row records
        it (`transitions.history_ending`, `watch.broke_after_merge`); a row from before breaks
        were recorded is unknown until one is recorded on it.  A rewrite later is no break: it
        may be the next feature.  None with no merged run."""
        merged = [row for row in ended if history.merged(row)]
        if not merged:
            return None
        known = [row for row in merged
                 if row.get("landing_breaks") is not None or row.get("broke_after_merge") is not None]
        return {"merged": len(known),
                "after_merge": sum(1 for row in known if row.get("broke_after_merge")),
                "landing": sum(1 for row in known if row["landing_breaks"]),
                "flakes": sum(1 for row in known if row.get("landing_flakes")),
                "unknown": len(merged) - len(known)}

    def pairs(ended):
        """The week's merged changes by their recorded pair; unknown pairs count in none,
        and unknown landing results count in no landing share."""
        merged = {row.get("change") or row["run_id"]: row
                  for row in sorted(ended, key=lambda row: row["finished_at"]) if history.merged(row)}
        merged = [row for row in merged.values() if row.get("review_pair") is not None]
        if not merged:
            return None
        stats = {}
        for key, pair in (("self", "self"), ("same_provider", "same provider"), ("other", "other provider")):
            group = [row for row in merged if row["review_pair"] == pair]
            if key != "other":
                stats[key] = len(group) / len(merged)
            landings = [row["landing_breaks"] for row in group if row.get("landing_breaks") is not None]
            stats[key + "_landing"] = sum(bool(n) for n in landings) / len(landings) if landings else None
        return stats

    def who_built(ended):
        """The week's merged runs by who built the change: a seat, whose change comes as a
        pull request's review (`change` names the PR, its own or another's), or a worker, a
        task or fix run; each with the share of its merged runs that merged in round 1, None
        with none merged.  A run neither can be told of (`by_seat`) counts in neither.  None
        with no run ended."""
        if not ended:
            return None
        merged = [(by_seat(row), row) for row in ended if history.merged(row)]
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
    check_rows = history.checks(now - 2 * week, now)
    finding_rows = history.findings(now - 2 * week, now)
    conflict_rows = history.conflict_rows(now - 2 * week, now)

    held = history.parks(now - 2 * week, now)       # stopped rows: not among `rows`
    moments = history.owner(now - 2 * week, now)
    dones = history.dones(now - 2 * week, now)
    seats, not_counted = seat_tokens.read(now - 2 * week, now)
    board, waits, merged_changes, broken = {"products": [], "ak": [], "tokens": []}, [], [], []
    built, parks, sunk, owner, intent, check_costs = [], [], [], [], [], []
    review_pairs, finding_counts = [], []
    conflicts = []
    for end in (now, now - week):
        finished = [row for row in rows if in_week(row["finished_at"], end)]
        # A run found not needed waited and ran like any other, but delivered nothing to score.
        ended = [row for row in finished if row["final_state"] != "not_needed"]
        total_tokens = sum((row.get(role + "_tokens") or 0)
                           for row in ended for role in ("executor", "reviewer"))
        seat_spent = [(repo, tokens) for repo, at, tokens in seats if in_week(at, end)]
        own_spent = sum(tokens for repo, tokens in seat_spent if repo in own_names)
        seat_total = sum(tokens for _, tokens in seat_spent)
        total_tokens += seat_total
        board["tokens"].append({"total_tokens": total_tokens, "seat_tokens": seat_total,
                                "not_counted": not_counted} if total_tokens or not_counted else None)
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
        grouped = changes(ended)
        merged_changes.append(per_change(grouped))
        check_costs.append(checked(grouped))
        broken.append(breaks(ended))
        review_pairs.append(pairs(ended))
        weighed = [row for row in finding_rows if in_week(row["at"], end)]
        blocking = [row for row in weighed if row["kind"] == "finding"]
        merged = [row for row in ended if history.merged(row)]
        changes_merged = {(row["repo"], row.get("change") or row["run_id"]) for row in merged}
        changes_broke = {(row["repo"], row.get("change") or row["run_id"]) for row in merged
                         if row.get("broke_after_merge")}
        # A finding follows its change's merge week; a later break can grow that week's cell.
        let_go = [row for row in finding_rows
                  if (row["kind"] == "follow-up" or row["outcome"] in ("dropped", "conceded"))
                  and (row["repo"], row.get("change") or row["run_id"]) in changes_merged]
        finding_counts.append({
            "blocking": len(blocking),
            "disputed": sum(row["outcome"] is not None for row in weighed),
            "conceded": sum(row["outcome"] in ("dropped", "conceded") for row in weighed),
            "raised_again": sum(row["raised_again"] for row in blocking),
            "let_go": len(let_go),
            "let_go_broke": sum((row["repo"], row.get("change") or row["run_id"]) in changes_broke
                                for row in let_go)} if weighed or let_go else None)
        built.append(who_built(ended))
        parks.append(None if held is None else {"parked": sum(in_week(at, end) for at in held)})
        conflicts.append(collided(ended, end))
        # the week's tokens that bought no merge: every ended run that delivered nothing
        wasted = sum((row.get(role + "_tokens") or 0) for row in ended if not history.merged(row)
                     for role in ("executor", "reviewer"))
        sunk.append({"share": wasted / total_tokens, "tokens": wasted} if total_tokens else None)
        # the owner's time: what the seats asked them, what reached them, how long they were waited on
        kinds = [(kind, waited) for at, kind, waited in moments or () if in_week(at, end)]
        answers = [waited / 3600 for kind, waited in kinds if kind == "answered"]
        owner.append(None if moments is None else {
            "asked": sum(kind == "asked" for kind, _ in kinds),
            "paged": sum(kind == "paged" for kind, _ in kinds),
            "hours": median(answers) if answers else None})
        # the time the owner feels: from their first message of an intent to the done that ends
        # it, and to the last of its changes live
        known = [(at, began, live, answered) for at, began, live, answered in dones or ()
                 if began is not None and in_week(at, end)]
        took = [(at - began) / 3600 for at, began, _, _ in known]
        lived = [(live - began) / 3600 for _, began, live, _ in known if live is not None]
        answers = [answered for _, _, _, answered in known]
        intent.append(None if dones is None else {
            "measured": len(took), "hours": median(took) if took else None,
            "live": len(lived), "live_hours": median(lived) if lived else None,
            "answer_share": sum(answers) / (sum(took) * 3600) if sum(took) and None not in answers else None})
        for label in ("products", "ak"):
            group = [row for row in ended if (row["repo"] in own_names) == (label == "ak")]
            if not group and not (label == "ak" and own_spent):
                board[label].append(None)
                continue
            merged = [row for row in group if history.merged(row)]
            hours = [(row["finished_at"] - row["started_at"]) / 3600 for row in merged
                     if row.get("started_at") is not None and row["started_at"] <= row["finished_at"]]
            tokens = [row["executor_tokens"] + row["reviewer_tokens"] for row in merged
                      if row.get("executor_tokens") is not None and row.get("reviewer_tokens") is not None]
            stats = {"runs": len(group), "merged": len(merged),
                     "first_round": sum(row["rounds_used"] == 1 for row in merged) / len(group) if group else None,
                     "unmerged": sum(row["final_state"] in (*record.FAILED, "exhausted")
                                     for row in group if row not in merged) / len(group) if group else None,
                     "hours": median(hours) if hours else None,
                     "tokens": median(tokens) if tokens else None}
            if label == "ak":
                spent = sum((row.get(role + "_tokens") or 0)
                            for row in group for role in ("executor", "reviewer"))
                stats["token_share"] = (spent + own_spent) / total_tokens if total_tokens else None
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
    board["checks"] = check_costs
    board["parks"] = parks
    board["conflicts"] = conflicts
    board["sunk"] = sunk
    board["broke"] = broken
    board["pairs"] = review_pairs
    board["findings"] = finding_counts
    board["size"] = [size("HEAD"), size(before.decode().strip() if before else None)]
    return board


def render(board=None):
    """The two weeks beside each other without losing words on a phone; `board` is the one
    computed here unless the caller holds one (the weekly audit's report)."""
    board = compute() if board is None else board

    def week(stats, own):
        if stats is None:
            return "no runs ended"
        if not stats["runs"]:
            return f"no runs ended; {stats['token_share']:.0%} of all recorded tokens"
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

    def checks(stats):
        if stats is None:
            return "not recorded"
        return (f"{stats['suites']:.2f} suite runs and {stats['hours']:.2f} check hours "
                "per merged change")

    def broke(stats):
        if stats is None:
            return "no merged change"
        text = (f"{stats['after_merge']} of {stats['merged']} merged changes broke main or live "
                f"after merge; {stats['landing']} went red at landing; {stats['flakes']} more were flakes")
        if stats["unknown"]:
            text += f"; {stats['unknown']} merged before breaks were recorded"
        return text

    def pairs(stats):
        if stats is None:
            return "not recorded"

        def landing(key):
            value = stats[key + "_landing"]
            return "landing not recorded" if value is None else f"{value:.0%} went red at landing"

        return (f"{stats['self']:.0%} self-reviewed ({landing('self')}); "
                f"{stats['same_provider']:.0%} reviewed by another model of the same provider "
                f"({landing('same_provider')}); another provider: {landing('other')}")

    def findings(stats):
        if stats is None:
            return "not recorded"
        return (f"{stats['blocking']} blocking; {stats['disputed']} disputed; "
                f"{stats['conceded']} of {stats['disputed']} conceded; "
                f"{stats['raised_again']} of {stats['blocking']} raised again; "
                f"{stats['let_go']} let go; {stats['let_go_broke']} of {stats['let_go']} "
                "on a change that broke main or live after merge")

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

    def conflicts(stats):
        if stats is None:
            return "no merged change"
        text = ("no merged change" if stats["share"] is None
                else f"{stats['share']:.0%} of merged changes met a conflict")

        def added_only(repo, path):
            # .gitattributes reads these as a glob, quote, escape, comment or the path's end
            if re.search(r'[\s*?\[\]!#"\\]', path):
                return " (added lines only)"
            return f" (added lines only: `{path} merge=union` in {repo}'s .gitattributes takes both sides)"

        return text + "".join(f"; {repo}/{path}: {count} conflicts" + (added_only(repo, path) if added else "")
                              for repo, path, count, added in stats["files"])

    def intent(stats):
        if stats is None:
            return "not recorded"
        if not stats["measured"]:
            return "no intent measured"
        text = (f"{stats['measured']} intents measured, median {stats['hours']:.1f} hours from the "
                "owner's first message to done")
        if stats["live"]:
            text += f"; {stats['live']} live, median {stats['live_hours']:.1f} hours to live"
        if stats["answer_share"] is not None:
            text += f"; {stats['answer_share']:.1%} of intent time waiting for the owner's answers"
        return text

    def owner(stats):
        if stats is None:
            return "not recorded"
        text = f"{stats['asked']} questions asked, {stats['paged']} cards sent"
        if stats["hours"] is not None:
            text += f", median {stats['hours']:.1f} hours waiting for an answer"
        return text

    def tokens(stats):
        if stats is None:
            return "no tokens recorded"
        text = (f"{stats['total_tokens']:,} tokens; {stats['seat_tokens']:,} from seats"
                if stats["total_tokens"] else "no tokens recorded")
        if stats["not_counted"]:
            text += "; not counted: " + ", ".join(stats["not_counted"])
        return text

    words = {"products": lambda stats: week(stats, False), "ak": lambda stats: week(stats, True), "tokens": tokens,
             "intent": intent, "owner": owner, "built": built, "waits": waited, "merged": split, "parks": parked,
             "checks": checks, "conflicts": conflicts, "sunk": sunk, "broke": broke, "pairs": pairs,
             "findings": findings, "size": size}
    rows = [("", "last 7 days", "7 days before"),
            *((label, *(words[key](stats) for stats in board[key])) for key, label, _ in MEASURES)]
    label_width = max(len(label) for _, label, _ in MEASURES)
    room = max(1, (terminal.content_width() - label_width - 4) // 2)
    lines = terminal.wrap("Scoreboard (reported tokens; size now and 7 days ago)", terminal.content_width())
    for label, current, previous in rows:
        left, right = terminal.wrap(current, room), terminal.wrap(previous, room)
        for i in range(max(len(left), len(right))):
            lines.append(terminal.table_row(
                [label if i == 0 else "", left[i] if i < len(left) else "",
                 right[i] if i < len(right) else ""], [label_width, room, room]))
    return lines
