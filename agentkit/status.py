"""`ak run status`: the run table, one run's details, and the words they use."""

import json
import re
import time
from pathlib import Path

from . import config, gate, gc, history, host, orch, run, scoreboard
from . import job as jobs
from . import land as landing
from . import record as run_record
from . import task as taskfile


def parked_line(state, run_id=None, now=None):
    """The dim line under a parked run's status row: its state as such, and when.

    An error with a scheduled retry names its hour (`error · retry 14:32`, or
    `retry due` once the hour has passed and the tick just has not fired yet); a
    `waiting` run names its place in the landing line or the merge it waits for;
    an `exhausted` run off a dead reviewer names the reviewer it waits for.
    A quota run already says its
    window on the waiting line, and a stalled one its stall lines, so neither
    says anything here. An admitted ending also names the conditions that let
    the tick take it up. Anything parked with no scheduled resume says who it
    waits for instead: `run <id> parked: <reason>`.
    """
    now = time.time() if now is None else now
    name = run_id or state.get("run_id") or "?"
    line = run.landing_line(state)
    if line:
        ahead = [directory.name for directory, _ in landing.line(config.RUNS / line)]
        place = ahead.index(name) + 1 if name in ahead else len(ahead) + 1
        suffix = ("th" if 10 <= place % 100 <= 20 else
                  {1: "st", 2: "nd", 3: "rd"}.get(place % 10, "th"))
        target = (state.get("target") or state.get("base") or "main").removeprefix("origin/")
        return f"waiting · {place}{suffix} in line to land on {target}"
    word = state.get("state")
    admission = run.tick_admission(state, now=now) if word in ("error", "waiting") else ""
    admitted = f" · {admission}" if admission else ""
    if word in ("error", "waiting") and not admission:
        return f"run {name} parked: {run.handback_reason(state)}"
    if word == "error":
        at = state.get("error_retry_at")
        if isinstance(at, (int, float)) and not isinstance(at, bool):
            if at <= now:
                return "error · retry due" + admitted
            try:
                return f"error · retry {time.strftime('%H:%M', time.localtime(at))}" + admitted
            except (OverflowError, OSError, ValueError):
                return "error · retry due" + admitted
        return f"run {name} parked: {run.handback_reason(state)}"
    if word == "waiting":
        ref = (state.get("waiting_on") or {}).get("ref") or run.conflict_upstream(state)
        return f"waiting · retry after the next merge to {ref}" + admitted
    if word == "exhausted" and run.exhausted_wait(state) == "reviewer":
        return "exhausted · resumes when a reviewer is eligible"
    return ""


def executor_line(state):
    """Who executed: `astra \u2192 opus (ran dry)` where the work changed hands mid-run.

    The arrow reads in the order the models held the work, and the reason in brackets is why
    the last one before the current model stopped -- never a guess, always what run.json says.
    The tick's entries name the move without the model half, so a link reads `from` where
    `model` is missing and the brackets read `reason` where `why` is.
    """
    name = str(state.get("executor", "?"))
    history = [entry for entry in state.get("executor_history") or [] if isinstance(entry, dict)]
    # a handover attempt that went nowhere (an older record, the tick's) is no link and no reason
    held = [e for e in history
            if e.get("from") is None or e.get("to") is None or e["from"] != e["to"]]
    if not held:
        return name
    chain = " \u2192 ".join([*(str(e.get("model") or e.get("from") or "?") for e in held), name])
    return f"{chain} ({held[-1].get('why') or held[-1].get('reason') or 'changed'})"


def blocked_note(state, word=None):
    """`! blocked \u00b7 <why>` for a run the orchestrator has to write a new task for, else "".

    The one dim line `ak run status` keeps under a blocked row: the glyph
    and the word for what it is, then why.  A blocked run is final -- `ak run resume` refuses
    it -- so the line says what happened and never offers a number to resume from.  `word`
    is the row's own, where the row's word is the listing's (`status_state_word`).
    """
    if state.get("state") != "blocked":
        return ""
    from . import menu, terminal
    why = " ".join((state.get("error") or "the task cannot be completed as written").split())
    return f"{terminal.state_glyph(word or menu.run_state_word(state))} blocked \u00b7 {why}"


def handback_waiting(state):
    """`hand-back waiting: <why>` for an ending held for a closed seat, else "".

    The one line `ak run status` keeps under a row whose seat the owner closed: the ending was
    never typed and the seat never reopened, so the wait has to be visible somewhere.  A seat
    mid-turn leaves the same flag without a reason, and shows no line: the tick types it at the
    next quiet prompt.
    """
    if not state.get("handback_pending"):
        return ""
    why = state.get("handback_wait_reason")
    if not why:
        return ""
    return f"hand-back waiting: {why}"


def run_scope_dir(scope):
    """This run's scope directory under the runs slice, or None where there is none.

    A scope the manager never made -- a plain start, or one already collected --
    has no directory, and says nothing: the marker scan below is the fallback.
    """
    if not isinstance(scope, str) or not scope or scope == "none" or scope.startswith("none ("):
        return None
    try:
        runs_dir = orch.slice_cgroup() / orch.run_slice_name()
    except (OSError, ValueError):
        return None
    for suffix in (".scope", ".service"):
        name = scope if scope.endswith(suffix) else f"{scope}{suffix}"
        candidate = runs_dir / name
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def scope_alive(state, scope_dir=None, _marker=None, _rss=None, _active=None):
    """(live processes, resident bytes) for an unfinished run, or None.

    The scope's cgroup answers first, where the run has one; without systemd
    the marker scan counts what still carries the run's name, plus the loop
    itself while it is still the run's own.  A finished run owns nothing and
    says nothing.  Anything unreadable fails open to no reading, the way every
    gate here does: no cgroup, no answer, no line.
    """
    if (state or {}).get("state") in run.ENDED:
        return None
    if scope_dir is None and (state or {}).get("scope"):
        scope_dir = run_scope_dir(state.get("scope"))
    if scope_dir is not None:
        readings = host._scope_readings(scope_dir)
        if readings is not None:
            return readings
    run_id = (state or {}).get("run_id")
    marker = _marker or run.marker_pids
    try:
        pids = list(marker(run_id)) if run_id else []
    except (OSError, ValueError, TypeError):
        return None
    active = _active or run_record.process_active
    try:
        loop_alive = bool(active(state))
    except (OSError, ValueError, TypeError, AttributeError):
        loop_alive = False
    pid = (state or {}).get("pid")
    if loop_alive and isinstance(pid, int) and pid > 0 and pid not in pids:
        pids.append(pid)
    rss = _rss or host.resident_bytes
    total = 0
    for member in pids:
        try:
            reading = rss(member)
        except (OSError, ValueError, TypeError):
            reading = None
        if reading is not None:
            total += reading
    if not pids:
        # Without /proc there is no scan to believe: a host that cannot answer
        # shows no line rather than a zero.
        try:
            if not Path("/proc").is_dir():
                return None
        except OSError:
            return None
    return len(pids), total


def format_alive_memory(mem_bytes):
    """Resident bytes the way the host line says gigabytes: `1.2 GB`, `50 MB`."""
    try:
        mb = float(mem_bytes) / (1024 * 1024)
    except (TypeError, ValueError):
        return "? MB"
    if mb >= 1024:
        return f"{host._g(mb)} GB"
    if mb >= 1:
        return f"{mb:.0f} MB"
    kb = mb * 1024
    return f"{kb:.0f} KB" if kb >= 1 else "0 KB"


def format_alive(count, mem_bytes):
    """`3 processes · 1.2 GB`: live processes and their resident memory, one line."""
    word = "processes" if count != 1 else "process"
    return f"{count} {word} · {format_alive_memory(mem_bytes)}"


def alive_line(state, scope_dir=None, _marker=None, _rss=None, _active=None):
    """`3 processes · 1.2 GB` under an unfinished run's row, else "".

    The one dim line that says what is still alive under the run: the scope's
    cgroup count and resident memory, or the marker scan's where there is no
    scope.  A finished run shows neither count nor memory.
    """
    readings = scope_alive(state, scope_dir, _marker, _rss, _active)
    if readings is None:
        return ""
    count, mem_bytes = readings
    return format_alive(count, mem_bytes)


def stop_note(state):
    """`stopped · <why>` for a run a cap or a kill ended, else "".

    The one dim line a stopped run keeps under its row: what ended it, in the
    run's own words.  A run the memory cap killed says its ceiling here too,
    so a `fail` on `killed: memory cap 4 GB` never reads as work that was judged.
    """
    if (state or {}).get("state") == "stopped":
        why = " ".join((state.get("error") or "stopped by the user").split())
        return f"stopped · {why}"
    err = " ".join(((state or {}).get("error") or "").split())
    lowered = err.lower()
    if "killed" in lowered or "memory cap" in lowered:
        return err
    return ""


def status_word(state, cfg=None):
    """What `ak run status` says became of a finished run's work.

    `delivery` already knows: this is that answer with the verdict taken off, because the
    status line carries the verdict in a column of its own.  So a run with no repository reads
    `delivered`, and `merged` and `not merged: <reason>` stay what they always were -- a
    repository run's answer, about a branch a run without one never had.  A merged run is
    `merged` whatever today's config makes of its review's providers: the merge happened.
    """
    if not state.get("finished_at"):
        return ""
    if state.get("merged"):
        return "merged"
    if state.get("pr"):
        return "PR open"
    word = run.delivery(state, run.report_config(cfg))
    return word[len("PASS, "):] if word.startswith("PASS, ") else ""


def step_word(state):
    """The step a live run is in and how long it has been there: `executor 41m`, `merge 1m`.

    Only a running run has one.  A finished run's step is over, and what became of its work is
    the column that says something.
    """
    if state.get("state") != "running" or not state.get("step"):
        return ""
    at = state.get("step_at")
    if type(at) not in (int, float):
        return str(state["step"])
    return f"{state['step']} {orch.span(time.time() - at)}"


def actionable(state):
    if state.get("recovery_acknowledged_at"):
        return False
    finished = state.get("finished_at") or state.get("started_at")
    recent_failure = (state.get("state") in ("fail", "error", "blocked") and
                      type(finished) in (int, float) and time.time() - gc.GC_AGE < finished <= time.time())
    pending_delivery = (state.get("state") == "pass" and state.get("repo")
                        and not state.get("merged") and not state.get("no_merge")
                        and not state.get("on_target")
                        and not state.get("review_pr") and not state.get("review_posted"))
    return bool(run.unfinished(state) or recent_failure or pending_delivery)


def status_key(pair):
    state = pair[1]
    return (state.get("state") in ("running", "queued"), bool(actionable(state)),
            state.get("interrupted_at") or state.get("finished_at") or state.get("started_at") or 0)


def result_paths(directory, state):
    return {"result": str(directory / "result.md"), "record": str(directory / "run.json"),
            "logs": str(directory), "workspace": state.get("worktree"),
            "workspace_present": bool(state.get("worktree") and Path(state["worktree"]).exists())}


def workspace_location(state, present):
    """`present`, or what a missing checkout still leaves behind.

    Every other cleanup keeps the local branch, so `removed; branch/PR retained`
    is the whole story -- except a stop without `--keep`, a merged run, and a
    branch a session stop took, which say `removed; branch removed` instead.
    """
    if present:
        return "present"
    if state.get("state") == "stopped" and not state.get("stop_kept"):
        return "removed; branch removed"
    if state.get("merged") or state.get("branch_removed"):
        return "removed; branch removed"
    return "removed; branch/PR retained"


def resume_age(state, now=None):
    """`resumed 13:05 · continued the executor's turn` for an hour after a resume, else "".

    The age column carries it, in the same cell the row's age usually occupies, and only
    while the resume is still the news. `turn restarted` is a session the harness could
    not continue, so the role went on in a fresh conversation.

    Only a model turn is a turn: a slot wait, the done-when gate and the merge are steps
    the loop continues itself, and the line names them as what they are.
    """
    note = state.get("resume_notice")
    if not isinstance(note, dict):
        return ""
    at = note.get("at")
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return ""
    now = time.time() if now is None else now
    if not 0 <= now - at <= run.RESUME_VISIBLE:
        return ""
    clock = time.strftime("%H:%M", time.localtime(at))
    if note.get("restarted"):
        return f"resumed {clock} · turn restarted"
    role = note.get("role") or "executor"
    what = f"the {role}'s turn" if role in run.TURN_ROLES else f"the {role}"
    return f"resumed {clock} · continued {what}"


def death_lines(state):
    """One line per recorded death, for `ak run status <id>`."""
    lines = []
    for death in state.get("deaths") or []:
        if not isinstance(death, dict):
            continue
        when = death.get("at")
        if isinstance(when, (int, float)) and not isinstance(when, bool):
            clock = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))
        else:
            clock = "?"
        reason = death.get("reason") or ""
        parked = " parked" if death.get("parked") else ""
        lines.append(f"  death {clock} pid {death.get('pid')}{parked}: {reason}")
    return lines


STATUS_HEADERS = ["id", "title", "state", "worker", "round", "age"]


def status_state_word(state, index=None):
    """`ak run status`'s word for a run: `menu.run_state_word`'s, except that a `needs you`
    ending already `settled` reads `done`.

    The record's own word stays the menu's.  This is the listing's, which knows what came
    after the run, so it tells the truth the seat's row tells: an ending handed back,
    acknowledged or superseded is nobody's question any more.
    """
    from . import menu
    word = menu.run_state_word(state)
    return "done" if word == "needs you" and run.settled(state, index) else word


def status_id_cell(name, room):
    """The id as its date and time, then the slug cut at a word.

    A run id is `YYYYMMDD-HHMM-slug`; the cell keeps the whole id where it
    fits and falls back to `YYYYMMDD HHMM <slug cut at a word>` where the
    screen cannot hold it.
    """
    from . import terminal
    if terminal.cells(name) <= room:
        return name
    match = re.match(r"^(\d{8})-(\d{4})-(.*)$", name, re.DOTALL)
    if not match:
        return terminal.cut(name, room)
    date, clock, slug = match.groups()
    head = f"{date} {clock} "
    if terminal.cells(head) >= room:
        return terminal.cut(name, room)
    room -= terminal.cells(head)
    if terminal.cells(slug) <= room:
        return head + slug
    # the slug's words are dash-separated: keep whole words, never mid-word;
    # the ellipsis takes the last cell, so the words keep all but one
    current = ""
    for word in slug.split("-"):
        added = word if not current else current + "-" + word
        if terminal.cells(added) > room - 1:
            break
        current = added
    if not current:
        return head + terminal.cut(slug, room)
    return head + current + "…"


def status_rows(found, width, index=None, cfg=None):
    """The status table's header and one line group per row.

    Fixed columns with two-space gutters, sized once from the rows on screen:
    id (its date and time, then the slug cut at a word), title (all the
    remaining width, wrapped once at a word onto an indented continuation, cut
    with ` \u2026` only past that), state, worker, round, age. The state reads the
    table's words from terminal.STATES: unfinished, working, done or failed.
    The worker pair carries `self-reviewed` where the executor's own model reviews.
    Returns (header, groups): the header drawn once, each group's lines for
    one row, so the caller can print a run's detail lines indented under it.
    `index` is the listing's `supersession_index`, for `status_state_word`.
    `cfg` tells an alias from another model for the mark; without it only the
    same name marks.
    """
    from . import menu, terminal
    if not found:
        widths = [terminal.cells(head) for head in STATUS_HEADERS]
        return terminal.table_row(STATUS_HEADERS, widths, "", ["dim"] * 6), []
    rows = []
    for directory, state in found:
        done = len(state.get("round_summaries") or [])
        total = state.get("rounds")
        going = state.get("state") in ("queued", "running")
        rnd = min(done + 1, total) if going and total else done
        if run.own_pr_wait_note(state) or state.get("own_pr_round_pending"):
            rnd = state.get("own_pr_round_pending") or done
        rounds = f"round {rnd}/{total or '?'}"
        if state.get("extended"):
            rounds += f" (+{state['extended']})"
        worker = f"{state.get('executor', '?')}/{state.get('reviewer', '?')}"
        if run.self_reviewed(state, cfg):
            worker += " self-reviewed"
        rows.append([directory.name, state.get("title") or directory.name,
                     status_state_word(state, index), worker, rounds,
                     resume_age(state) or terminal.format_age(menu.run_age_secs(state))])
    fixed = [2, 3, 4, 5]
    natural = [max([terminal.cells(row[i]) for row in rows] + [terminal.cells(STATUS_HEADERS[i])])
               for i in fixed]
    # natural is [state, worker, round, age]; the title takes what is left after
    # the id, which keeps whole ids where they fit and cuts the slug at a word
    # past that. The id is a machine token that --plain, --json and the detail
    # lines already carry whole, so the title keeps its floor first and the id
    # takes the rest: one long id never starves every title in the table.
    state_texts = [terminal.state_text(row[2]) for row in rows]
    natural[0] = max([terminal.cells(line) for line in state_texts] +
                     [terminal.cells(STATUS_HEADERS[2])])
    gutter = 2
    title_min = 20
    id_budget = max(15, width - sum(natural) - gutter * 5 - title_min)
    id_room = min(max([terminal.cells(row[0]) for row in rows]), id_budget)
    title_room = width - id_room - sum(natural) - gutter * 5
    narrow = title_room < 12
    first_room = max(1, width - id_room - gutter)
    widths = [id_room, max(1, title_room), natural[0], natural[1], natural[2], natural[3]]
    if narrow:
        header = terminal.table_row(STATUS_HEADERS[:2], [id_room, first_room], "",
                                    ["dim"] * 2)
    else:
        header = terminal.table_row(STATUS_HEADERS, widths, "", ["dim"] * 6)
    groups = []
    for row, line in zip(rows, state_texts):
        word = row[2]
        kind = terminal.state_colour(word)
        cell = status_id_cell(row[0], id_room)
        if not narrow:
            titled = terminal.title_lines(row[1], title_room)
            group = [terminal.table_row([cell, titled[0], line, row[3], row[4], row[5]],
                                        widths, "", [None, None, kind, None, None, None])]
            if len(titled) > 1:
                group.append(" " * (id_room + gutter) + titled[1])
        else:
            titled = terminal.title_lines(row[1], first_room)
            group = [terminal.table_row([cell, titled[0]], [id_room, first_room])]
            if len(titled) > 1:
                group.append(" " * (id_room + gutter) + titled[1])
            # the tail is measured plain and printed coloured: a cut never
            # touches a styled cell, and the state itself is never cut
            plain = [line, row[3], row[4], row[5]]
            if terminal.cells("  " + "  ".join(plain)) <= width:
                plain[0] = terminal.state_cell(word)
                group.append(("  " + "  ".join(plain)).rstrip())
            else:
                head, rest = plain[:2], plain[2:]
                head_line = "  " + "  ".join(head)
                if terminal.cells(head_line) > width:
                    over = terminal.cells(head_line) - width
                    head[1] = terminal.cut(head[1], max(1, terminal.cells(head[1]) - over))
                head[0] = terminal.state_cell(word)
                group.append(("  " + "  ".join(head)).rstrip())
                group.append(("  " + "  ".join(rest)).rstrip())
        groups.append(group)
    return header, groups


def status_final_check(directory, state):
    """The run's `final check:` line for `ak run status`, or None when unreadable."""
    try:
        _, body, _ = taskfile.parse_task(directory / "task.md")
        cmds = taskfile.done_when(body, directory / "task.md")
    except (OSError, config.Error):
        return None
    if state.get("scratch") or state.get("no_merge"):
        cmds = [taskfile.split_once(cmd)[0] for cmd in cmds]
    if not state.get("scratch") and not state.get("review_pr"):
        wt = state.get("worktree")
        if wt:
            try:
                cmds = run.with_suite(cmds, Path(wt), state.get("target") or state.get("base"),
                                  landing=not state.get("no_merge"))
            except Exception:
                pass
    return run.final_check_line(state, cmds)


def status_details(directory, state, providers=None, cfg=None, index=None):
    """The lines indented under one status row: result, record, workspace,
    and -- where the run waits -- why it stopped and what reopens it.

    `providers` and `cfg` are one listing's usage cache and config, handed
    down so a waiting run's line does not re-read them per row; `index` is its
    `supersession_index`, so a blocked note wears the row's glyph.
    """
    paths = result_paths(directory, state)
    lines = [f"  result: {paths['result']}", f"  record: {paths['record']}",
             f"  limits: silence_minutes={state.get('silence_minutes', run_record.SILENCE_MINUTES):g}, "
             f"ceiling_hours={state.get('ceiling_hours', run_record.CEILING_HOURS):g}"]
    for role in ("workers", "reviewers"):
        if state.get(role) is not None:
            lines.append(f"  {role}: {', '.join(state[role])}")
    if paths["workspace"]:
        location = workspace_location(state, paths["workspace_present"])
        lines.append(f"  workspace: {paths['workspace']} ({location})")
    checked = status_final_check(directory, state)
    if checked:
        lines.append(f"  {checked}")
    if state.get("first"):
        lines.append("  first")
    stalled = run.stall_summary(state)
    if stalled:
        lines.append(f"  {stalled}")
    lines.extend(death_lines(state))
    if state.get("state") == "queued":
        lines.append(f"  {gate.slot_note(state)}")
    elif run.own_pr_wait_note(state):
        lines.append(f"  {run.own_pr_wait_note(state)}")
    elif gate.gate_turn_note(state):
        lines.append(f"  {gate.gate_turn_note(state)}")
    if run.needs_recovery(state):
        reason = run.recovery_reason(state)
        wait = run.waiting(state, providers=providers, cfg=cfg)
        # a run sitting out a provider window resumes itself: the lines say
        # what it waits for, never that the owner should reach for its number
        lines.append(f"  {reason}; {wait}" if wait else
                     f"  {reason}; ak run resume {directory.name} offers recovery")
    note = blocked_note(state, status_state_word(state, index))
    if note:
        from . import terminal
        lines.append("  " + terminal.styled(note, "dim"))
    parked = parked_line(state, directory.name)
    if parked:
        from . import terminal
        lines.append("  " + terminal.styled(parked, "dim"))
    if handback_waiting(state):
        from . import terminal
        lines.append("  " + terminal.styled(handback_waiting(state), "dim"))
    living, ended = alive_line(state), stop_note(state)
    if living or ended:
        from . import terminal
        if living:
            lines.append("  " + terminal.styled(living, "dim"))
        if ended:
            lines.append("  " + terminal.styled(ended, "dim"))
    onward = run.continue_line(state, directory)
    if onward:
        lines.append(f"  {onward}")
    return lines


def size_summary_line(repo):
    """One line per repository for `ak run status --history`: median rounds overall,
    over long tasks and over many-pointed ones, so the orchestrator sizes the next task
    from what this repository's last twenty actually took."""
    summary = history.size_summary(repo)
    if summary is None:
        return None

    def med(value):
        return f"median {value:g} rounds" if value is not None else "–"

    overall, words, points = summary
    return (f"{repo}: last 20 tasks: {med(overall)} · over 400 words: {med(words)} · "
            f"over 3 points: {med(points)}")


def cmd_status(argv):
    show_history, machine = "--history" in argv, "--json" in argv
    plain, why = "--plain" in argv, "--why" in argv
    pending = "--pending" in argv
    args = [arg for arg in argv
            if arg not in ("--history", "--json", "--plain", "--why", "--pending")]
    if len(args) > 1 or any(arg.startswith("-") for arg in args):
        raise config.Error(
            "usage: ak run status [ID] [--history] [--why] [--plain] [--json] [--pending]")
    wanted = args[0] if args else None
    receipts = [(d, jobs.read_job(d)) for d in jobs.job_dirs()]
    receipts = [(d, job) for d, job in receipts if job and isinstance(job.get("tasks"), list)]
    from . import menu
    # Whether a run was superseded asks every record, whichever run or job is shown, but
    # never the smoke suite's own, as on the menu.
    index = None if machine else run.supersession_index(
        state for state in map(run_record.read_state, run_record.run_dirs()) if state and not menu.smoke_run(state))
    if wanted:
        for directory, job in receipts:
            if directory.name == wanted:
                if machine:
                    print(json.dumps({**job, "paths": {
                        "record": str(jobs.receipt_path(directory)),
                        "logs": str(directory / "log.txt")}}, indent=2))
                    return 0
                print(gate.host_status_line())
                alive = jobs.reap_job(directory, job)
                shown = jobs.job_now(job, alive, run.report_config(), index)
                print(jobs.job_block_line(shown))
                if not alive:
                    print(jobs.job_gone_line(directory, job))
                for task in shown["tasks"]:
                    line = f"  {task['name']} {task['state']} {task.get('run_id') or '-'}"
                    if task.get("verdict_line"):
                        line += f"  {task['verdict_line']}"
                    print(line)
                print(f"  record/log: {jobs.receipt_path(directory)} {directory}/log.txt")
                return 0
    dirs = run_record.run_dirs()
    if wanted:
        dirs = [d for d in dirs if d.name == wanted]
        if not dirs:
            raise config.Error(f"no such run: {wanted} (looked in {config.RUNS})")
        # Showing an ending by id marks it looked at. A scheduled error is still
        # working: inspecting its retry does not acknowledge the ending.
        looked = set()
        for single in dirs:
            try:
                if run.mark_looked_at(single):
                    looked.add(single)
            except (OSError, ValueError):
                pass
    if not machine:
        # The header reads the live host, so it prints only once the target
        # resolved: an unknown id errors without any host inspection.
        print(gate.host_status_line())
    found, hidden = [], 0
    for directory in dirs:
        state = run_record.read_state(directory)
        # the smoke suite's own runs are the toolkit testing itself, as on the menu;
        # naming one by id still shows it
        if state and not wanted and menu.smoke_run(state):
            continue
        state = run.reap(directory, state) if state else {"run_id": directory.name,
                                                     "state": "unreadable"}
        if wanted and not machine and directory in looked:
            # the look that just acknowledged an ending still shows it as it found it
            state = {**state, "recovery_acknowledged_at": None}
        # An admitted error or merge wait still belongs to the tick. Once admission
        # ends it ages out of the listing like any other ending, stale stamp or not.
        live = run.going(state) and state.get("state") in ("waiting", "error")
        if (not wanted and not show_history and state.get("state") not in ("running", "queued", "stalled",
                                                                  "unreadable")
                and not actionable(state) and not live and
                time.time() - (state.get("finished_at") or state.get("started_at") or 0) > gc.GC_AGE):
            hidden += 1
            continue
        found.append((directory, state))
    if pending:
        found = [(d, s) for d, s in found if handback_waiting(s)]
    found.sort(key=status_key, reverse=True)
    if machine:
        rows = []
        for directory, state in found:
            row = history.get(state.get("run_id") or directory.name) or {}
            rows.append({**row, **state, "paths": result_paths(directory, state)})
        print(json.dumps(rows, indent=2))
        return 0
    shown_jobs = 0
    if not wanted:
        now = time.time()
        job_cfg = run.report_config() if receipts else None
        for directory, job in sorted(receipts, key=lambda pair: pair[1].get("started_at") or 0,
                                     reverse=True):
            finished = job.get("finished_at")
            # finished jobs older than the run history window are history, like old runs
            if not show_history and isinstance(finished, (int, float)) and now - finished > gc.GC_AGE:
                continue
            alive = jobs.reap_job(directory, job)
            shown = jobs.job_now(job, alive, job_cfg, index)
            print(jobs.job_block_line(shown))
            if not alive:
                print(jobs.job_gone_line(directory, job))
            for task in shown["tasks"]:
                if task.get("verdict_line"):
                    print(f"  {task['verdict_line']}")
            shown_jobs += 1
    if not found and not shown_jobs:
        print(f"no current runs in {config.RUNS}")
    if plain:
        # Read one config for the delivery and waiting words; only waiting needs usage.
        plain_cfg = run.report_config()
        plain_providers = (run._cached_providers() if any(
            state.get("state") == "exhausted" for _, state in found) else {})
        # a `waiting_login` row names its harness out of run.json and reads no meters
        for d, state in found:
            word = state.get("state", "?")
            if word == "queued":
                word = "waiting"
            if word in ("exhausted", "waiting_login"):
                # the run waits for a provider window or a login; both lift by themselves,
                # and the drill-down keeps the state word
                word = run.waiting_word(state, providers=plain_providers, cfg=plain_cfg)
            line = (f"{d.name:<40} {word:<11} {str(state.get('verdict')):<5} "
                    f"{executor_line(state)}/{state.get('reviewer', '?')}  "
                    f"{state.get('branch') or 'scratch'}")
            outcome, step = status_word(state, plain_cfg), step_word(state)
            if state.get("extended"):
                line += (f"  round {len(state.get('round_summaries') or [])}/{state['rounds']} "
                         f"(+{state['extended']})")
            stalled = run.stall_summary(state)
            if stalled:
                line += f"  {stalled}"
            if run.needs_recovery(state):
                line += f"  {run.recovery_reason(state)}; ak run resume {d.name} offers recovery"
            if state.get("state") == "blocked":
                line += f"  blocked: {' '.join((state.get('error') or '').split())}"
            if state.get("pr"):
                line += f"  {outcome} {state['pr']}"
            elif outcome:
                line += f"  {outcome}"
            if step:
                line += f"  {step}"
            if run.self_reviewed(state, plain_cfg):
                line += "  self-reviewed"
            resumed = resume_age(state)
            if resumed:
                line += f"  {resumed}"
            waiting = handback_waiting(state)
            if waiting:
                from . import terminal as _terminal
                line += f"  {_terminal.styled(waiting, 'dim')}"
            print(line)
            if run.landing_line(state):
                print(f"  {parked_line(state, d.name)}")
            elif state.get("state") == "queued":
                print(f"  {gate.slot_note(state)}")
            elif run.own_pr_wait_note(state):
                print(f"  {run.own_pr_wait_note(state)}")
            elif gate.gate_turn_note(state):
                print(f"  {gate.gate_turn_note(state)}")
            if state.get("first"):
                print("  first")
            living, ended = alive_line(state), stop_note(state)
            if living or ended:
                from . import terminal as _terminal
                if living:
                    print("  " + _terminal.styled(living, "dim"))
                if ended:
                    print("  " + _terminal.styled(ended, "dim"))
            if why:
                print(f"  limits: silence_minutes={state.get('silence_minutes', run_record.SILENCE_MINUTES):g}, "
                      f"ceiling_hours={state.get('ceiling_hours', run_record.CEILING_HOURS):g}")
            paths = result_paths(d, state)
            print(f"  result: {paths['result']}  record/logs: {d}")
            if paths["workspace"]:
                location = workspace_location(state, paths["workspace_present"])
                print(f"  workspace: {paths['workspace']} ({location})")
            checked = status_final_check(d, state)
            if checked:
                print(f"  {checked}")
            for death in death_lines(state):
                print(death)
            onward = run.continue_line(state, d)
            if onward:
                print(f"  {onward}")
    else:
        from . import terminal
        try:
            table_cfg = config.load()
        except config.Error:
            table_cfg = None
        header, groups = status_rows(found, terminal.content_width(), index, table_cfg)
        if wanted or why:
            # one id, or every run with --why: each run's lines indented under
            # its own row, never in one block after the table. The usage cache
            # and the config are read once for the waiting lines, never per
            # row -- and nothing is read when no run waits. With no rows there
            # is no header either: `no current runs` above is the whole answer.
            if any(run.needs_recovery(state) for _, state in found):
                try:
                    scope_cfg = config.load()
                except config.Error:
                    scope_cfg = None
                scope_providers = run._cached_providers()
            else:
                scope_cfg, scope_providers = None, {}
            if groups:
                print(header)
            for (directory, state), group in zip(found, groups):
                print("\n".join(group))
                for line in status_details(directory, state, scope_providers, scope_cfg,
                                           index):
                    print(line)
        elif found:
            print(header)
            for (directory, state), group in zip(found, groups):
                print("\n".join(group))
                parked = parked_line(state, directory.name)
                if state.get("state") == "queued":
                    print(f"  {gate.slot_note(state)}")
                elif run.own_pr_wait_note(state):
                    print(f"  {run.own_pr_wait_note(state)}")
                elif gate.gate_turn_note(state):
                    print(f"  {gate.gate_turn_note(state)}")
                elif blocked_note(state):
                    word = status_state_word(state, index)
                    print("  " + terminal.styled(blocked_note(state, word), "dim"))
                elif handback_waiting(state):
                    print("  " + terminal.styled(handback_waiting(state), "dim"))
                elif parked:
                    print("  " + terminal.styled(parked, "dim"))
                if state.get("first"):
                    print("  first")
                living, ended = alive_line(state), stop_note(state)
                if living:
                    print("  " + terminal.styled(living, "dim"))
                if ended:
                    print("  " + terminal.styled(ended, "dim"))

    if not wanted:
        print(f"{hidden} older run(s) hidden; ak run status --history [--json] shows full history")
    if show_history and not wanted and not machine:
        print("\n".join(scoreboard.render()))
        for repo in history.finished_repos():
            line = size_summary_line(repo)
            if line:
                print(line)
    return 0
