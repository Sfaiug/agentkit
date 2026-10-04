"""Several task files are one job (v5q): its receipt, its scheduler and each task's ladder.

`ak run a.md b.md` writes the job's receipt and starts each task as an ordinary run, waits
out spent budget and logins, finishes a passed task's delivery or
reruns a failed one once, and hands the job's line back to the seat that launched it.  A run
itself is `run`'s, called through the module so a test that patches the loop patches it here.
"""

import json
import os
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path

from . import box, config, host, notify, orch, retention, run, task as taskfile, watch
from . import record

JOB_PICKER_INTERVAL = 60  # the executor picker is re-run on every job tick, at most this often
JOB_TICK = 2              # seconds between scheduler passes over the job receipt
OWNER_WORDS_BYTES = 64 * 1024  # spend the receipt's UTF-8 JSON budget on the newest words
JOB_TERMINAL = ("merged", "passed", "failed", "blocked", "skipped", "stopped")
# A task whose work never landed: the job ends nonzero. A blocked or stopped one keeps its own
# word on the log and the status block.
JOB_UNDELIVERED = ("failed", "blocked", "stopped")
_JOB_MUTE = threading.local()  # per-thread job quiet: announce/notify_recovery read it, never swap it


def job_dirs():
    return sorted(d for d in config.JOBS.iterdir() if d.is_dir()) if config.JOBS.exists() else []


def receipt_path(job_dir):
    """Where a job keeps its receipt: gc, status, resume and the menu ask here, never build it."""
    return Path(job_dir) / "job.json"


def read_job(job_dir):
    try:
        state = json.loads((Path(job_dir) / "job.json").read_text())
        return state if isinstance(state, dict) else None
    except (OSError, ValueError):
        return None


def read_jobs():
    """Every receipt under `config.JOBS` that parses, for the menu's job bar; OSError when the
    directory cannot be listed.  A flat `<name>.json` beside the job directories counts too,
    as the menu has always read one."""
    found = []
    for entry in sorted(config.JOBS.iterdir()) if config.JOBS.exists() else []:
        path = receipt_path(entry) if entry.is_dir() else entry
        if path.suffix != ".json":
            continue
        try:
            found.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return found


def read_job_safely(job_dir):
    """gc's read of a receipt: retention's, which never follows a link or reads what is not ours."""
    return retention.read_json(receipt_path(job_dir))


def job_fingerprint(job_dir):
    """The receipt's identity, which gc's plan records and its removal compares."""
    return retention.fingerprint(receipt_path(job_dir))


def save_job(job_dir, job):
    path = Path(job_dir) / "job.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2, ensure_ascii=False))
    tmp.replace(path)


def job_logger(job_dir, to_file):
    def log(message):
        line = f"{datetime.now():%H:%M:%S} {message}"
        print(line, flush=True)
        if to_file:  # the --bg child's stdout already is log.txt; writing again would double it
            with (Path(job_dir) / "log.txt").open("a") as fh:
                fh.write(line + "\n")
    return log


def job_task_by_name(job, name):
    for task in job["tasks"]:
        if task["name"] == name:
            return task
    return None


def job_for_run(run_id):
    """(job_dir, job, task) holding that run, or None: a run belongs to at most one job.

    Read-only.  A stop asks the receipt's own `job_id` first -- it names the job
    from the first write, before the scheduler files the run id -- and this is the
    fallback for receipts a previous version wrote.
    """
    for job_dir in job_dirs():
        job = read_job(job_dir)
        if not job or not isinstance(job.get("tasks"), list):
            continue
        for task in job["tasks"]:
            if isinstance(task, dict) and task.get("run_id") == run_id:
                return job_dir, job, task
    return None


def job_scheduler_owns(run_id, state):
    """Whether the run's pid is still a live job scheduler's, not one loop's.

    The stamp alone cannot say: a task resumed by hand keeps its `job_id` but runs
    under its own pid, and stopping it must end that loop like any run of its own.
    Only a job that is still alive and still owns this exact pid spares the tree.
    """
    job = None
    if state.get("job_id"):
        job_dir = config.JOBS / state["job_id"]
        if (job_dir / "job.json").exists():
            job = read_job(job_dir)
    if job is None:
        found = job_for_run(run_id)
        job = found[1] if found else None
    if not job or job.get("pid") != state.get("pid"):
        return False
    try:
        return bool(record.process_active(job))
    except (TypeError, ValueError, AttributeError, OSError):
        return False  # an old receipt with no pid to check owns nothing live


def job_make_id(first_title):
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    base = f"{stamp}-{run.slugify(first_title)}"
    job_dir = config.JOBS / base
    n = 1
    while job_dir.exists():
        n += 1
        job_dir = config.JOBS / f"{base}-{n}"
    return job_dir


def cap_owner_words(messages):
    """Keep the newest words, including the tail of a prompt larger than the receipt budget."""
    kept, size = [], 2       # the list's brackets
    for message in reversed(messages):
        room = OWNER_WORDS_BYTES - size - (2 if kept else 0)

        def bytes_for(text):
            return len(json.dumps({**message, "text": text}, ensure_ascii=False).encode("utf-8"))

        text = message["text"]
        if bytes_for(text) > room:
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if bytes_for(text[-middle:]) <= room:
                    low = middle
                else:
                    high = middle - 1
            if low:
                kept.append({**message, "text": text[-low:]})
            break
        kept.append(message)
        size += bytes_for(text) + (2 if len(kept) > 1 else 0)
    return list(reversed(kept))


def owner_words(seat):
    """Snapshot the seat's record and return its next launch cursor beside the new words."""
    record = config.session_records().get(seat, {})
    plugin = orch.seat_plugin(record)
    cwd = record.get("cwd")
    conversation = plugin.conversation(record, cwd)
    messages = plugin.user_messages(record, cwd, conversation, seat=seat)
    previous = record.get("owner_words_cursor") or {}
    # Receipts cover pre-upgrade jobs and a restart between the job and seat writes;
    # the seat keeps the cursor after retention removes those receipts.
    for prior in read_jobs():
        if (isinstance(prior, dict) and isinstance(prior.get("seat"), str)
                and config.resolve_session(prior["seat"]) == seat
                and isinstance(prior.get("started_at"), (int, float))
                and prior["started_at"] > previous.get("at", 0)):
            previous = prior.get("owner_words_cursor") or {"at": prior["started_at"]}
    if (previous.get("harness"), previous.get("conversation")) == (plugin.name, conversation):
        fresh = messages[previous.get("count", 0):]
    else:
        fresh = [message for message in messages if not previous or message["at"] > previous["at"]]
    cursor = {"harness": plugin.name, "conversation": conversation,
              "count": len(messages), "at": time.time()}
    return cap_owner_words(fresh), cursor


def job_create(cfg, task_paths, opts, parallel):
    """Build the job receipt before the first run starts; every change after saves it again."""
    if opts.get("--no-worktree"):
        raise config.Error("--no-worktree runs in the repo's current branch: one checkout cannot "
                           "hold a job of concurrent tasks; drop the flag so each task gets its "
                           "own worktree")
    infos = []
    for raw in task_paths:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise config.Error(f"no such task file: {path}")
        meta, body, title = taskfile.parse_task(path)
        # reject malformed commands before allocating anything, as well as a task over the
        # round budget or whose `repo:` names no home here, which nothing waives, and one
        # that looks already under way in the same repository -- unless --anyway says to
        # start beside it regardless, the way a single run does
        cmds = taskfile.done_when(body, path)
        infos.append({"path": path, "meta": meta, "title": title, "stem": path.stem,
                      "name": path.name, "cmds": cmds})
    seen = {}
    for info in infos:
        if info["name"] in seen:
            raise config.Error(f"{info['path']}: another task file in the job is already called "
                               f"{info['name']!r} ({seen[info['name']]}); the job keys tasks "
                               "and threads on that basename, so rename one")
        seen[info["name"]] = info["path"]
    for info in infos:
        refusal = taskfile.launch_refusal(info["meta"])
        if refusal:
            raise config.Error(f"{info['path']}: {refusal}")
        run.repo_line(info["meta"], info["path"])
    if not opts.get("--anyway"):
        for info in infos:
            rivals = run.already_under_way(info["path"], info["meta"], info["title"], info["cmds"])
            if rivals:
                first = rivals[0]
                detail = ", ".join(first["files"]) if first["files"] \
                    else f"{first['words']} title words"
                if len(rivals) > 1:
                    detail += f" and {len(rivals) - 1} more"
                try:
                    started = datetime.fromtimestamp(first["started"]).strftime("%H:%M")
                except (OSError, OverflowError, ValueError, TypeError):
                    started = "??:??"
                seat = first["seat"] or "nobody's"
                raise config.Error(
                    f"{info['path']}: this looks already under way: {first['id']} ({seat}, "
                    f"started {started}, \"{first['title']}\") shares {detail}; wait for "
                    "it, or add --anyway to start a second run")
    seat = config.current_session()
    with notify.session_lock(seat) if seat else nullcontext() as held:
        seat = held or seat
        words, cursor = owner_words(seat) if seat else ([], {"at": time.time()})
        job_dir = job_make_id(infos[0]["title"])
        job_dir.mkdir(parents=True)
        (job_dir / "log.txt").touch()
        job = {"job_id": job_dir.name, "seat": seat, "started_at": cursor["at"], "finished_at": None,
               "owner_words": words, "owner_words_cursor": cursor,
               "parallel": parallel, "executor_history": [], **record.process_owner(), "cwd": os.getcwd(),
               "opts": {key: opts.get(key) for key in ("--rounds", "--exec", "--review",
                                                       "--no-merge", "--no-worktree", "--anyway",
                                                       "--first")},
               "tasks": [{"name": info["name"], "title": info["title"], "state": "queued",
                          "run_id": None, "executor": None, "reviewer": None,
                          "started_at": None, "finished_at": None, "task_file": str(info["path"])}
                         for info in infos]}
        save_job(job_dir, job)
        if seat:
            config.update_session(seat, owner_words_cursor=cursor)
    return job_dir, job


def job_next_executor(cfg, current, workers=None):
    """The next model after `current` in the run's worker list (`config.workers` without), or None.

    A rerun is still that run's executor pick: the rotation goes around the list its
    session bound it to, never wider.
    """
    order = list(workers) if workers else config.workers(cfg)
    if current in order:
        rest = order[order.index(current) + 1:] + order[:order.index(current)]
    else:
        rest = order
    for name in rest:
        if name != current:
            return name
    return None


def job_classify(run_state, cfg):
    """A finished run's job state: merged, passed (no merge was asked, or the target already
    had the work), blocked or failed.

    `blocked` is a failure like any other -- see `JOB_UNDELIVERED` -- and it keeps its own word because no resume, rerun or larger budget can move it: the task
    itself is what was wrong, and only a new task written for it can go anywhere.
    A `stopped` run keeps its own word the same way: deliberately ended, nothing to retry.
    """
    if run_state.get("state") == "stopped":
        return "stopped"
    if run_state.get("state") == "blocked":
        return "blocked"
    if run_state.get("state") == "not_needed":
        return "passed"
    if run.review_pass(run_state, cfg):
        if run_state.get("merged"):
            return "merged"
        if run_state.get("no_merge") or run_state.get("scratch") or run_state.get("on_target"):
            return "passed"
        if str(run_state.get("target") or "").lower() == "none":
            return "passed"
        return "failed"
    return "failed"


def job_verdict_line(task, run_state=None):
    """The one per-task line for the job log and `ak run status`."""
    name = task["name"]
    if task["state"] == "skipped":
        # only receipts from before `after:` went have skipped tasks
        return task.get("verdict_line") or f"{name}: skipped"
    if task["state"] == "stopped":
        return f"{name}: stopped"
    if task["state"] == "blocked":
        why = " ".join(((run_state or {}).get("error") or task.get("findings") or "").split())
        return f"{name}: BLOCKED: {why or 'the task cannot be completed as written'}"
    if task["state"] in ("merged", "passed"):
        rounds = len((run_state or {}).get("round_summaries") or [])
        word = "merged" if task["state"] == "merged" else "passed"
        pr = (run_state or {}).get("pr")
        tail = f" {pr}" if word == "merged" and pr and str(pr).startswith("http") else ""
        return f"{name}: PASS, {word} after {rounds} rounds{tail}".replace(" after 0 rounds", "")
    rounds = len((run_state or {}).get("round_summaries") or [1])
    rerun = task.get("rerun_executor")
    if task.get("resume_attempted") and rerun:
        return (f"{name}: FAIL after {rounds} rounds, resumed once, rerun on {rerun}, "
                "still failing: needs you")
    if task.get("resume_attempted"):
        return f"{name}: FAIL after {rounds} rounds, resumed once, still failing: needs you"
    if rerun:
        return f"{name}: FAIL after {rounds} rounds, rerun on {rerun}, still failing: needs you"
    return f"{name}: FAIL after {rounds} rounds: needs you"


def job_hand_back(seat, line, log, typed=None, receipt=lambda mark: None):
    """Type a finished job's line into its seat: `sent`, `busy` or `gone`.

    The seat has to be found and typed into in the same world -- see `launcher_world` -- and
    only at its own prompt, exactly as a single run's ending is handed back.  `busy` is a seat
    that is there with a turn in flight: the line waits on the job's record and the tick types
    it at the next quiet prompt, because a seat still in its chair is never a reason to ask the
    owner instead.  Only `gone` is.  `typed` and `receipt` are the job record's side of
    `watch.type_at_prompt`'s: a line in the composer is never typed a second time.
    """
    with run.launcher_world(seat) as live:
        if not live:
            return "gone"
        if watch.type_at_prompt(orch.find(seat) or {"name": seat}, line, log,
                                typed=typed, receipt=receipt):
            return "sent"
    return "busy"


def mark_job_delivery(job_dir, job, **marks):
    """`mark_delivery` for a job: write what its delivery decided and nothing else.

    The job's own loop owns the rest of `job.json` -- every task's state and verdict -- and
    keeps writing it while the tick is here.  A whole save from this side would put a copy of
    the tasks from before back over them, and a job resumed since this copy was taken is no
    more this delivery's to mark than a resumed run is.  A mark given as None is removed.
    """
    with run.delivery_lock(job_dir):
        current = read_job(job_dir)
        if current is None:
            current = dict(job)
        elif not run.same_attempt(job, current):
            return False
        for key, value in marks.items():
            if value is None:
                current.pop(key, None)
                job.pop(key, None)
            else:
                current[key] = job[key] = value
        save_job(job_dir, current)
        return True


def deliver_job_handbacks(log):
    """Hand a finished job's line to a seat that was mid-turn when it ended, at the next prompt.

    The tick's pass for jobs, and the same promise a run's `handback_pending` carries: once,
    at the next quiet prompt, and the owner is asked only once the seat is gone.  Two ticks
    can overlap, so the line is read, typed and struck off inside the job's own
    `delivery_lock`, exactly as a run's ending is: whoever takes it second finds nothing left
    to say.
    """
    for job_dir in job_dirs():
        with run.delivery_lock(job_dir):
            job = read_job(job_dir)
            line = (job or {}).get("handback_pending")
            seat = (job or {}).get("seat")
            if not line or not seat:
                continue
            answer = job_hand_back(seat, line, log, job.get("handback_typed"),
                                   lambda mark: mark_job_delivery(job_dir, job, handback_typed=mark))
            if answer == "busy":
                continue
            # the card says what the job's own card says, never the typed line: that one
            # names a path, and a path is the last thing a seat's row or a phone has room for
            card = job.get("handback_card") or line
            done = {"handback_pending": None, "handback_card": None, "handback_typed": None}
            if answer == "sent":
                log(f"handed job {job_dir.name} back to the {seat} seat")
                mark_job_delivery(job_dir, job, card_sent={"kind": "handback",
                                                           "at": job.get("finished_at")}, **done)
            elif notify.shaped("needs", card, session=seat,
                               event_id=f"job:{job.get('job_id')}:{job.get('finished_at')}") == 0:
                mark_job_delivery(job_dir, job, card_sent={"kind": "needs",
                                                           "at": job.get("finished_at")}, **done)
            else:
                log(f"WARN job {job_dir.name}: its card was not accepted; retry required")
                mark_job_delivery(job_dir, job, card_pending=True, **done)


def job_block_line(job):
    """`job <id>: 2 running, 1 queued, 3 merged` for `ak run status`."""
    counts = {}
    for task in job["tasks"]:
        counts[task["state"]] = counts.get(task["state"], 0) + 1
    parts = []
    if counts.get("running"):
        parts.append(f"{counts['running']} running")
    if counts.get("queued"):
        parts.append(f"{counts['queued']} queued")
    known = ("merged", "passed", "skipped", "failed", "blocked", "stopped")
    for state in known:
        if counts.get(state):
            parts.append(f"{counts[state]} {state}")
    # a task whose launcher is gone reads its run's own word (`job_now`): `2 interrupted`
    parts += [f"{count} {state}" for state, count in counts.items()
              if state not in ("running", "queued", *known)]
    return f"job {job['job_id']}: {', '.join(parts) if parts else 'no tasks'}"


def job_now(job, alive, cfg=None, index=None):
    """The job as its runs stand now, for `ak run status`.

    A job writes a task's word and line when the task settles and never again, so a run
    resumed and merged since would still read FAIL, and a task whose launcher died would
    still read `running` over a run that was interrupted.  A settled task, and every task of
    a job whose launcher is gone (`alive` false), reads its run's current state instead; a
    task the live launcher still drives keeps its word, since its ladder may yet resume or
    rerun the run.  A line stops saying `needs you` once the job's own line was handed back
    to its seat, or once the task's run is `settled`.  The job's record is never written; its
    runs are reaped as the listing reaps every run, so a dead loop reads as one.
    """
    handed = ((job.get("card_sent") or {}).get("kind") == "handback"
              or bool(job.get("handback_pending")))
    tasks = []
    for task in job["tasks"]:
        run_state = run.reap(config.RUNS / task["run_id"], {}) if task.get("run_id") else {}
        if run_state.get("state") and (not alive or task.get("state") in JOB_TERMINAL):
            ended = run_state["state"] in run.ENDED
            # a merge is merged whatever today's config makes of its review's providers
            word = ("merged" if run_state.get("merged") else
                    job_classify(run_state, run.report_config(cfg)) if ended else
                    {"waiting": "waiting to merge"}.get(run_state["state"], run_state["state"]))
            # a run that finished after the job wrote its line has new rounds to tell
            if word != task.get("state") or (
                    (run_state.get("finished_at") or 0) > (task.get("finished_at") or 0)):
                task = {**task, "state": word, "verdict_line": (
                    job_verdict_line({**task, "state": word}, run_state) if ended
                    else f"{task['name']}: {word}")}
        if task.get("verdict_line") and (handed or run.settled(run_state, index)):
            task = {**task, "verdict_line": task["verdict_line"].replace(": needs you", "")}
        tasks.append(task)
    return {**job, "tasks": tasks}


def job_allocate_run_dir(title):
    """An ordinary run directory with a name no concurrent task takes: mkdir wins the race."""
    run_id = f"{datetime.now():%Y%m%d-%H%M}-{run.slugify(title)}"
    n = 1
    while True:
        run_dir = config.RUNS / (run_id if n == 1 else f"{run_id}-{n}")
        try:
            run_dir.mkdir(parents=True)
        except FileExistsError:
            n += 1
            continue
        (run_dir / "log.txt").touch()
        return run_dir


@contextmanager
def job_muted():
    """A job sends nothing per finished task: blocked runs still speak.

    A counter on thread-local state, so threads entering and leaving interleave safely --
    no globals are swapped and nothing is left behind. `announce` and `notify_recovery`
    read it and stay quiet only for finished attempts (pass/fail/error, which carry
    `recovery_pending` after a resume); genuinely blocked runs notify as today.
    """
    _JOB_MUTE.depth = getattr(_JOB_MUTE, "depth", 0) + 1
    try:
        yield
    finally:
        _JOB_MUTE.depth -= 1


def job_started(state):
    """Whether this process is a task its job started in a scope of its own (`job_scoped`).

    The job's quiet is thread-local in its own process.  A task it placed apart inherits the
    job's directory in its environment instead, and names that job on its receipt.
    """
    return bool(state.get("job_id")) and \
        Path(os.environ.get(config.JOB_DIR_ENV) or "").name == state["job_id"]


@contextmanager
def job_adopting(run_name):
    """While the job adopts one run, that run's recovery notice stays unsent.

    The scheduler reaps the run to learn its state, then resumes it itself seconds
    later: a "do not automatically rerun it" message now would be per-task noise the
    job immediately contradicts. Thread-local like `job_muted`, and it names the run
    so a glance at the flag says whose notice is held.
    """
    previous, _JOB_MUTE.adopt = getattr(_JOB_MUTE, "adopt", None), run_name
    try:
        yield
    finally:
        _JOB_MUTE.adopt = previous


def job_budget_exhausted(error):
    """Whether an `exhausted` error is spent provider budget (wait) rather than a stop.

    Only these messages mean more budget later: gate meters at 100% and no eligible
    reviewer. A twice-silent reviewer names the same spare
    shortage but spends reviewer turns on every resume, so it waits capped below
    instead. A stopped tool, a refused prompt, or a structural delivery complaint
    needs the owner instead.
    """
    text = error or ""
    return "100% used" in text or ("no eligible reviewer" in text
                                   and "gave no verdict twice" not in text)


def job_transport_exhausted(error):
    """Whether an `exhausted` error spends reviewer turns on every resume: a reviewer
    dying on API/transport errors, or one that twice answered without a verdict.

    The meters read healthy either way, so the picker keeps passing and every resume
    re-spends reviewer turns before failing again: the wait is capped, never forever.
    """
    text = error or ""
    return "API/transport errors" in text or "gave no verdict twice" in text


def job_round_shortfall(run_state):
    """Whether an `exhausted` run is really a spent round budget, which only more rounds fix.

    Integration invalidating the review at the last round (and a merge error with a
    pending review) raises `Exhausted` with outstanding `review_pending` work that only
    a resume finishes -- the run itself prints the way on. The ladder treats this like a
    FAIL at its budget that no review failed: no more rounds, since three is the budget,
    but the one rerun on the next executor model, rather than the budget wait (which would
    never help) or a failure on the spot.
    """
    if run_state.get("state") != "exhausted":
        return False
    if run_state.get("review_pending"):
        return True
    return "round budget" in (run_state.get("error") or "")


def job_wait_budget(job_dir, job, task, log, lock, error, where, rounds=None):
    """Requeue a budget-exhausted task with pacing; transport outages get a cap.

    Gate-meter exhaustion waits indefinitely -- the spec never fails a task for lack of
    budget, and the resume spends no model turn while the picker still says exhausted.
    A transport outage does spend (reviewer turns with backoff on every resume), so
    after `JOB_TRANSPORT_WAITS` paced waits the task needs its owner instead of
    burning turns silently forever. The cap counts one outage, not history: when the
    attempt completed more rounds than the last wait saw, a new episode starts at one.
    Returns True when the task now waits in `queued`.
    """
    if job_transport_exhausted(error):
        last = task.get("transport_rounds")
        if rounds is not None and last is not None and rounds > last:
            waits = 1
        else:
            waits = task.get("transport_waits", 0) + 1
        task["transport_waits"] = waits
        task["transport_rounds"] = rounds
        if waits > JOB_TRANSPORT_WAITS:
            task.update(state="failed", finished_at=time.time(),
                        verdict_line=f"{task['name']}: FAIL: needs you ({error[:300]})",
                        findings=error)
            with lock:
                save_job(job_dir, job)
            log(task["verdict_line"])
            return False
    else:
        task["exhausted_waits"] = task.get("exhausted_waits", 0) + 1
    task["budget_wait"] = True
    task["retry_after"] = time.time() + JOB_PICKER_INTERVAL
    task["state"] = "queued"
    with lock:
        save_job(job_dir, job)
    count = task.get("transport_waits") or task.get("exhausted_waits")
    log(f"{task['name']}: exhausted {where} ({error}); "
        f"waiting for budget (wait {count})")
    return True


JOB_TRANSPORT_WAITS = 5  # paced outage waits before a transport-exhausted task needs its owner


def job_wait_login(job_dir, job, task, log, lock, run_state, where):
    """Whether this attempt parked on an expired login, and if so, wait beside it.

    Nothing in a job can log anybody in, and the tick resumes the run itself the moment that
    harness's `auth` verb passes: the task waits at the picker's own rate, the way it waits
    for spent budget, rather than spending its one resume and its one rerun on a wall and
    then calling work nobody faulted a failure.  Every attempt a task makes asks this.
    """
    if run_state.get("state") != "waiting_login":
        return False
    job_wait_budget(job_dir, job, task, log, lock,
                    run_state.get("error") or "a harness login expired", where,
                    rounds=len(run_state.get("round_summaries") or []))
    return True


class LegacyTask(config.Error):
    """A task from a receipt before `after:` went: a fresh run would lack what it waited for."""


def job_block_legacy(task, exc):
    """Hand a never-built legacy task back to its seat: blocked, the relaunch its findings."""
    task.update(state="blocked", finished_at=time.time(), findings=str(exc),
                verdict_line=f"{task['name']}: BLOCKED: {exc}")


def job_legacy_refusal(task):
    """Why a task from a receipt before `after:` went cannot get a fresh run, or ""."""
    deps = task.get("after") or ([task["from_pass"].get("task")] if task.get("from_pass") else [])
    return (f"`after:` is gone; launch {task['name']} on its own once "
            f"{', '.join(map(str, deps))} merged") if deps else ""


def job_start_task(cfg, job_dir, task, opts, log):
    """Allocate an ordinary run directory and launch it; the caller marks running first."""
    if job_legacy_refusal(task):
        raise LegacyTask(job_legacy_refusal(task))
    task_path = Path(task["task_file"])
    _, _, title = taskfile.parse_task(task_path)
    run_dir = job_allocate_run_dir(title)
    extra = task.get("starting_branch")
    text = task_path.read_text()
    if extra:
        text = text.rstrip() + (f"\n\n## Starting point\nPrevious attempt branch: {extra}\n")
    (run_dir / "task.md").write_text(text)
    run_opts = {"--rounds": opts.get("--rounds"), "--exec": task.get("exec_override") or opts.get("--exec"),
                "--review": task.get("review_override") or opts.get("--review"),
                "--review-pr": None,
                "--no-merge": bool(opts.get("--no-merge")), "--no-worktree": bool(opts.get("--no-worktree")),
                "--anyway": bool(opts.get("--anyway")), "--first": bool(opts.get("--first")),
                "--bg": False}
    if task.get("rerun_attempted") and run_opts["--review"]:
        kept = run_opts["--review"]
        if run.same_model(cfg, run_opts["--exec"], kept):
            log(f"{task['name']}: reviewer {kept} is the rerun executor's own model; "
                "the rerun will pick another reviewer")
            run_opts["--review"] = None
    run.prepare(run_dir, run_opts, run.logger(run_dir, True), cfg, job_id=job_dir.name, task_file=task_path)
    log(f"{task['name']} start: {run_dir.name}")
    return run_dir, run_opts


def job_scoped(job):
    """Whether this process sits in the job's own scope, whose one memory cap is not a task's.

    `spawn_job_bg` places a job in `agentkit-job-<id>`, and a task run in that process would
    share the job's cap with every other task.  So a job in a scope of its own starts each
    task in one of its own instead, the way `--bg` starts a lone run.  A job run from a
    terminal -- or resumed there after its scoped launcher died -- runs its tasks in its own
    process, as a lone run from a terminal does.
    """
    scope = job.get("scope")
    if not run.scope_is_real(scope):
        return False
    cgroup = host.process_cgroup()
    return (cgroup is not None and
            cgroup.rstrip("/").rsplit("/", 1)[-1] in (f"{scope}.scope", f"{scope}.service"))


def job_await(run_dir, poll=lambda: None):
    """Follow a task's run in its own scope until the job's ladder can take it up.

    It is a lone run in everything but its voice, so it goes on as one does: while its
    process lives, and while the tick carries a death of it on -- a resume ordered or backing
    off, or a death recorded for the dead-loop pass -- it is still going.  What comes back is
    its ending, a wait for budget or a login, or what the tick left for a person.
    """
    while True:
        poll()
        state = record.read_state(run_dir) or {}
        if not record.process_active(state):
            with job_adopting(run_dir.name):
                state = run.reap(run_dir, state)
            if not (state.get("state") in ("queued", "running")
                    or (state.get("state") == "waiting"
                        and (state.get("waiting_on") or {}).get("line"))
                    or (state.get("state") == "interrupted" and state.get("deaths")
                        and run.tick_resumes(state))):
                return state
        time.sleep(JOB_TICK)


def job_drive(cfg, run_dir, run_opts, box, scoped=False):
    """One `drive` to completion, muted so the job stays the only voice; never raises.

    `scoped` starts it the way `--bg` starts a lone run, in a run scope with a memory cap of
    its own, and follows it there (see `job_scoped`).
    """
    try:
        if scoped:
            argv = [str(run_dir / "task.md")]
            for key in ("--rounds", "--exec", "--review"):
                if run_opts.get(key):
                    argv += [key, str(run_opts[key])]
            argv += [key for key in ("--no-merge", "--anyway", "--first") if run_opts.get(key)]
            run.spawn_bg(run_dir, argv)
            box["state"] = job_await(run_dir)
            box["rc"] = 0 if job_classify(box["state"], cfg) in ("merged", "passed") else 1
            return
        log = run.logger(run_dir, True)
        with job_muted():
            box["rc"] = run.drive(cfg, run_dir, run_opts, log)
        box["state"] = record.read_state(run_dir) or {}
    except config.Error as exc:
        box["rc"] = 2
        box["state"] = record.read_state(run_dir) or {"state": "error", "verdict": "ERROR",
                                               "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - a crashed task run must still end its thread
        box["rc"] = 2
        box["state"] = record.read_state(run_dir) or {"state": "error", "verdict": "ERROR",
                                               "error": repr(exc)}


def job_exit_line(task, run_dir, run_state, rc):
    merged = bool(run_state.get("merged"))
    return (f"{task['name']} exit {rc}: {run_dir.name} {run_state.get('state')} "
            f"{run_state.get('verdict')} {'merged' if merged else 'not merged'}")


def job_settle(cfg, job_dir, job, task, run_dir, run_state, log, lock):
    """A terminal attempt becomes the task's result; the receipt is current before returning."""
    outcome = job_classify(run_state, cfg)
    task.update(state=outcome, finished_at=time.time(), verdict_line=job_verdict_line(
        {**task, "state": outcome}, run_state))
    if outcome == "failed":
        task["findings"] = run_state.get("findings") or run_state.get("error") or ""
    with lock:
        save_job(job_dir, job)
    log(task["verdict_line"])


def job_follow_waiting(run_dir, run_state, log):
    """Waiting is no ending, including when a delivery retry leaves it in the line."""
    asked = 0
    while run_state.get("state") == "waiting" and run.tick_admission(run_state):
        if not run.landing_line(run_state) and time.time() - asked >= JOB_PICKER_INTERVAL:
            asked = time.time()   # each ask fetches: at the picker's rate, not every tick
            watch.resume_waiting(log=log, run=run_dir)
        time.sleep(JOB_TICK)
        run_state = record.read_state(run_dir) or run_state
        if run_state.get("state") != "waiting":
            run_state = job_await(run_dir)
    return run_state


def job_ladder(cfg, job_dir, job, task, run_dir, run_state, rc, log, lock):
    """The retries, in the worker thread, so the scheduler keeps scheduling while they run.

    An `exhausted` run waits for budget rather than failing; a PASS whose delivery failed is
    finished with `ak run merge`, not re-executed; only then comes the one rerun on the next
    executor model, for a FAIL at its budget its reviews did not fail.  No task is given
    more rounds, and one its reviews failed is not rerun either: it goes back to the seat
    with its findings, as a single run does, to be split or re-scoped.
    """
    if (run_state.get("state") == "waiting"
            and (run_state.get("waiting_on") or {}).get("line")):
        run_state = job_await(run_dir)
    task["executor"] = run_state.get("executor") or task.get("executor")
    task["reviewer"] = run_state.get("reviewer") or task.get("reviewer")
    log(job_exit_line(task, run_dir, run_state, rc))
    if run_state.get("state") == "waiting":
        # A wait is no ending: the task follows the lander or the target moving,
        # so its dependants wait instead of skipping.
        log(f"{task['name']}: parked waiting ({run_state.get('error')}); following it")
    run_state = job_follow_waiting(run_dir, run_state, log)
    if job_wait_login(job_dir, job, task, log, lock, run_state, "mid-run"):
        return
    if run_state.get("state") == "stopped":
        # Deliberately ended: no resume, no rerun, no budget wait. The task keeps
        # the run's word.
        job_settle(cfg, job_dir, job, task, run_dir, run_state, log, lock)
        return
    if run_state.get("state") == "exhausted":
        error = run_state.get("error") or "no reason was recorded"
        if job_budget_exhausted(error) or job_transport_exhausted(error):
            # the message decides first: a pending review parked on spent meters waits
            # for budget even with `review_pending` still set -- the resume the shortfall
            # rule would spend has nothing to bill to
            job_wait_budget(job_dir, job, task, log, lock, error, "mid-run",
                            rounds=len(run_state.get("round_summaries") or []))
            return
        if not job_round_shortfall(run_state):
            # a stopped tool or a structural complaint: no resume can fix it, the owner
            # is needed
            task.update(state="failed", finished_at=time.time(),
                        verdict_line=f"{task['name']}: FAIL: needs you ({error[:300]})",
                        findings=error)
            with lock:
                save_job(job_dir, job)
            log(task["verdict_line"])
            return
    outcome = job_classify(run_state, cfg)
    if outcome in ("merged", "passed", "skipped"):
        job_settle(cfg, job_dir, job, task, run_dir, run_state, log, lock)
        return
    if run_state.get("state") == "pass" and run_state.get("merge_failed"):
        # reviewed work with only its delivery left: finish it with the one command for that
        log(f"{task['name']}: PASS needs delivery; merging with ak run merge {run_dir.name}")
        try:
            if job_scoped(job):
                # in a run scope of its own, like every other attempt the task makes
                pid = watch.launch_resume(run_dir.name, log, verb="merge")
                launched = record.process_owner(pid) if pid else {}
                while record.process_active(launched):
                    time.sleep(JOB_TICK)
                settled = job_await(run_dir) if pid else {}
                mrc = 0 if job_classify(settled, cfg) in ("merged", "passed") else 1
            else:
                with job_muted():
                    mrc = run.cmd_merge([run_dir.name])
                waiting = record.read_state(run_dir) or {}
                if (waiting.get("state") == "waiting"
                        and (waiting.get("waiting_on") or {}).get("line")):
                    settled = job_await(run_dir)
                    mrc = 0 if job_classify(settled, cfg) in ("merged", "passed") else 1
        except config.Error as exc:
            mrc = 2
            log(f"{task['name']}: merge refused: {exc}")
        run_state = job_follow_waiting(run_dir, record.read_state(run_dir) or run_state, log)
        task["executor"] = run_state.get("executor") or task.get("executor")
        task["reviewer"] = run_state.get("reviewer") or task.get("reviewer")
        log(job_exit_line(task, run_dir, run_state, mrc))
        if job_wait_login(job_dir, job, task, log, lock, run_state, "on delivery"):
            return
        if job_classify(run_state, cfg) in ("merged", "passed"):
            job_settle(cfg, job_dir, job, task, run_dir, run_state, log, lock)
            return
        # `ak run merge` runs fixer turns of its own, and one of them can end the run
        # `blocked`: that word is the run's, and nothing here turns it into a delivery that
        # failed -- the same rule the ladder's last word obeys below. A stop between
        # the merge and this line keeps its word the same way.
        if run_state.get("state") == "stopped":
            job_settle(cfg, job_dir, job, task, run_dir, run_state, log, lock)
            return
        blocked = run_state.get("state") == "blocked"
        task["state"] = "blocked" if blocked else "failed"
        task.update(finished_at=time.time(),
                    verdict_line=(job_verdict_line(task, run_state) if blocked else
                                  f"{task['name']}: PASS, delivery failed: needs you"),
                    findings=(run_state.get("merge_note") or run_state.get("error") or ""))
        with lock:
            save_job(job_dir, job)
        log(task["verdict_line"])
        return
    # a FAIL at its round budget gets no more rounds: three is the budget.  One its reviews
    # failed goes back to the seat with its findings, as a single run's does, to be split
    # or re-scoped.  One a check or integration left behind -- or an `exhausted` that is
    # really a spent round budget -- starts once more on the next executor model in
    # worker-list order
    if not task.get("rerun_attempted") and job_classify(run_state, cfg) == "failed" \
            and (run.failed_at_budget(run_state) or job_round_shortfall(run_state)) \
            and not run.review_failed(run_state):
        nxt = job_next_executor(cfg, task.get("executor") or run_state.get("executor"),
                                run.run_workers(cfg, run_state))
        if nxt:
            # The rerun keeps the job's reviewer unless it is the rerun executor's own
            # model; then the fresh run picks another reviewer (`job_start_task`).
            task.pop("review_override", None)
            task["rerun_attempted"] = True
            task["rerun_executor"] = nxt
            task.setdefault("executor_history", []).append(
                {"at": time.time(), "from": run_state.get("executor"), "to": nxt,
                 "reason": "budget-failover"})
            job.setdefault("executor_history", []).append(
                {"task": task["name"], "from": run_state.get("executor"), "to": nxt})
            with lock:
                save_job(job_dir, job)
            log(f"{task['name']}: still failing, rerunning on {nxt}")
            branch = run_state.get("branch")
            task["starting_branch"] = branch
            task["exec_override"] = nxt
            task["run_id"] = None
            with lock:
                save_job(job_dir, job)
            try:
                run_dir2, run_opts2 = job_start_task(cfg, job_dir, task, job["opts"], log)
            except LegacyTask as exc:
                job_block_legacy(task, exc)
                with lock:
                    save_job(job_dir, job)
                log(task["verdict_line"])
                return
            except (config.Error, OSError) as exc:
                task.update(state="failed", finished_at=time.time(),
                            verdict_line=f"{task['name']}: FAIL: needs you ({exc})")
                with lock:
                    save_job(job_dir, job)
                log(task["verdict_line"])
                return
            task["run_id"] = run_dir2.name
            # a new run starts new episodes: the old outage counts stay with the old run
            for key in ("exhausted_waits", "transport_waits", "transport_rounds",
                        "retry_after", "budget_wait"):
                task.pop(key, None)
            with lock:
                save_job(job_dir, job)
            box = {}
            job_drive(cfg, run_dir2, run_opts2, box, job_scoped(job))
            run_state2 = job_follow_waiting(
                run_dir2, box.get("state") or record.read_state(run_dir2) or {}, log)
            task["executor"] = run_state2.get("executor") or nxt
            task["reviewer"] = run_state2.get("reviewer") or task.get("reviewer")
            log(job_exit_line(task, run_dir2, run_state2, box.get("rc", 1)))
            if job_wait_login(job_dir, job, task, log, lock, run_state2, "on rerun"):
                return
            if run_state2.get("state") == "exhausted" \
                    and not job_round_shortfall(run_state2):
                error2 = run_state2.get("error") or "no reason was recorded"
                if job_budget_exhausted(error2) or job_transport_exhausted(error2):
                    job_wait_budget(job_dir, job, task, log, lock, error2, "on rerun",
                                    rounds=len(run_state2.get("round_summaries") or []))
                    return
            if job_classify(run_state2, cfg) in ("merged", "passed"):
                job_settle(cfg, job_dir, job, task, run_dir2, run_state2, log, lock)
                return
            run_state = run_state2
    # a blocked run keeps its own word here: nothing above it resumed or reran one, and
    # nothing below it should read it as a FAIL that another round might have carried.
    # A stopped run keeps its word the same way.
    if run_state.get("state") == "stopped":
        task["state"] = "stopped"
    else:
        task["state"] = "blocked" if run_state.get("state") == "blocked" else "failed"
    task.update(finished_at=time.time(), verdict_line=job_verdict_line(task, run_state),
                findings=(run_state.get("findings") or run_state.get("error") or ""))
    with lock:
        save_job(job_dir, job)
    log(task["verdict_line"])


def job_fresh_worker(cfg, job_dir, job, task, run_dir, run_opts, lock, log):
    """A task's whole ladder -- initial drive, resume, rerun -- inside its own thread.

    The scheduler stays a scheduler while retries run for hours: it keeps starting queued
    tasks and reaping finished ones.
    """
    box = {}
    job_drive(cfg, run_dir, run_opts, box, job_scoped(job))
    try:
        job_ladder(cfg, job_dir, job, task, run_dir,
                   box.get("state") or record.read_state(run_dir) or {}, box.get("rc", 1), log, lock)
    except (OSError, ValueError, KeyError, TypeError):
        task.update(state="failed", finished_at=time.time(),
                    verdict_line=f"{task['name']}: FAIL: needs you")
        with lock:
            save_job(job_dir, job)
        log(task["verdict_line"])


def job_adopt_worker(cfg, job_dir, job, task, run_dir, lock, log):
    """A run from before a kill, resumed and settled inside its own thread.

    Finished attempts go straight to the ladder with their result kept; genuinely
    unfinished ones resume through the existing run resume. Nothing is re-executed from
    scratch here, so a branch is never delivered twice and the ladder bookkeeping stands.

    A run parked on an expired login is not one of the unfinished ones: nothing here can
    log anybody in, so a resume from this thread would park it again before it reached a
    model and spend a launch on a wall every pass.  It goes to the ladder, which waits for
    it the way it waits for spent budget, and the tick resumes it when the login is back.
    """
    try:
        with job_adopting(run_dir.name):
            run_state = run.reap(run_dir, record.read_state(run_dir) or {})
        if (run_state.get("state") == "queued" and run_state.get("slot_waiting") and
                not record.process_active(run_state)) or run_state.get("state") in (
                "interrupted", "exhausted", "stalled") or (
                run.needs_recovery(run_state) and run_state.get("state") not in run.ENDED
                and run_state.get("state") != "waiting_login"):
            # a scoped job resumes it in a run scope of its own and follows it there
            scoped = job_scoped(job)
            with job_adopting(run_dir.name), job_muted():
                run.cmd_resume([run_dir.name, "--bg"] if scoped else [run_dir.name])
            run_state = job_await(run_dir) if scoped else record.read_state(run_dir) or run_state
        if run_state.get("state") in ("running", "queued"):
            # `reap` declined it (inside its grace) or it is parked: pace the next look at
            # the once-a-minute rate and keep the run, so adopt hands back instead of spinning
            task["retry_after"] = time.time() + JOB_PICKER_INTERVAL
            task["state"] = "queued"
            with lock:
                save_job(job_dir, job)
            return
        job_ladder(cfg, job_dir, job, task, run_dir, run_state,
                   0 if job_classify(run_state, cfg) in ("merged", "passed") else 1, log, lock)
    except config.Error as exc:
        # the kept run refuses resume (e.g. a budget FAIL rerun from scratch is the ladder's
        # job, not this adoption's): clear it and let the scheduler start the task over with
        # its ladder flags intact
        log(f"{task['name']}: resume refused: {exc}")
        task["run_id"] = None
        task["state"] = "queued"
        with lock:
            save_job(job_dir, job)
    except (OSError, ValueError, KeyError, TypeError):
        task.update(state="failed", finished_at=time.time(),
                    verdict_line=f"{task['name']}: FAIL: needs you")
        with lock:
            save_job(job_dir, job)
        log(task["verdict_line"])


def reap_job(job_dir, job):
    """Whether the job's launcher is still alive: a dead one is the tick's to relaunch when
    `job_admission` says so, and otherwise needs `ak run resume <job>`."""
    if job.get("finished_at"):
        return True
    try:
        return record.process_active(job)
    except (TypeError, ValueError, AttributeError):
        return True  # uncertainty is never evidence of an exit


def job_waiting(seat):
    """A live job this seat can wait on, even before any task has a run directory."""
    try:
        directories = job_dirs()
    except OSError:
        return False
    for directory in directories:
        job = read_job(directory)
        if not job or not isinstance(job.get("tasks"), list):
            continue
        owner = job.get("seat")
        try:
            if not isinstance(owner, str) or not owner or (
                    owner != seat and config.resolve_session(owner) != seat):
                continue
        except config.Error:
            continue
        if reap_job(directory, job) and any(
                isinstance(task, dict) and task.get("state") not in JOB_TERMINAL
                for task in job["tasks"]):
            return True
    return False


def job_admission(job_dir, job, now=None):
    """Why the tick may relaunch this job whose launcher is gone, or nothing: a person's.

    `tick_admission`'s bounds, for a job: a seat launched it, that seat's session -- by its
    name now -- still exists and its owner did not close it, no run of an unfinished task that
    stopped short of its ending was handed back, carded or acknowledged, and the launcher was
    alive under a day ago.  A launcher dies without writing an ending, so its heartbeat -- the
    last write in the job's directory, which none of the tick's run passes touch -- stands in
    for one.  The directory it was launched from must still be there: a task that names no
    repo finds its checkout from it.  A job with a task its owner stopped stays as it is.  So
    does one the tick relaunched twice in the hour before it died again: a third death parks
    it, as a run's does.
    """
    try:
        seat = config.resolve_session(job["seat"]) if job.get("seat") else None
        if not seat or not config.session_path(seat).is_file() \
                or watch.seat_closed_by_owner(seat):
            return ""
    except config.Error:
        return ""
    if not job.get("cwd") or not Path(job["cwd"]).is_dir():
        return ""
    for task in job["tasks"]:
        run_state = (record.read_state(config.RUNS / task["run_id"]) if task.get("run_id") else None) or {}
        if "stopped" in (task.get("state"), run_state.get("state")):
            return ""
        if (task.get("state") not in JOB_TERMINAL and run_state.get("state") not in run.ENDED
                and any(run_state.get(key) for key in (
                    "handed_back", "recovery_notified", "recovery_acknowledged_at"))):
            return ""
    now = time.time() if now is None else now
    alive_at = watch.run_last_write(job_dir)
    if not 0 <= now - alive_at < 86400:
        return ""
    relaunches = [at for at in job.get("relaunches") or []
                  if isinstance(at, (int, float)) and 0 <= alive_at - at < watch.DEAD_WINDOW]
    if len(relaunches) >= 2:
        return ""
    return f"session {seat} exists; alive under 24h ago; no task stopped"


def job_gone_line(job_dir, job):
    """The line under a job whose launcher is gone: whose it is to continue."""
    admission = job_admission(job_dir, job)
    if admission:
        return f"  launcher gone; the next tick relaunches it · {admission}"
    return f"  launcher gone; ak run resume {job_dir.name} to continue"


def run_job_loop(cfg, job_dir, job, to_file=True):
    """Start queued tasks at once up to `--parallel`, each an independent piece."""
    job_dir = Path(job_dir)
    log = job_logger(job_dir, to_file)
    lock = threading.Lock()
    threads = {}  # name -> worker Thread
    last_picker = [0.0]
    opts = job.get("opts") or {}
    parallel = job.get("parallel")
    limit = config.max_runs()
    if limit:
        parallel = min(parallel, limit) if parallel else limit
    # This process owns the receipt from here on, so a kill reads as unfinished, not
    # running. Under the recovery lock a `--bg` child starts only after its launcher's
    # handoff save, the way a run child waits on its own receipt.
    with record.recovery_lock(job_dir):
        job.update(record.process_owner())
        with lock:
            save_job(job_dir, job)

    def save():
        with lock:
            save_job(job_dir, job)

    for task in job["tasks"]:
        if task["state"] == "waiting":
            # a receipt from before `after:` went: a kept run decides for itself (`run.loop`
            # ends one still on its dependency); one without goes back to its seat below
            task["state"] = "queued"
            save()
    while True:
        for name, thread in list(threads.items()):
            if thread.is_alive():
                continue
            threads.pop(name)
            task = job_task_by_name(job, name)
            if task["state"] == "running":
                # its worker died mid-flight with the run still open; requeue, run kept
                task["state"] = "queued"
                save()
                log(f"{name}: worker died; requeued")
        # running tasks with no thread own a run from before a kill: adopt it in a worker
        for task in job["tasks"]:
            if task["state"] != "running" or task["name"] in threads:
                continue
            if parallel is not None and len(threads) >= parallel:
                break
            now = time.time()
            if task.get("retry_after", 0) > now:
                continue  # a live record elsewhere is re-checked at most once a minute
            run_id = task.get("run_id")
            rundir = config.RUNS / run_id if run_id else None
            if rundir is None or not (rundir / "run.json").exists():
                task["state"] = "queued"
                task["run_id"] = None
                save()
                continue
            with job_adopting(rundir.name):
                state = run.reap(rundir, record.read_state(rundir) or {})
            if state.get("state") in ("running", "queued") and record.process_active(state):
                # alive elsewhere; its own scheduler owns it: look again in a minute,
                # not every tick (the reap takes the run's lock each time)
                task["retry_after"] = now + JOB_PICKER_INTERVAL
                save()
                continue
            thread = threading.Thread(target=job_adopt_worker,
                                      args=(cfg, job_dir, job, task, rundir, lock, log),
                                      daemon=True)
            threads[task["name"]] = thread
            thread.start()
        # a legacy task goes back to its seat before any slot, retry or budget wait unless its
        # kept run already stands on the target: no fresh run, and no resume of one still on
        # its dependency, can give it what it waited for
        for task in job["tasks"]:
            kept = task.get("run_id")
            if task["state"] != "queued" or not job_legacy_refusal(task):
                continue
            kept_state = record.read_state(config.RUNS / kept) if kept else None
            if not kept_state or run.stands_on_dependency(kept_state):
                job_block_legacy(task, job_legacy_refusal(task))
                save()
                log(task["verdict_line"])
        running = sum(1 for task in job["tasks"] if task["state"] == "running")
        # queued tasks with no brake start at once; provider budgets only
        for task in job["tasks"]:
            if task["state"] != "queued" or task["name"] in threads:
                continue
            if parallel is not None and running >= parallel:
                break
            now = time.time()
            if task.get("retry_after", 0) > now:
                continue  # paced waits (budget, grace) retry at most once a minute
            if task.get("budget_wait") and now - last_picker[0] < JOB_PICKER_INTERVAL:
                continue
            try:
                providers = run.collect_usage(cfg)
                run.pick_models(cfg, providers, opts.get("--exec"), opts.get("--review"), lambda _: None)
            except run.Exhausted:
                # a pair no budget can make is not waited for: the task's run refuses it at launch
                if not run.pair_refusal(cfg, providers, None, opts.get("--exec"),
                                    opts.get("--review")):
                    task["budget_wait"] = True
                    task["retry_after"] = now + JOB_PICKER_INTERVAL
                    last_picker[0] = now
                    save()
                    continue
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                task["budget_wait"] = True
                task["retry_after"] = now + JOB_PICKER_INTERVAL
                last_picker[0] = now
                save()
                continue
            except config.Error as exc:
                task.update(state="failed", finished_at=time.time(),
                            verdict_line=f"{task['name']}: FAIL: needs you ({exc})")
                save()
                log(task["verdict_line"])
                continue
            task.pop("budget_wait", None)
            kept = task.get("run_id")
            kept_dir = config.RUNS / kept if kept else None
            if kept_dir is not None and (kept_dir / "run.json").exists():
                # an exhausted or interrupted run kept across ticks: reap it here so a live
                # record is never adopted, then resume it in a worker, never redo it
                with job_adopting(kept_dir.name):
                    kept_state = run.reap(kept_dir, record.read_state(kept_dir) or {})
                if kept_state.get("state") in ("running", "queued") \
                        and record.process_active(kept_state):
                    # alive elsewhere; its own scheduler owns it: back off like every wait
                    task["retry_after"] = now + JOB_PICKER_INTERVAL
                    save()
                    continue
                task["state"] = "running"
                save()
                thread = threading.Thread(target=job_adopt_worker,
                                          args=(cfg, job_dir, job, task, kept_dir, lock, log),
                                          daemon=True)
                threads[task["name"]] = thread
                thread.start()
                running += 1
                continue
            task["state"] = "running"
            task["started_at"] = time.time()
            save()
            try:
                run_dir, run_opts = job_start_task(cfg, job_dir, task, opts, log)
            except LegacyTask as exc:
                job_block_legacy(task, exc)
                save()
                log(task["verdict_line"])
                continue
            except record.StopRequested:
                # A stop landed during preflight: the receipt already says so, so
                # the task keeps the run's word and nothing is launched to carry on.
                task.update(state="stopped", finished_at=time.time(),
                            verdict_line=f"{task['name']}: stopped")
                save()
                log(task["verdict_line"])
                continue
            except (config.Error, OSError) as exc:
                task.update(state="failed", finished_at=time.time(),
                            verdict_line=f"{task['name']}: FAIL: needs you ({exc})")
                save()
                log(task["verdict_line"])
                continue
            task["run_id"] = run_dir.name
            save()
            thread = threading.Thread(target=job_fresh_worker,
                                      args=(cfg, job_dir, job, task, run_dir, run_opts,
                                            lock, log),
                                      daemon=True)
            threads[task["name"]] = thread
            thread.start()
            running += 1
        if all(task["state"] in JOB_TERMINAL for task in job["tasks"]) and not threads:
            break
        # the launcher's heartbeat: however long a task runs, the last write in this directory
        # says when this process was last alive, which the tick reads once it is gone
        try:
            os.utime(job_dir / "job.json")
        except OSError:
            pass
        time.sleep(JOB_TICK)
    if job.get("finished_at") and job.get("card_sent"):
        log(f"job {job['job_id']}: already finished; card already sent")
        orch.stop_scope(job.get("scope"), log, wait=False)
        return 1 if any(task["state"] in JOB_UNDELIVERED for task in job["tasks"]) else 0
    job["finished_at"] = time.time()
    save()
    undelivered = [task for task in job["tasks"] if task["state"] in JOB_UNDELIVERED]
    # a task the owner stopped was ended on purpose: it delivered nothing, yet needs nobody
    failed = [task for task in undelivered if task["state"] != "stopped"]
    stopped = len(undelivered) - len(failed)
    seat = job.get("seat")
    if failed:
        findings = next((task.get("findings") or "" for task in failed if task.get("findings")), "")
        text = (f"job {job['job_id']}: {len(failed)} task(s) need you"
                + (f", {stopped} stopped" if stopped else "")
                + (f": {findings[:200]}" if findings else ""))
        for task in failed:
            if task.get("findings"):
                log(f"{task['name']} findings:\n{task['findings']}")
        log(f"job {job['job_id']}: Needs you")
        line = (f"{text}. Result: {job_dir / 'log.txt'}. Decide the next step.")
        # the seat that launched the job is there, so the failures are its to act on and the
        # owner is never asked about them -- the same rule a single run's ending obeys.  Under
        # the job's own delivery lock, because a tick may be holding a line this loop left
        # pending on an earlier pass: one of them types it, and only one.
        with run.delivery_lock(job_dir):
            answer = job_hand_back(seat, line, log, job.get("handback_typed"),
                                   lambda mark: mark_job_delivery(job_dir, job, handback_typed=mark)
                                   ) if seat else "gone"
            if not seat:
                log("no seat launched this job, so nothing is sent; "
                    "the result is here and in `ak run status`")
            elif answer == "sent":
                mark_job_delivery(job_dir, job, handback_pending=None, handback_card=None,
                                  handback_typed=None,
                                  card_sent={"kind": "handback", "at": job["finished_at"]})
                orch.stop_scope(job.get("scope"), log, wait=False)
                return 1
            elif answer == "busy":
                mark_job_delivery(job_dir, job, handback_pending=line, handback_card=text)
                log(f"job {job['job_id']}: its seat is not at its prompt; the tick hands it back")
                orch.stop_scope(job.get("scope"), log, wait=False)
                return 1
            elif notify.shaped("needs", text, session=seat,
                               event_id=f"job:{job['job_id']}:{job['finished_at']}") != 0:
                mark_job_delivery(job_dir, job, card_pending=True)
                log("WARN job card was not accepted; retry required")
                orch.stop_scope(job.get("scope"), log, wait=False)
                return 1
            job["card_sent"] = {"kind": "needs", "at": job["finished_at"]}
    else:
        text = (f"job {job['job_id']}: {stopped} task(s) stopped, nobody is needed" if stopped
                else f"job {job['job_id']}: all {len(job['tasks'])} tasks finished")
        log(f"job {job['job_id']}: Done")
        if not seat:
            log("no seat launched this job, so nothing is sent; "
                "the result is here and in `ak run status`")
        elif notify.shaped("done", text, session=seat,
                           event_id=f"job:{job['job_id']}:{job['finished_at']}") != 0:
            job["card_pending"] = True
            save()
            log("WARN job card was not accepted; retry required")
            orch.stop_scope(job.get("scope"), log, wait=False)
            return 1
        job["card_sent"] = {"kind": "done", "at": job["finished_at"]}
    save()
    orch.stop_scope(job.get("scope"), log, wait=False)
    return 1 if undelivered else 0


def spawn_job_bg(job_dir, relaunch=None):
    """Detach the job the way a single run detaches; the child resumes it in the background.

    `relaunch` is the receipt the tick found with its launcher gone.  It must still be that
    receipt under the lock, the relaunch is stamped on it for `job_admission` to count, and
    the child is given the job's seat: a tick from cron has none, and the tasks the job starts
    belong to the seat that launched it.
    """
    job_dir = Path(job_dir)
    log_path = job_dir / "log.txt"
    env = dict(os.environ, **{config.JOB_DIR_ENV: str(job_dir)})
    if relaunch is not None:
        env[config.SESSION_ENV] = relaunch["seat"]
    child = [sys.executable, str(config.REPO / "bin" / "ak"), "run", "resume", job_dir.name]
    with record.recovery_lock(job_dir):
        try:
            job = read_job(job_dir) or {}
            if relaunch is not None:
                if job != relaunch:
                    raise config.Error(f"{job_dir.name} changed while the tick read it")
                job["relaunches"] = [*(job.get("relaunches") or []), time.time()]
            unit = f"agentkit-job-{job_dir.name}"
            if run.scope_is_real(job.get("scope")):
                unit = orch.next_scope_unit(unit)   # an old launcher's scope may linger
            placement = {}
            cap, properties = run.run_scope_limits()
            pid = orch.start_in_slice(
                child, unit, env, log_path,
                log=run.note_in(log_path), target_slice=orch.run_slice_name(),
                properties=properties,
                nice=True, placement=placement)
            # The child waits on this lock before adopting the receipt. The parent can never
            # overwrite a running child's tasks, and reaping sees the child, not its launcher.
            job.update(record.process_owner(pid), scope=placement.get("scope"),
                       scope_reason=placement.get("scope_reason"))
            run.remember_memory_cap(job, placement, cap)
            save_job(job_dir, job)
        except OSError as exc:
            raise config.Error(f"could not launch the job: {exc}") from exc
    print(job_dir.name)
    print(job_dir / "job.json")
    return 0


def cmd_job_resume(argv):
    """Restart an interrupted job: finished tasks keep their result, the rest start again."""
    background = "--bg" in argv
    argv = [arg for arg in argv if arg != "--bg"]
    # `--rounds` is a single-run option; a job keeps each task's own budget, and one over
    # the rule is refused here exactly as a run's is
    if len(argv) >= 3 and argv[1] == "--rounds":
        if not (len(argv) == 3 and argv[2].isdigit() and int(argv[2]) > 0):
            raise config.Error("usage: ak run resume ID [--rounds N] [--bg]")
        refusal = taskfile.rounds_refusal(argv[2], "--rounds")
        if refusal:
            raise config.Error(refusal)
        argv = [argv[0]]
    if len(argv) != 1 or Path(argv[0]).name != argv[0] or argv[0] in (".", ".."):
        raise config.Error("usage: ak run resume ID [--rounds N] [--bg]")
    job_dir = config.JOBS / argv[0]
    if not (job_dir / "job.json").exists():
        return None
    # Read under the handoff lock so a `--bg` child never decides on a receipt its
    # launcher is still writing: the parent holds this lock across Popen and its pid
    # save, and the child adopts the receipt under it on its first tick.
    with record.recovery_lock(job_dir):
        job = read_job(job_dir)
    if not job or not isinstance(job.get("tasks"), list):
        raise config.Error(f"no resumable job: {argv[0]} (looked in {config.JOBS})")
    box.check()
    try:
        launcher_alive = not job.get("finished_at") and bool(record.process_active(job))
    except (TypeError, ValueError, AttributeError, OSError):
        launcher_alive = False  # an old receipt with no pid to check is resumable, not live
    own_child = (launcher_alive and os.environ.get(config.JOB_DIR_ENV) == str(job_dir)
                 and job.get("pid") == os.getpid())
    if launcher_alive and not own_child:
        raise config.Error(f"{argv[0]} is still running as pid {job['pid']}")
    if background:
        return spawn_job_bg(job_dir)
    if all(task["state"] in JOB_TERMINAL for task in job["tasks"]):
        job_block = job_block_line(job)
        print(f"{job_block} (already finished)")
        return 1 if any(task["state"] in JOB_UNDELIVERED for task in job["tasks"]) else 0
    # A task that names no repo inherits the checkout the job was launched from, and neither a
    # tick from cron nor a detached child starts there: the job goes back to it first.
    if job.get("cwd") and Path(job["cwd"]).is_dir():
        os.chdir(job["cwd"])
    cfg = config.load()
    to_file = os.environ.get(config.JOB_DIR_ENV) != str(job_dir)
    # Finished tasks keep their result with their run and ladder flags intact. Anything
    # running without a live worker is left running: the loop adopts its kept run in a
    # worker, resuming it through the existing run resume, so no branch runs twice. Only
    # tasks that never started are re-derived here; unstarted tasks start under the same
    # rules as a fresh job.
    for task in job["tasks"]:
        if task["state"] in (*JOB_TERMINAL, "running", "waiting"):
            continue
        task["state"] = "queued"
    save_job(job_dir, job)
    return run_job_loop(cfg, job_dir, job, to_file=to_file)
