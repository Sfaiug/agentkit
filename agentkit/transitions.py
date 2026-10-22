"""A run's record between steps: the words it carries and when they move.

The state words a record holds (`going`, `unfinished`, `queued`, `delivery`), the
history a run starts and finishes with the sizes of its change, the pass a review
saved and when it is void, the parks (exhausted, errored, waiting on a conflict)
with their retry ladders, which run supersedes another, and the rounds a change has
spent across its runs and may still spend.
"""

from bisect import bisect_left
from collections import Counter
import json
import os
import re
import tempfile
import time
from itertools import accumulate
from pathlib import Path

from . import config, gitcall, history, record as run_record, task as taskfile, turns
from .harness import load as harness_plugin


RESUME_VISIBLE = 3600           # ak run status names a mid-turn resume in the age column for this long


TURN_ROLES = ("executor", "fixer", "reviewer")   # the steps that are a model's turn to continue


def stall_summary(state):
    """`stalled 2× (done-when: bash tests/smoke.sh), recovered` for a running run with stalls."""
    stalls = state.get("stalls") or []
    if state.get("state") != "running" or not stalls:
        return ""
    step = (stalls[-1].get("step") or "").strip()
    return f"stalled {len(stalls)}× ({step}), recovered" if step else f"stalled {len(stalls)}×, recovered"


def review_providers(cfg, executor, reviewer):
    """The (executor, reviewer) providers.  Any reviewer may review any executor --
    another model is only preferred, by reviewer_order, never required."""
    executed = config.model(cfg, executor) if executor else None
    reviewed = config.model(cfg, reviewer)
    return (executed["provider"] if executed else None), reviewed["provider"]


def review_pass(state, cfg):
    """A verdict alone (including a legacy PASS) is not evidence of a successful review."""
    evidence = state.get("review")
    if (state.get("review_pr") and state.get("own_pr") and isinstance(evidence, dict)
            and evidence.get("skipped")):
        # the seat's own wording, its review skipped for exactly the commit it was judged on
        return (state.get("verdict") == "PASS" and evidence.get("verdict") == "PASS"
                and all(evidence.get(key) for key in ("head_sha", "tree_sha")))
    if state.get("verdict") != "PASS" or not isinstance(evidence, dict):
        return False
    if state.get("repo") and not all(evidence.get(key) for key in ("head_sha", "tree_sha")):
        return False
    if (evidence.get("returncode") != 0 or evidence.get("verdict") != "PASS"
            # a reviewed PR whose repository declares no suite ran nothing: None, not True
            or not (evidence.get("done_when") is True
                    or (state.get("review_pr") and evidence.get("done_when", False) is None))
            or evidence.get("executor") != state.get("executor")
            or not evidence.get("reviewer") or evidence["reviewer"] != state.get("reviewer")
            or not evidence.get("reviewer_provider")):
        return False
    if not state.get("executor"):
        if not state.get("review_pr") or evidence.get("executor_provider") is not None:
            return False
    elif not evidence.get("executor_provider"):
        return False
    try:
        providers = review_providers(cfg, state.get("executor"), state["reviewer"])
    except config.Error:
        return False
    if providers != (evidence.get("executor_provider"), evidence["reviewer_provider"]):
        return False
    if state.get("own_pr"):
        own = state.get("own_orchestrator")
        if not own:
            return False
        try:
            review_providers(cfg, own, state["reviewer"])
        except config.Error:
            return False
    return True


def invalidate_saved_pass(state, cfg, log):
    """Recover old verdicts by reviewing the saved work, even if its task rounds are spent."""
    if state.get("verdict") != "PASS" or review_pass(state, cfg):
        return
    log("WARN saved PASS lacks eligible review or commit verification evidence; reviewing again")
    entries = state["round_summaries"]
    rnd = len(entries) + 1
    state.update(verdict=None, review=None,
                 review_pending={"round": rnd, "summary": entries[-1]["summary"] if entries else ""},
                 rounds=max(state["rounds"], rnd))


def delivered(state):
    """Whether the run delivered its change: merged, or found it not needed."""
    return bool(state.get("merged") or state.get("state") == "not_needed")


def stands_on_dependency(state):
    """Why a record from before `after:` went cannot go on, or "" when it can.

    Its branch was to be cut from, or still stands on, a dependency's passed tip: the
    reviewed diff leaves that dependency's commits out, so landing would deliver them
    unreviewed, and replaying them after the dependency's squash conflicts.  Once
    integrated onto the target the branch stands on its own commits and goes on.
    """
    after = state.get("from_pass")
    if not isinstance(after, dict) or state.get("base_sha") not in (None, after.get("tip")):
        return ""
    dep, branch = after.get("task"), state.get("branch")
    if not branch:
        # never started: there is no branch to go on from, only the task to launch again
        return (f"this run was to start from {dep}'s passed work, which `after:` no longer "
                f"waits for; once that has merged, launch its task again")
    return (f"this branch stands on {dep}'s passed work, which `after:` no longer "
            f"waits for; once that has merged, relaunch with `from: {branch}`")


def history_start(state, log=None):
    """Publish the launch receipt without making SQLite part of run correctness.

    A test suite's run -- launched under the suites' notify sink, which run.json keeps -- is
    never recorded: every later write finds no row.  The row names the model the launching
    seat's orchestrator runs.
    """
    if state.get("notify_sink"):
        return
    session = launched_session(state)
    record = config.session_records().get(session) if session else None
    history.start_run(state.get("run_id"), repo=state.get("repo"),
                      executor=state.get("executor"), reviewer=state.get("reviewer"),
                      rounds_used=len(state.get("round_summaries") or []),
                      started_at=state.get("started_at"),
                      session=session, task_words=state.get("task_words"),
                      task_points=state.get("task_points"),
                      task_checks=state.get("task_checks"),
                      orchestrator=record.get("orchestrator") if record else None,
                      change=change_name(state), log=log)


def changed_files(state):
    """Files the run changed against its base, or None when that cannot be read.

    Best effort for the history row: a scratch run has no base. A worktree that is
    gone -- collected on delivery, or never built -- is diffed from the record
    instead: the delivery sha, else the reviewed head, names the same tip the
    worktree's HEAD held, and the objects outlive the branch that pointed at them.
    """
    try:
        wt, base = state.get("worktree"), state.get("base_sha")
        if not wt or not base:
            return None
        if Path(wt).is_dir():
            out = gitcall.git(Path(wt), "diff", "--name-only", "-z", "--no-renames",
                      f"{base}...HEAD", check=False)
        else:
            review = state.get("review")
            tip = state.get("delivery_sha") or (review.get("head_sha") if isinstance(review, dict)
                                                else None)
            repo = state.get("repo")
            if not tip or not repo:
                return None
            out = gitcall.git(Path(repo), "diff", "--name-only", "-z", "--no-renames",
                      f"{base}...{tip}", check=False)
    except (config.Error, OSError, ValueError, TypeError, AttributeError):
        return None
    return [found for found in out.split("\0") if found]


def diff_lines(repo, base, head="HEAD", added_only=False):
    """Added plus deleted text lines, excluding files Git marks linguist-generated; with
    `added_only`, the added lines alone, what a reviewer reads: nothing deleted counts.

    The diff runs from where `head` left `base`, the target it lands on, and every file reads
    its attributes at `base`, so a change cannot leave its own lines out by marking them
    generated: a path is marked by a change of its own that lands first.  NUL records
    preserve unusual filenames and rename pairs.
    """
    total = 0
    for selector in ("d", *(() if added_only else ("D",))):
        parts = iter(gitcall.git(repo, "diff", "--numstat", "-z", "--find-renames",
                         f"--diff-filter={selector}", f"{base}...{head}").split("\0"))
        changes = []
        for entry in parts:
            if not entry:
                continue
            added, deleted, name = entry.split("\t", 2)
            if not name:
                next(parts)  # the old name; a renamed file counts under its new one
                name = next(parts)
            if added != "-":
                changes.append((name, int(added) if added_only else int(added) + int(deleted)))
        generated = _generated(repo, base, [name for name, _ in changes])
        total += sum(lines for name, lines in changes if name not in generated)
    return total


def size_base(state):
    """What a run's size is counted against (`diff_lines`): the target's tip it recorded, whose
    attributes say which files are generated, else its base, for a run that recorded none."""
    return state.get("target_sha") or state.get("base_sha")


def _generated(repo, source, names):
    """Which of `names` Git marks linguist-generated in `source`'s tree."""
    if not names:
        return set()
    # Older Git has no check-attr --source; a private index reads the same tree.
    with tempfile.TemporaryDirectory(dir=config.TMP) as tmp:
        index = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        gitcall.git(repo, "read-tree", source, env=index)
        attrs = gitcall.git(repo, "check-attr", "--cached", "-z", "linguist-generated",
                    "--", *names, env=index).split("\0")[2::3]
    if len(attrs) != len(names):
        raise config.Error("git did not report generated attributes for the PR diff")
    return {name for name, attr in zip(names, attrs) if attr.lower() in ("set", "true")}


MOVED_BLOCK = 20    # alphanumeric characters a moved block holds at least, as git's own
                    # moved-line detection (--color-moved) asks before it calls lines moved


def first_review_refusal(what, lines, carried=0):
    """One sentence when `what` (a pull request, a task's change) adds more lines than a first
    review takes at once (`task.MAX_PR_LINES`), else None: `lines` as `diff_lines` counts the
    added ones, less `carried`, the ones `carried_lines` found moved unchanged from lines the
    diff deletes -- what a reviewer reads; nothing deleted counts."""
    if lines - carried <= taskfile.MAX_PR_LINES:
        return None
    moved = f", {carried} of them moved unchanged from lines it deletes" if carried else ""
    return (f"{what} adds {lines} lines{moved} (generated files aside; deletions never "
            f"count): a first review takes at most {taskfile.MAX_PR_LINES}; split it")


def carried_lines(repo, base, head="HEAD"):
    """Added lines a reviewer need not read: the blocks moved unchanged, whitespace aside, from
    lines the same diff deletes -- a run of added lines reading as a run of deleted lines of one
    file, each deleted line paired once, the block holding at least MOVED_BLOCK alphanumeric
    characters -- so a new blank line or brace that reads as a deleted one is not moved, and a
    module split across files adds what its new lines come to.  Generated files are left out,
    as `diff_lines` leaves them out."""
    return reviewed_lines(repo, base, head)[1]


def reviewed_lines(repo, base, head="HEAD"):
    """(the lines a diff adds that a reviewer reads, each as its text with whitespace collapsed,
    counted; how many added lines it carries, `carried_lines`): every added line, generated
    files aside, as `diff_lines` counts them, less the carried ones, so what two pull requests
    share and each one's size are read off the same lines."""
    # a submodule reads as its commit line: diff_lines never counts its insides
    diff = gitcall.git(repo, *gitcall.patch_args("diff", f"{base}...{head}"), check=False)
    added, deleted = {}, {}
    for old, new, lines in gitcall.patch_files(diff):
        if new:
            added[new] = [" ".join(line[1:].split()) for line in lines if line[:1] == "+"]
        if old:
            deleted[old] = [" ".join(line[1:].split()) for line in lines if line[:1] == "-"]
    skip_new = _generated(repo, base, sorted(added))
    skip_old = _generated(repo, base, sorted(deleted))
    gone = {name: lines for name, lines in deleted.items() if name not in skip_old}
    # each deleted position is indexed by the run of lines from it that first reaches
    # MOVED_BLOCK alphanumerics: an added line starting no such run (a lone brace, a blank)
    # matches nothing, and an added block takes the first deleted block under its key not yet
    # paired, each key's list consumed in order, so the walk grows with the diff's size, never
    # with its copies squared
    where = {}
    for name, lines in gone.items():
        for at, key in enumerate(_windows(lines)):
            if key:
                where.setdefault(key, []).append((name, at))
    used = {name: set() for name in gone}
    cursor = {}     # how far each key's deleted positions are consumed
    read, carried = Counter(), 0
    for name, lines in added.items():
        if name in skip_new:
            continue
        keys = _windows(lines)
        i = 0
        while i < len(lines):
            key, length = keys[i], 0
            candidates = where.get(key, ()) if key else ()
            at = cursor.get(key, 0)
            while at < len(candidates):
                file, start = candidates[at]
                source, held, length = gone[file], used[file], 0
                while (i + length < len(lines) and start + length < len(source)
                       and start + length not in held
                       and source[start + length] == lines[i + length]):
                    length += 1
                at += 1
                if length >= len(key):
                    used[file].update(range(start, start + length))
                    break
                length = 0      # a deleted block paired already, or cut by one: never again
            if key:
                cursor[key] = at
            if length:
                carried += length
                i += length
            else:
                read[lines[i]] += 1
                i += 1
    return read, carried


REPLACED_WITHIN = 14 * 86400    # a pull request that failed at its budget this long ago still
                                # charges the one that re-adds its lines


def budget_failed_reviews(repo, exclude=None):
    """The pull requests of that repository whose review spent the budget, counted
    across their runs (`rounds_spent_elsewhere`), none of which merged, as (url, `size_base`,
    head) of each run of them that ended `fail` within `REPLACED_WITHIN`: what a replacement
    inherits rounds from.  The run itself (`exclude`) counts for nothing."""
    found, merged = [], set()
    for run_dir in run_record.run_dirs():
        if exclude is not None and run_dir.name == Path(exclude).name:
            continue
        state = run_record.read_state(run_dir)
        if not state:
            continue
        if state.get("merged"):
            # a task run keeps its pull request in `pr`, a review in `review_pr`
            merged |= {pr_key(state.get("pr")), pr_key(state.get("review_pr"))}
        elif (state.get("review_pr") and state.get("state") == "fail"
                and same_repo(state.get("repo"), repo) and size_base(state) and state.get("head_sha")
                and time.time() - (state.get("finished_at") or 0) <= REPLACED_WITHIN):
            found.append((state["review_pr"], size_base(state), state["head_sha"]))
    return [(url, base, head) for url, base, head in found if pr_key(url) not in merged
            and rounds_spent_elsewhere(pr=url, exclude=exclude)[0] >= taskfile.TASK_MAX_ROUNDS]


def replacement_refusal(repo, base, head, number, counted, exclude=None):
    """Why a pull request's first review is refused as a replacement, else None: more than half
    of the lines it adds that a reviewer reads (`reviewed_lines`) and that hold a letter or digit
    were added by a pull request whose review failed at the budget (`budget_failed_reviews`), and
    it is no real split of that one: its `counted` lines, as the size ceiling counts them, are
    more than half of that one's, counted alike.  It inherits the rounds that were spent, which
    is all of them.  A blank line or a lone brace, which any two changes share, charges nothing;
    a redesign adds lines of its own and passes; a split takes a part under half the failed
    one's size and passes.  A failed pull request whose commits git no longer holds is skipped:
    nothing to compare; a git that never answered stops the gate."""
    mine = Counter({text: n for text, n in reviewed_lines(repo, base, head)[0].items()
                    if any(map(str.isalnum, text))})
    if not mine:
        return None
    written, worst = sum(mine.values()), None
    for url, their_base, their_head in budget_failed_reviews(repo, exclude):
        if not all(gitcall.git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}", check=False)
                   for sha in (their_base, their_head)):
            continue
        theirs = reviewed_lines(repo, their_base, their_head)[0]
        shared, size = sum((mine & theirs).values()), sum(theirs.values())
        if shared * 2 > written and counted * 2 > size and (worst is None or shared > worst[1]):
            worst = (url, shared, size)
    if worst is None:
        return None
    url, shared, size = worst
    return (f"PR #{number} re-adds {shared} of its {written} lines holding a letter or digit from {url}, "
            f"whose review failed after {taskfile.TASK_MAX_ROUNDS} rounds; a replacement inherits them: "
            f"split it into parts under {size // 2 + 1} lines, or redesign it")


def _windows(lines):
    """For each position in `lines`, the run of lines from it that first holds MOVED_BLOCK
    alphanumeric characters, as a tuple, or None where the lines end first or the line itself
    holds no letter or digit: what a moved block starting there must read as, whole.  A run
    of punctuation-only lines (a maze, a banner, blank lines) builds no window of its own,
    however long it runs."""
    counts = [sum(map(str.isalnum, line)) for line in lines]     # no frame per character
    totals = list(accumulate(counts, initial=0))                 # alphanumerics before each line
    ends = [bisect_left(totals, before + MOVED_BLOCK) for before in totals[:-1]]
    return [tuple(lines[at:end]) if counts[at] and end <= len(lines) else None
            for at, end in enumerate(ends)]


def history_finish(state, log=None):
    """Publish a terminal receipt and close the step this process was running, if any."""
    now = state.get("finished_at") or time.time()
    history.close_step(state.get("run_id"), now, log=log)
    files = changed_files(state)
    # git is read from the run's worktree while it exists, else from its repository
    wt = state.get("worktree")
    try:
        present = bool(wt) and Path(wt).is_dir()
    except (OSError, TypeError):
        present = False
    repo = wt if present else state.get("repo")
    size, against = None, size_base(state)
    if state.get("merged") and against:
        try:
            review = state.get("review") or {}
            head = state.get("delivery_sha") or review.get("head_sha") or ("HEAD" if present else None)
            if repo and head:
                size = diff_lines(repo, against, head)
        except (config.Error, OSError, ValueError, TypeError, AttributeError, StopIteration):
            pass  # best-effort history must never change the merge's outcome
    # the AGENTS.md its workers were handed, measured as the ceiling measures it
    rules = None
    if repo and state.get("base_sha"):
        try:
            # no file, or a link, hands its workers no rules: 0, where a failed read stays unknown
            rules = len(gitcall.rules_bytes(repo, state["base_sha"]) or b"")
        except (config.Error, OSError, ValueError, TypeError):
            pass
    history.finish_run(state.get("run_id"), repo=state.get("repo"),
                       executor=state.get("executor"), reviewer=state.get("reviewer"),
                       rounds_used=len(state.get("round_summaries") or []),
                       final_state=state.get("state"), verdict=state.get("verdict"),
                       started_at=state.get("started_at"), finished_at=now,
                       session=launched_session(state), peak_rss_mb=state.get("peak_rss_mb"),
                       task_files=json.dumps(files) if files is not None else None,
                       changed_lines=size, rules_bytes=rules,
                       own_orchestrator=state.get("own_orchestrator"),
                       own_orchestrator_effort=state.get("own_orchestrator_effort"), log=log)


def history_role_tokens(run_id, role, out, log=None, cfg=None, model=None):
    """Copy token counts from where the model's harness keeps them, when it reports them at all.

    None of the turns reporting leaves the column unknown, never zero.  A model the config
    cannot place is read the default way, from its event log.
    """
    try:
        harness = config.model(cfg, model)["harness"] if cfg is not None and model else None
    except (config.Error, KeyError, TypeError, AttributeError):
        harness = None
    out = Path(out)
    paths = [out, *sorted(out.parent.glob(f"{out.name}-retry*"))]
    values = [harness_plugin(harness).tokens(path) for path in paths]
    values = [value for value in values if value is not None]
    if not values:
        return
    history.add_tokens(run_id, role, sum(values), log=log)


def park_exhausted(state, exc):
    """Only a quota stop waits on a window, whether in a round or during delivery."""
    state["state"] = "exhausted"
    if exc:
        state["error"] = str(exc)
    if isinstance(exc, turns.QuotaDry):
        state["quota_dry"] = True
    else:
        state.pop("quota_dry", None)
        state.pop("refusal_retry", None)


def over_lineage(state, run_dir, n_rounds):
    """Refuse a `--rounds` above what the change has left across its runs."""
    cap = lineage_cap(state, run_dir)
    if n_rounds > cap:
        raise config.Error(f"--rounds {n_rounds} is over this change's budget: {cap} of "
                           f"{taskfile.TASK_MAX_ROUNDS} rounds across its runs; split or redesign the task")


def failed_at_budget(state):
    """A FAIL that ran out of rounds rather than out of work, so more rounds carry it on.

    Deliberately not part of `needs_recovery`: nothing was interrupted here, so this is no
    recovery decision for the menu to raise, for the seat to be told about or for `announce`
    to swallow the finished-run notice over.  An explicit `--rounds` above the saved budget,
    and no higher than `taskfile.TASK_MAX_ROUNDS`, continues it and nothing else does -- see
    `cmd_resume`.
    """
    return (state.get("state") == "fail" and not state.get("review_pr")
            and bool(state.get("worktree")) and Path(state["worktree"]).is_dir()
            and len(state.get("round_summaries") or []) >= (state.get("rounds") or 0) > 0)


def _integration_fail_guards(state, run_dir=None):
    """What every FAIL resumed past the merge shares: it failed there, not in the rounds.

    A run the tick parked `waiting` off such a FAIL shares it too: the branch, base
    and budget still identify the saved work, and the merge note still names why.

    The branch, base and budget identify the saved work, `merge_note` names the delivery
    failure and the log carries it.  Judged or not, rounds left or not, is the caller's
    distinction -- see `integration_note` and `judged_in_integration`.
    """
    if state.get("state") not in ("fail", "waiting") or state.get("review_pr"):
        return False
    if not state.get("worktree") or not Path(state["worktree"]).is_dir():
        return False
    for key in ("branch", "base", "base_sha", "rounds"):
        if not state.get(key):
            return False
    if not state.get("merge_note"):
        return False
    if run_dir is not None:
        try:
            if "not merged:" not in (Path(run_dir) / "log.txt").read_text(errors="replace"):
                return False
        except OSError:
            return False
    return True


def integration_note(state, run_dir=None):
    """A FAIL whose last note came from integration rather than from the rounds.

    The branch is saved with rounds possibly left, but origin moved under it or the rebase
    could not land.  A last round that recorded a judged failure -- a `FAIL` verdict with a
    done-when value and the commit it judged -- is not one of these, however its delivery
    note reads: only the reviewer can clear that tree.  Nor is a last review that failed
    it without being a round -- after a conflict or a final-check fix -- whose older PASS
    of the same commit a resume would otherwise put back.  The old code's synthetic marker
    (`FAIL` with no done-when review and no commit) judged nothing, so it stays eligible.
    Budget is not consulted here: classifying the failure is independent of the budget
    needed to continue it -- see `failed_in_integration` and `cmd_resume`.
    """
    if not _integration_fail_guards(state, run_dir):
        return False
    summaries = state.get("round_summaries") or []
    review = state.get("review") if isinstance(state.get("review"), dict) else {}
    for last in (review, summaries[-1] if summaries else {}):
        if (last.get("verdict") == "FAIL" and last.get("done_when") is not None
                and ("head_sha" in last or "tree_sha" in last)):
            return False
    return True


def failed_in_integration(state, run_dir=None):
    """An integration FAIL with rounds left, so a resume needs no larger `--rounds`.

    Unlike `failed_at_budget` the run continues with the rounds it has left.
    """
    return (integration_note(state, run_dir)
            and len(state.get("round_summaries") or []) < (state.get("rounds") or 0))


def judged_in_integration(state, run_dir=None):
    """A judged FAIL after the rebase with rounds left: a fixer round carries it on.

    Unlike `failed_in_integration` the last round judged the tree -- a `FAIL` verdict with
    a done-when value and the commit it judged -- so the resume spends a fixer round on the
    reviewer's findings, then review, then the merge.  The delivery note still says the last
    word came from integration (`merge_note` set, `not merged:` in the log).  At its budget
    this is a `failed_at_budget` resume with `--rounds`, never this path.
    """
    if not _integration_fail_guards(state, run_dir):
        return False
    summaries = state.get("round_summaries") or []
    if len(summaries) >= (state.get("rounds") or 0):
        return False
    if not summaries:
        return False
    last = summaries[-1]
    return (last.get("verdict") == "FAIL" and last.get("done_when") is not None
            and ("head_sha" in last or "tree_sha" in last))


def continue_line(state, run_dir=None):
    """The way on from a FAIL at its round budget, an integration FAIL below it,
    a judged FAIL after the rebase with rounds left, a reviewer that never answered,
    or a run parked `stalled`."""
    if state.get("state") == "stalled" and state.get("run_id"):
        return f"continue: ak run resume {state['run_id']}"
    if not state.get("run_id"):
        return ""
    # Only the no-verdict stop names its resume here: a quota-dry stop inside
    # review leaves the same `review_pending` behind, but its row already says which
    # window it waits for and the tick resumes it by itself.
    if (state.get("state") == "exhausted" and state.get("review_pending")
            and "gave no verdict twice" in (state.get("error") or "")):
        return f"continue: ak run resume {state['run_id']}"
    if failed_at_budget(state):
        # up to the change's budget across its runs and no further: past it the task is
        # split or redesigned instead
        cap = lineage_cap(state, run_dir or config.RUNS / state["run_id"])
        return (f"continue: ak run resume {state['run_id']} --rounds {cap}"
                if state["rounds"] < cap else "")
    if failed_in_integration(state, run_dir):
        return f"continue: ak run resume {state['run_id']}"
    if judged_in_integration(state, run_dir):
        return f"continue: ak run resume {state['run_id']}"
    return ""


def report_config(cfg=None):
    """Live reports use the run's config; standalone reports tolerate a broken config file.

    Without readable model policy a report cannot establish PASS, but it must still leave
    the original failure and recovery instructions instead of failing while reporting it.
    """
    if cfg is not None:
        return cfg
    try:
        return config.load()
    except config.Error:
        return {"models": {}, "providers": {}}


def delivery(state, cfg=None):
    """The review verdict and the delivery outcome are separate facts.

    `not merged` is a repository run's answer and only a repository run's: a run with no repo
    has no branch to merge, and its workspace is where the work went, so it is `delivered`.
    """
    if state.get("state") == "not_needed":
        return f"not needed: {state['not_needed']}"
    if state.get("state") == "waiting":
        return f"WAITING: {state.get('merge_note') or state.get('error') or 'delivery pending'}"
    cfg = report_config(cfg)
    if not review_pass(state, cfg) or state.get("state") in (
            "error", "fail", "interrupted", "exhausted", "blocked", "waiting_login",
            "stopped"):
        return "FAIL"
    if state.get("scratch"):
        return "PASS, delivered"
    if state.get("merged"):
        return "PASS, merged"
    reason = state.get("merge_note")
    if not reason:
        reason = ("review only" if state.get("review_pr") else
                  "--no-merge" if state.get("no_merge") else "delivery did not finish")
    return f"PASS, not merged: {reason}"


def run_for_pr(url):
    """(run_dir, state) of the run that opened that PR, or (None, None)."""
    for run_dir in run_record.run_dirs():
        state = run_record.read_state(run_dir)
        if state and state.get("pr") == url:
            return run_dir, state
    return None, None


def first_started(state):
    """When this run's work was first started: its own start, or, for a run started again after
    a park (`leases.restart`), its first attempt's, which every restart carries on."""
    return state.get("first_started_at") or state.get("started_at") or 0


def first_queued(state):
    """Where this run stands in the slot queue: when it queued, or, for a run started again after
    a park (`leases.restart`), when its first attempt queued, which every restart carries on.  Not
    that attempt's start: its admission may have waited behind runs queued after it."""
    return state.get("first_queued_at") or state.get("queued_at") or state.get("started_at") or 0


def seat_runs(name):
    """Every run that seat launched which stopping it stops (`stop.stop_owned_runs`), each one
    `ak run stop` takes: one not ended, an `error` still waiting on its owner or on the tick's
    retry, and one stopped to wait on an older run's change (`leases.parked`)."""
    from . import leases
    try:
        dirs = run_record.run_dirs()
    except OSError:
        return []
    found = []
    for run_dir in dirs:
        try:
            state = run_record.read_state(run_dir)
            word = state and state.get("state")
            if (state and launched_session(state) == name
                    and (word not in run_record.ENDED or leases.parked(state)
                         or word == "error" and (unfinished(state) or going(state)))):
                found.append(run_dir)
        except (OSError, ValueError, config.Error):
            continue
    return found


def launched_session(state, resolved=None):
    """The seat this run was launched from, by its name now, or None: it was launched from none.

    `session` is what a run.json written before the field was renamed calls the same thing.  A
    pass over many runs hands each call the same `resolved`, so a seat many runs name is
    resolved once: following a rename reads the seat's record.
    """
    name = state.get("launched_session") or state.get("session")
    if not isinstance(name, str) or not name:
        return None
    if resolved is None:
        return config.resolve_session(name)
    if name not in resolved:
        resolved[name] = config.resolve_session(name)
    return resolved[name]


def runs_by_seat(records):
    """Each seat's runs, (run_dir, state) as `records` has them, under the name it goes by now:
    every seat a run names resolved once (`launched_session`), and runs launched from none, or
    from a name whose renames will not resolve, left out."""
    resolved, mine = {}, {}
    for run_dir, state in records:
        try:
            seat = launched_session(state, resolved)
        except config.Error:
            seat = resolved[state.get("launched_session") or state.get("session")] = None
        if seat is not None:
            mine.setdefault(seat, []).append((run_dir, state))
    return mine


def needs_recovery(state):
    """Work a resume could still carry on.  `blocked` never is: the task itself is wrong.

    A resume leaves `recovery_pending` on the record it starts from, so an attempt that ends
    `blocked` would otherwise be offered for recovery it is refused -- see `cmd_resume`.
    A `stopped` run is a deliberate end, never an accident to offer back. Line
    members belong to the lander even if an earlier attempt left a recovery mark.
    """
    return (not landing_line(state) and
            state.get("state") not in (*run_record.ACTIVE, "pass", "blocked", "stopped", "not_needed") and
            (state.get("state") in ("interrupted", "exhausted", "stalled", "waiting_login") or
             bool(state.get("recovery_pending"))))


def recovery_reason(state):
    return ((state.get("error") if state.get("state") in ("error", "exhausted", "stalled",
                                                          "waiting_login") else None) or
            ("Resume attempt failed; `ak run status` shows the failed checks or review."
             if state.get("state") == "fail" and state.get("recovery_pending") else None) or
            state.get("interruption_reason") or
            state.get("error") or "The run stopped before recording completion.")


def interrupt(state, reason):
    state.update(state="interrupted", interrupted_at=time.time(),
                 interruption_reason=reason, recovery_pending=True)
    # finished_at and the review verdict describe completion, never detection of a dead loop.
    return state


def tick_resumes(state):
    """A dead loop the tick continues itself, so its death is nobody's news.

    The dead-loop pass resumes a run whose loop process is gone in the tick that notices
    it, and puts the record straight back: an interruption a menu look reaped in between
    is one about to be undone, and spending the run's one recovery card on it would tell
    the seat about a death nobody had to answer.  A death the pass has given up on -- the
    third within an hour, which it parks itself -- and a launch that never got as far as a
    worktree are what is left for a person.
    """
    deaths = state.get("deaths") or []
    if deaths and isinstance(deaths[-1], dict) and deaths[-1].get("parked"):
        return False
    # Exactly what the pass itself will carry on, so the two never disagree over one
    # record: without a workspace to go back to there is nothing to continue, and a
    # recorded worktree that has gone is the one it hands back to a person.
    wt = state.get("worktree")
    return bool(wt) and Path(wt).is_dir()


def supersession_index(states):
    """Newest-first replacements per title and per branch: build once, then test runs
    without rescanning.

    `states` is an iterable of states, or `(run_dir, state)` pairs as `run_records`
    yields. Answers `{title: [(finished_when, run_id, display)]}` for merged runs
    with a title, and `{("from", repo, branch): [...]}` for every run relaunched
    `from:` a branch, each with a numeric finish (or start), newest first. Read-only.
    A merged relaunch is also answered under `{("merged-from", repo, branch): [...]}`,
    for the settled question, which only a merged replacement ends.
    """
    index = {}
    for item in states:
        other = item[1] if isinstance(item, (tuple, list)) and len(item) == 2 else item
        if not isinstance(other, dict):
            continue
        when = other.get("finished_at") or other.get("started_at") or 0
        if not isinstance(when, (int, float)) or isinstance(when, bool):
            continue
        title = other.get("title")
        if other.get("merged") and title:
            index.setdefault(title, []).append(
                (when, other.get("run_id"), other.get("run_id") or title))
        if other.get("from"):
            entry = (when, other.get("run_id"), other.get("run_id") or other["from"])
            index.setdefault(("from", other.get("repo"), other["from"]), []).append(entry)
            if other.get("merged"):
                index.setdefault(("merged-from", other.get("repo"), other["from"]),
                                 []).append(entry)
    for entries in index.values():
        entries.sort(key=lambda entry: entry[0], reverse=True)
    return index


def superseded_by(state, records=None, index=None, merged_only=False):
    """The later run that replaced this one, or None. Read-only.

    A `↳` row appears only for a run nobody has replaced: a later merged run of the
    same title supersedes it, and so does a later run relaunched `from:` its branch in
    its repository, whatever that run's own ending -- the orchestrator took the work up
    again, and its title often says `(continued from its branch)`.  `r` names the
    replacement as `superseded by <run id>`.
    A merged run never supersedes itself. `records` is an iterable of states already
    read; when omitted the runs on disk are read once, never written. `index` is a
    `supersession_index` over the same states: pass it when testing many runs, so one
    draw scans the records once instead of once per run per seat. With `merged_only`
    only a replacement that merged counts: a relaunch still running settles nothing.
    """
    title, branch = state.get("title"), state.get("branch")
    if not (title or branch) or state.get("merged"):
        return None
    mine = state.get("finished_at") or state.get("started_at") or 0
    if not isinstance(mine, (int, float)) or isinstance(mine, bool):
        mine = 0
    if index is not None:
        relaunched = ("merged-from" if merged_only else "from",
                      state.get("repo"), branch)
        later = [(when, display) for when, run_id, display in (
                     *index.get(title, ()), *index.get(relaunched, ()))
                 if run_id != state.get("run_id") and when > mine]
        return max(later)[1] if later else None
    found = []
    if records is None:
        from . import menu  # here, not at the top: the menu draws without the loop
        for run_dir in run_record.run_dirs():
            other = run_record.read_state(run_dir)
            if other and not menu.smoke_run(other):
                found.append(other)
    else:
        for item in records:
            other = item[1] if isinstance(item, (tuple, list)) and len(item) == 2 else item
            if isinstance(other, dict):
                found.append(other)
    best, newest = None, mine
    for other in found:
        if merged_only and not other.get("merged"):
            continue
        if not ((title and other.get("merged") and other.get("title") == title) or
                (branch and other.get("from") == branch
                 and other.get("repo") == state.get("repo"))):
            continue
        if other.get("run_id") == state.get("run_id"):
            continue
        when = other.get("finished_at") or other.get("started_at") or 0
        if not isinstance(when, (int, float)) or isinstance(when, bool):
            continue
        if when > newest:
            best, newest = other, when
    return (best.get("run_id") or best.get("title")) if best else None


def is_superseded(state, records=None, index=None, merged_only=False):
    """Whether a later run replaced this one (see `superseded_by`). Read-only."""
    return superseded_by(state, records, index, merged_only) is not None


def settled(state, index=None):
    """Whether an ending is already its orchestrator's: handed back to the seat that launched
    it or waiting for that seat's next quiet prompt, acknowledged, or superseded by later work.

    These are the endings `menu.v5o_needs_look` counts as nobody's question, and as there
    an `exhausted` run the tick cannot resume is no ending: neither a hand-back nor its
    age settles it, only an acknowledgement -- or a later merged run taking the work up,
    which ends the question however the run parked.  `index` is a `supersession_index`;
    without one supersession is not read.
    """
    if state.get("state") == "exhausted":
        return bool(state.get("recovery_acknowledged_at")
                    or (index is not None
                        and is_superseded(state, None, index, merged_only=True)))
    return bool(state.get("handed_back") or state.get("handback_pending")
                or state.get("recovery_acknowledged_at")
                or (index is not None and is_superseded(state, None, index)))


def mark_looked_at(run_dir):
    """Opening a run by number, `ak run status <id>` or `2 acknowledge` marks it looked at.

    Sets `recovery_acknowledged_at` for `fail`, `error` and `pass` as well, so an
    ending under a live seat counts as `needs a look` until it is looked at, then as
    merged-or-gone, never `needs a look` again. A scheduled error is still working,
    like a merge wait: inspecting it does not cancel its retry; `ak run stop` does.
    A PASS still waiting on its merge leaves the menu the same way: looked at is
    looked at. Returns True when it marked.  Through `record`, so a notice's told mark
    written meanwhile stays.
    """
    try:
        with run_record.record(run_dir) as current:
            if (not current or current.get("state") not in run_record.ENDED
                    or current.get("state") == "error" and going(current)
                    or current.get("recovery_acknowledged_at")):
                return False
            current["recovery_acknowledged_at"] = time.time()
            current.pop("error_retry_at", None)
            current.pop("error_retries", None)
    except run_record.Unreadable:
        return False
    return True


def acknowledge(run_dir):
    try:
        with run_record.record(run_dir) as state:
            waiting = state and (needs_recovery(state) or state.get("state") in run_record.FAILED)
            if not waiting or state.get("recovery_acknowledged_at"):
                raise config.Error("the run is no longer waiting for recovery")
            state["recovery_acknowledged_at"] = time.time()
            state.pop("error_retry_at", None)
            state.pop("error_retries", None)
    except run_record.Unreadable:
        raise config.Error("the run is no longer waiting for recovery") from None


ERROR_RETRY_CAP = 3600  # an errored run is retried at most hourly, however long the ladder


def error_retry_delay(retries):
    """How long the tick waits before retry number `retries` of an errored run.

    The loop's own transient ladder first -- the 1, 5, 15, 30 and 60 minutes a
    worker turn waits between attempts -- then hourly, indefinitely.  A provider
    that died under the run is worth another hour's patience every hour; giving
    up is the owner's decision, and he makes it with `ak run stop`.
    """
    if retries < len(turns.TRANSIENT_BACKOFF):
        return turns.TRANSIENT_BACKOFF[retries]
    return ERROR_RETRY_CAP


def schedule_error_retry(state, now=None):
    """Stamp the tick's next retry of this errored run onto its record.

    `error_retries` is the rung already tried, kept across attempts so the ladder
    never restarts: a run that errors again an hour later waits another hour, not
    another minute.  Only the stamp is written here; whether the run can be
    resumed at all is `error_resumable`'s answer, taken before this is called.
    """
    now = time.time() if now is None else now
    retries = state.get("error_retries") or 0
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        retries = 0
    state["error_retries"] = retries
    state["error_retry_at"] = now + error_retry_delay(retries)
    return state


def error_resumable(state, run_dir):
    """Whether an errored run is one a resume could carry on.

    The same checks `resume_run` refuses on, asked before anything is scheduled:
    a worktree that is still there, the keys a resume replays, and -- for a task
    run -- a task that still parses with a done-when.  A job's run is its job's to
    settle, never the tick's.  A run that fails any of the others is parked for a
    person, not for the tick: retrying a task nobody can run would only fail on
    the hour, every hour, saying nothing new.
    """
    if state.get("review_pr"):
        return False  # the watch relaunches the review itself; the run is never resumed
    if state.get("job_id"):
        return False  # its job settles it or reruns it elsewhere; a retry would race that
    wt = state.get("worktree")
    if not wt or not Path(wt).is_dir():
        return False
    keys = (("worktree", "rounds") if state.get("scratch") else
            ("repo", "worktree", "branch", "base", "base_sha", "rounds"))
    if any(not state.get(key) for key in keys):
        return False
    try:
        _, body, _ = taskfile.parse_task(Path(run_dir) / "task.md")
        taskfile.done_when(body, Path(run_dir) / "task.md")
    except (OSError, config.Error):
        return False
    return True


def park_error(run_dir, state, now=None):
    """Schedule the tick's retry for a run that just ended in error, or park it.

    An admitted, resumable error is born scheduled: the status line says when,
    and the seat stays working. Anything else -- a by-hand run, a settled ending,
    a worktree already gone, a task that never parsed -- keeps no stamp, so the
    run reads parked for a person from the start. Stale stamps from an earlier
    episode come off with it: the rung goes with the hour, and a run that is
    resumable again starts a new ladder.
    """
    if tick_admission(state, now=now) and error_resumable(state, run_dir):
        schedule_error_retry(state, now=now)
    else:
        state.pop("error_retry_at", None)
        state.pop("error_retries", None)
    return state


def exhausted_wait(state):
    """What the tick brings back to an `exhausted` run: `window`, `reviewer`, or nothing.

    A quota run waits on a provider window; a run off a dead reviewer -- which carries
    no quota mark, because no window was ever spent -- waits on a reviewer being
    eligible again.  `watch.resume_exhausted` resumes those two by itself and no other:
    rounds spent, a stopped tool or a reviewer stuck without a verdict wait on nobody
    until `ak run resume`, so `going` reads this too, and a run nothing will move keeps
    no seat working.  A run a later merged run replaced waits on neither: the tick
    stands down, marked `replaced`, and the wait is over however the run parked.
    """
    if state.get("state") != "exhausted":
        return ""
    if state.get("replaced"):
        return ""
    if state.get("quota_dry"):
        return "window"
    if reviewer_transport_dead(state.get("error")):
        return "reviewer"
    return ""


def going(state, now=None):
    """Whether the run keeps its seat working while it lasts.

    The `record.GOING` states -- queued, running, waiting, exhausted, stalled,
    waiting_login -- which resume themselves or are already running, plus an
    error the tick will retry. Errors and waits on a target ref need current admission:
    an old stamp cannot keep a seat working after its retry stopped being allowed,
    and an exhausted run keeps one working only while the tick can resume it
    (`exhausted_wait`): one that waits on nobody is his, not going. Line members
    stay going until the lander ends them, and a run stopped to wait on an older run's
    change (`leases.park`) until the tick has started its task again.
    """
    if state.get("state") == "waiting" and (state.get("waiting_on") or {}).get("line"):
        return True  # the line is unfinished work, not an ending with timed recovery
    from . import leases
    if leases.parked(state):
        return True
    if state.get("state") in ("error", "waiting") and not tick_admission(state, now=now):
        return False
    if state.get("state") == "exhausted":
        return bool(exhausted_wait(state))
    if state.get("state") in run_record.GOING:
        return True
    if state.get("state") != "error":
        return False
    at = state.get("error_retry_at")
    return isinstance(at, (int, float)) and not isinstance(at, bool)


def conflict_upstream(state):
    """The `origin/<base>` a rebase conflict was against, from the loop's own words.

    The conflict notes name it -- `the rebase of origin/main conflicted` -- so
    the tick waits on exactly what the loop tripped over.  A note that names
    nothing waits on the run's base, which is what integration rebases onto.
    The capture stops at a `;`: the fixer note ends `... of origin/main; it was
    aborted`, and `origin/main;` is a ref that can never move.
    """
    match = re.search(r"(?:rebase|merge) of ([^\s;]+)", state.get("merge_note") or "")
    if match:
        return match.group(1)
    return f"origin/{state.get('base') or 'main'}"


CONFLICT_NOTE = re.compile(r"conflict|did not finish the (?:rebase|merge)", re.I)


def tick_admission(state, now=None):
    """Why the tick may take up this ending, or nothing if it belongs to a person.

    Line members belong to the lander until they end, however long they wait.
    A telling or acknowledgement settles an ending for good. Only an untold
    ending under a day old, from a session that still exists, is the tick's.
    Following the launch name also keeps a renamed seat's runs with that seat.
    """
    if landing_line(state):
        return "in line to land"
    if any(state.get(key) for key in (
            "handed_back", "recovery_notified", "recovery_acknowledged_at")):
        return ""
    now = time.time() if now is None else now
    ended = state.get("finished_at")
    if (not isinstance(ended, (int, float)) or isinstance(ended, bool)
            or not 0 <= now - ended < 86400):
        return ""
    try:
        seat = launched_session(state)
        if not seat or not config.session_path(seat).is_file():
            return ""
    except config.Error:
        return ""
    return (f"session {seat} exists; ending under 24h old; "
            "not handed back, carded or acknowledged")


def parkable_conflict(state, run_dir=None, now=None):
    """Whether this FAIL waits on main rather than on a person.

    A rebase or merge the loop could not land -- conflicted, or a fixer that did
    not finish it -- with rounds still to spend and the saved branch behind it.
    The work is reviewed; only main stands in its way, and main keeps moving.  A
    conflict FAIL at its budget is not one of these: more rounds are the owner's
    decision, never the tick's. Only an untold, unacknowledged ending under a
    day old from a session that still exists may be parked: anything the seat
    moved past is history, and a by-hand run waits for a person.  A job's run is
    never parked: its job has already settled that FAIL, and alone decides what next.
    """
    if state.get("job_id"):
        return False
    if not CONFLICT_NOTE.search(state.get("merge_note") or ""):
        return False  # cheap first: most FAILs never reach the log read below
    if len(state.get("round_summaries") or []) >= (state.get("rounds") or 0):
        return False
    if not tick_admission(state, now=now):
        return False
    return _integration_fail_guards(state, run_dir)


def upstream_sha(wt, ref):
    """What `ref` points at on origin now, or None when that cannot be read.

    A fetch first, so a merge to main since the last one moves the answer: the
    tick waits on the next merge, not the last fetch.  A fetch that fails, or a
    ref that will not parse, is not a move -- the waiter keeps waiting, silently,
    exactly as a window that has not refilled.  Only a full oid is an answer:
    `rev-parse` echoes an unresolved rev on stdout before it exits non-zero, and
    reading that echo as a sha would park the run on a move that can never come.
    Either object format counts: sha1 oids are 40 hex chars, sha256 ones 64.
    """
    try:
        if gitcall.fetch(wt, "origin")[0] != 0:
            return None
        sha = gitcall.git(wt, "rev-parse", f"{ref}^{{commit}}", check=False)
    except (config.Error, OSError):
        return None
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", sha or ""):
        return None
    return sha


def landing_line(state):
    """The repository lock named by a waiting line member."""
    return (state.get("waiting_on") or {}).get("line") if state.get("state") == "waiting" else None


def unfinished(state, records=None, index=None):
    """Runs that still own an active seat or await an explicit recovery decision.

    A run a later merged run replaced is neither: its work is done, elsewhere.
    `records` is an iterable of states already read, `index` a `supersession_index`
    over them; without either supersession is not read.
    """
    if state.get("state") in run_record.ACTIVE:
        return True
    if not (needs_recovery(state) and not state.get("recovery_acknowledged_at")):
        return False
    if records is None and index is None:
        return True
    return not is_superseded(state, records, index, merged_only=True)


def queued(run_dir):
    """The background launch receipt, possibly already holding its slot."""
    try:
        with run_record.recovery_lock(run_dir):
            state = run_record.read_state(run_dir)
            return (state.get("state") == "queued" or
                    (state.get("state") == "running" and state.get("pid") == os.getpid()
                     and state.get("slot_waiting") is False))
    except (OSError, ValueError, AttributeError):
        return False


PR_PARTS = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$")


def pr_key(url):
    """One pull request's identity, however its URL was spelled: owner and repository
    case-folded, a trailing slash ignored; None for no pull request URL."""
    found = PR_PARTS.match((url or "").strip()) if isinstance(url, str) else None
    return (found.group(1).lower(), found.group(2).lower(), found.group(3)) if found else None


def same_repo(a, b):
    """Whether two recorded checkouts name the same repository."""
    try:
        return bool(a) and bool(b) and Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def change_of(state):
    """The change a run belongs to: the id it inherited at a `from:` launch, else its own."""
    return state.get("change") or state.get("run_id")


def change_name(state):
    """The name a run's change is recorded under: the pull request it reviews, as
    `owner/repo#n` however its URL was spelled (`pr_key`), else its change (`change_of`)."""
    key = pr_key(state.get("review_pr"))
    return f"{key[0]}/{key[1]}#{key[2]}" if key else change_of(state)


def change_on(branch, repo, exclude=None):
    """The change a launch `from:` that branch continues: the change of the newest run of that
    repository that ak cut the branch for and whose branch is still there, or None when the
    name is free and the launch is a new change.  A branch name is not a change: a merge, a
    stop without `--keep` or a session's end takes the branch (`record.branch_gone`) and the
    next task of that title gets the name back, and a run working in the repository itself
    (`--no-worktree`) is on whatever branch was checked out and owns none."""
    owner = None
    for run_dir in run_record.run_dirs():
        if exclude is not None and run_dir.name == Path(exclude).name:
            continue
        state = run_record.read_state(run_dir)
        if (state and state.get("branch") == branch and state.get("worktree") and state.get("repo")
                and Path(state["worktree"]) != Path(state["repo"]) and same_repo(state["repo"], repo)
                and not run_record.branch_gone(state)
                and (owner is None or run_dir.name > owner["run_id"])):
            owner = {**state, "run_id": run_dir.name}
    return change_of(owner) if owner else None


def rounds_spent(state):
    """The review rounds a run spent: those with a verdict recorded (`round_summaries`), and
    the one under way on a run still going -- from its first step (`step_round`, which
    `Loop.step` records as the round begins) or its pending review -- spent the moment it
    starts so no other run of the change takes it too."""
    recorded = len(state.get("round_summaries") or [])
    pending = state.get("review_pending")
    begun = max(state.get("step_round") or 0,
                (pending.get("round") or 0) if isinstance(pending, dict) else 0)
    return recorded + (1 if begun > recorded and going(state) else 0)


def spent_line(spent, runs, what):
    """Why no round is left: the one wording of a spent budget, wherever it is refused."""
    return (f"{spent} review rounds spent on {what} across {runs} run{'s' if runs != 1 else ''}: "
            f"{taskfile.TASK_MAX_ROUNDS} per pull request is the budget; split or redesign it")


def rounds_spent_elsewhere(*, pr=None, change=None, exclude=None):
    """(the review rounds other runs spent on that pull request or on that change, how many
    runs spent them): the budget is the change's, not the run's, so a relaunch inherits what
    was spent on it.

    A round counts once its verdict was recorded, or from its start on a run still going
    (`rounds_spent`).  A run is on the change it carries (`change_of`), so every run launched
    `from:` a branch of the change, however far down, owes the rounds of every other; and on
    its pull request, whatever the spelling of its URL.  The run itself (`exclude`) counts
    for nothing.  Read-only.
    """
    counted = [rounds for rounds in map(rounds_spent, runs_on(pr=pr, change=change, exclude=exclude))
               if rounds]
    return sum(counted), len(counted)


def runs_on(*, pr=None, change=None, exclude=None):
    """The records of the runs on that pull request, whatever the spelling of its URL, or on
    that change (`change_of`), but the run `exclude` names."""
    wanted = pr_key(pr)
    for run_dir in run_record.run_dirs():
        if exclude is not None and run_dir.name == Path(exclude).name:
            continue
        state = run_record.read_state(run_dir)
        if state and ((wanted is not None
                       and wanted in (pr_key(state.get("pr")), pr_key(state.get("review_pr"))))
                      or (change is not None and change_of(state) == change)):
            yield state


def change_reviewed(*, pr=None, change=None):
    """Whether a review of that pull request or change handed in its verdict
    (`round_summaries`) on any run of it (`runs_on`): a round under way holds its place in the
    budget (`rounds_spent`), but no reviewer has judged the change yet."""
    return any(state.get("round_summaries") for state in runs_on(pr=pr, change=change))


def round_budget(asked, *, pr=None, change=None, exclude=None, what, own=0):
    """(the rounds this run may still have, None), or (0, why) once the change's budget is
    spent: `asked` less what the other runs (`exclude` names this one) spent on the same pull
    request or change and less this run's `own`, `taskfile.TASK_MAX_ROUNDS` in all.  The one
    reading of the budget: a launch, a resume, the way on from a FAIL and every round as it
    is spent read it here."""
    spent, runs = rounds_spent_elsewhere(pr=pr, change=change, exclude=exclude)
    left = min(asked, taskfile.TASK_MAX_ROUNDS - spent - own)
    if left < 1:
        return 0, spent_line(spent + own, runs + (1 if own else 0), what)
    return left, None


def change_budget(state, run_dir, asked, own=0):
    """`round_budget` for a run's own pull request or change: the one place a record is
    read into its arguments."""
    return round_budget(asked, pr=state.get("pr") or state.get("review_pr"),
                        change=change_of(state), exclude=run_dir, what="this change", own=own)


def lineage_cap(state, run_dir):
    """The rounds that run may have in all: the change's budget less what other runs spent."""
    return change_budget(state, run_dir, taskfile.TASK_MAX_ROUNDS)[0]


def allowed_rounds(lp):
    """The rounds this run may spend in all, read again as each is spent: its own budget, and
    never past what its change has left across its runs (`lineage_cap`), which another run of
    the change may have spent meanwhile."""
    return min(lp.rounds, lineage_cap(lp.state, lp.run_dir))


def round_allowed(lp):
    """Whether this run may spend another round: one of its own left, and one left on its
    change across its runs (`change_budget`, counting the rounds it spent itself).  Past the
    change's with rounds of its own left, the run ends blocked with the reason, so its seat
    hears it: the task is what changes, split or redesigned, and nothing a resume could
    spend."""
    if lp.rnd >= lp.rounds:
        return False
    left, why = change_budget(lp.state, lp.run_dir, lp.rounds, own=lp.rnd)
    if left < 1:
        lp.log(f"BLOCKED {why}")
        raise turns.Blocked(why, f"## Blocked\n\n{why}")
    return True


def reviewer_transport_dead(error):
    """Whether an `exhausted` run is off a reviewer's transport deaths, and only that.

    The transport half of `job_transport_exhausted`: the reviewer died on API or
    transport errors, with the meters still healthy.  A reviewer that twice answered
    without a verdict is not dead -- it is stuck, and another lap at the tick's pace
    will not unstick it -- so only this half resumes a run outside a job.
    """
    return "API/transport errors" in (error or "")
