"""Compute and render the history scoreboard of delivered work and ak's cost."""

import os
import subprocess
import time
from statistics import median

from . import config, history, record, terminal

# The parts of a merged change's hours, each second of its runs' phase rows in the first that
# holds it: a model turn, else ak's own work (a check, or a merge step, which runs from the run's
# place in its landing line), else a wait.
PARTS = (("model", ("executor", "reviewer")), ("ak", ("done-when", "merge")),
         ("waiting", tuple(f"{wait} wait" for wait in history.WAIT_COLUMNS)))


def split_hours(run_id):
    """A run's hours in each of `PARTS`, read from its phase rows so that no second is in two;
    None for a run with none, one from before they were kept."""
    rows = [row for row in history.phases(run_id) if row["ended_at"] is not None]
    if not rows:
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
        such as a park on a spent quota window, is in none, and a change with a run from before
        the phase rows were kept is not recorded."""
        by_change = {}
        for row in rows:
            if row.get("started_at") is not None and row["started_at"] <= row["finished_at"]:
                by_change.setdefault(row.get("change") or row["run_id"], []).append(row)
        merged = {row.get("change") or row["run_id"] for row in ended if delivered(row)}
        splits = []
        for key in merged:
            runs = by_change.get(key) or []
            parts = [split_hours(row["run_id"]) for row in runs]
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
        try:
            result = subprocess.run(["git", "-C", str(config.REPO), *args],
                                    capture_output=True, timeout=10)
            if result.returncode == 0 or (args[0] == "grep" and result.returncode == 1):
                return result.stdout
        except (OSError, subprocess.SubprocessError):
            pass
        return None

    common = git("rev-parse", "--git-common-dir")
    own_names = {config.REPO.name}
    if common:
        own_names.add((config.REPO / os.fsdecode(common).strip()).resolve().parent.name)
    rows = [row for row in history.ended_runs(now - 2 * week, now)
            if row["final_state"] in ("pass", *record.FAILED, "exhausted", "not_needed")]

    board, waits, merged_changes = {"products": [], "ak": []}, [], []
    for end in (now, now - week):
        finished = [row for row in rows if end - week <= row["finished_at"] and
                    (row["finished_at"] <= end if end == now else row["finished_at"] < end)]
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
        readme = git("show", f"{ref}:README.md")
        if code is None and readme is None:
            return None
        return {"code_lines": code.count(b"\n") if code is not None else None,
                "readme_words": len(readme.decode("utf-8", "replace").split()) if readme is not None else None}

    before = git("rev-list", "--first-parent", "-1",
                 "--before=" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - week)), "HEAD")
    board["waits"] = waits
    board["merged"] = merged_changes
    board["size"] = [size("HEAD"), size(before.decode().strip() if before else None)]
    return board


def render():
    """The two weeks beside each other without losing words on a phone."""
    board = compute()

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

    def size(stats):
        if stats is None:
            return "size unavailable"
        code = stats["code_lines"]
        words = stats["readme_words"]
        return (f"{code} code lines" if code is not None else "code lines unknown") + ", " + (
            f"{words} README words" if words is not None else "README words unknown")

    rows = [("", "last 7 days", "7 days before"),
            ("products", *(week(stats, False) for stats in board["products"])),
            ("ak", *(week(stats, True) for stats in board["ak"])),
            ("waits", *(waited(stats) for stats in board["waits"])),
            ("merged", *(split(stats) for stats in board["merged"])),
            ("ak size", *(size(stats) for stats in board["size"]))]
    room = max(1, (terminal.content_width() - 12) // 2)
    lines = terminal.wrap("Scoreboard (reported tokens; size now and 7 days ago)", terminal.content_width())
    for label, current, previous in rows:
        left, right = terminal.wrap(current, room), terminal.wrap(previous, room)
        for i in range(max(len(left), len(right))):
            lines.append(terminal.table_row(
                [label if i == 0 else "", left[i] if i < len(left) else "",
                 right[i] if i < len(right) else ""], [8, room, room]))
    return lines
