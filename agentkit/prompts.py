"""What a reviewer is handed and how its hand-in is weighed.

The review contract: the diff and done-when output a reviewer reads, the findings a fixer is
handed, the replay of earlier findings on a later commit and where the fix left their lines,
the proofs ak runs itself for a finding, a follow-up or a dispute, and the words a fixer's
summary and a pull request's own description become in a prompt.  What a check printed is
read here into the line that names its first failure.
"""

import difflib
import io
import json
import re
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path

from . import config, gitcall, hand_in, record as run_record, turns, worker


DIFF_CAP = 300 * 1024


FOLLOWUPS = re.compile(r"^(#+)[ \t]*Follow-ups\b[^\n]*$", re.M | re.I)


NOTES = re.compile(r"^(#+)[ \t]*Notes\b[^\n]*$", re.M | re.I)


# What the loop itself adds to a done-when log, in its own words, after the commands have had
# their say: none is a command's output, and reading one as such would make a failure that
# never moved look new every round.  See `run_done_when`, `verify_work` and `final_check`.
LOOP_NOTE = re.compile(r"^(?:Checkout changed during |done-when: stopped after |outside files: "
                       r"|AGENTS\.md (?:is|could not be read|must not|front matter has) )")


# Where a suite, unittest, pytest or TAP names what failed: at the start of the line it says so
# on, long before the tally it ends with.  See `first_failure`.
FAILURE_LINE = re.compile(r"^(?:FAIL(?:ED)?|ERROR|not ok)\b")


HANDOVER = ("## Another model started this round\n"
            "{before} began this round and its provider's window ran out mid-way, so the work is "
            "yours from here. The checkout is the same one it was working in and may carry "
            "uncommitted edits of its own: read them, keep what is right, and finish the task "
            "below as if it were round one.")


def plan_context(seat):
    """The seat's open plan lines (`plan.open_lines`), for the review of its own PR: the
    outcomes the user agreed to, each with the check that proves it and the project it is
    on.  A review launched from no seat has no plan."""
    from . import plan
    open_lines = plan.open_lines(seat) if seat else []
    if not open_lines:
        return ""
    return ("## The plan this PR serves\nThe session's open plan lines, the outcomes the user "
            "agreed to, each naming the project it is on:\n" + "\n".join(open_lines) + "\nAn "
            "outcome on this repository that this PR claims to deliver but misses is a finding "
            "whose proof is that line's check, run with `--run`.\n\n")


def base_proof_line(state):
    """What a run's result and PR say of its proof, or "" for a run that owes none."""
    if state.get("base_proof") == "proven":
        return "base proof: a check fails on the old code and passes with this change"
    if state.get("base_proof") == "owed":
        return f"base proof: none shown ({state.get('base_proof_note') or 'not tried yet'})"
    return ""


def review_files(run_dir, rnd):
    """Every reviewer answer one round left, oldest first; the last is the one it recorded.

    A round writes under `reviewer`, `reviewer-attemptN` when an unfinished review resumed,
    `reviewer-<model>` when the reviewer fell back to another model, and `-retryN` beside
    any of those when the harness died on the provider rather than on the diff.
    """
    found = []
    for directory in Path(run_dir).joinpath(f"round-{rnd}").glob("reviewer*"):
        try:
            path = directory / hand_in.REPORT
            if not path.exists():
                path = directory / "final.md"
            found.append((path.stat().st_mtime, path))
        except OSError:
            continue                    # no answer under it, or it went while we were looking
    return [path for _, path in sorted(found)]


def written_answer(out, text):
    """The file the answer just returned was read from.

    `call_retrying` gives every retry a directory of its own and returns only the text, so
    `out` itself holds a provider error whenever a retry is what finally answered -- naming it
    would hand the next fixer that error instead of the review.  Matched on the content, which
    is what makes the answer and the file the same thing.
    """
    out = Path(out)
    directories = sorted([out, *out.parent.glob(f"{out.name}-retry*")],
                         key=lambda path: (path.stat().st_mtime_ns if path.exists() else 0, path.name),
                         reverse=True)
    for directory in directories:
        if turns.read_answer(directory / "final.md") == text:
            return directory / "final.md"
    for directory in directories:
        if (directory / hand_in.FILE).exists():
            return directory / "final.md"
    return out / "final.md"


def review_records(out, text):
    return hand_in.read(written_answer(out, text).parent / hand_in.FILE)


def record_findings(lp, out, text, submitted=None):
    """What the reviewer said, and where the whole of it is.

    Written together everywhere, because a `findings_file` left pointing at another answer
    would hand the next fixer the wrong review -- worse than the tail it replaces.
    """
    source = written_answer(out, text)
    if submitted is None:
        submitted = hand_in.read(source.parent / hand_in.FILE) or hand_in.Review([])
    text = submitted.text
    source = source.parent / hand_in.REPORT
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text)
    source.with_name(hand_in.FINDINGS_FILE).write_text(json.dumps(submitted.findings))
    lp.findings = text
    lp.state["findings"] = text.strip()[-8000:]
    lp.state["findings_file"] = str(source)
    lp.state["review_records"] = submitted.records


def overridden_section(state):
    """Why the loop failed what the reviewer passed, to lead wherever that review is shown.

    It lives in the round's review record, never in the reviewer's text, whose kept tail
    a long report would push it out of.
    """
    review = state.get("review")
    why = review.get("overridden") if isinstance(review, dict) else None
    return f"## Overridden to FAIL\n{why}\n\n" if why else ""


def saved_findings(run_dir, state):
    """The last reviewer's whole text, for the fixer that has to work through it.

    `run.json` keeps a bounded tail of it, which is all a result page or a menu row needs;
    the round directory keeps the answer itself.  A resumed round must not be handed less than
    the round it continues would have been, so the file wins wherever it is still there --
    including for a run saved before the loop recorded which file that is, whose answers are
    still on disk: the tail was cut off the end of one of them, and that one is it.  Without
    a `run_dir` only the named file is read.
    """
    tail = (state.get("findings") or "").strip()
    named = turns.read_answer(state.get("findings_file")) if state.get("findings_file") else None
    if named is not None and (not tail or named.strip().endswith(tail)):
        return named
    for rnd in (range(len(state.get("round_summaries") or []), 0, -1)
                if tail and run_dir is not None else ()):
        for path in reversed(review_files(run_dir, rnd)):
            whole = turns.read_answer(path)
            if whole is not None and whole.strip().endswith(tail):
                return whole
    return state.get("findings") or ""


def without_followups(text):
    """The reviewer's answer as its fixer gets it, without follow-ups or unproven notes.

    Follow-ups predate the task and start runs of their own once this one merges; handed to
    a fixer told to address every finding below, they become out-of-scope work. Each section
    ends at the next heading of the same level or higher.
    """
    for pattern in (FOLLOWUPS, NOTES):
        heading = pattern.search(text or "")
        if heading:
            section = text[heading.end():]
            end = re.search(rf"^#{{1,{len(heading.group(1))}}}[ \t]", section, re.M)
            text = text[:heading.start()] + (section[end.start():] if end else "")
    return text


def record_flakes(state, text):
    """Keep each gate's flaky evidence with the current review, including checks after PASS."""
    for record in text.split("\n\n"):
        if record.startswith("flaky: ") and record not in state.get("followups", []):
            state.setdefault("followups", []).append(record)


def done_when_counts(dw_log, cmds):
    """(exited_zero, total) done-when commands, from the markers run_done_when writes.

    A marker only counts at the start of a blank-line-separated record, and only for the
    done-when command named on its `$ command` line.  Only `[exit 0]` is a pass: a signed
    status, `[killed at the limit]`, `[not run: the done-when limit was already spent]`
    and any marker text a later writer adds all count as failed, so nothing the loop
    reports ever vanishes from the reviewer's summary.  Whatever a command itself printed
    -- even a blank line plus a record-shaped `$ ...` / `[exit ...]` pair for a pending
    command -- never establishes provenance: when the records for one command disagree on
    the outcome, that command counts as failed.
    """
    marks = []
    for record in dw_log.split("\n\n"):
        match = re.match(r"\$ ([^\n]*)\n\[([^\]\n]*)\]", record)
        if match:
            marks.append((match.group(1), match.group(2) == "exit 0"))
    if cmds is None:
        return sum(ok for _, ok in marks), len(marks)
    hits = {}
    for cmd, ok in marks:
        hits.setdefault(cmd, []).append(ok)
    totals = {}
    for cmd in cmds:
        totals[cmd] = totals.get(cmd, 0) + 1
    passed = total = 0
    used = {}
    for cmd in cmds:
        outcomes, at = hits.get(cmd, []), used.get(cmd, 0)
        used[cmd] = at + 1
        if len(outcomes) == totals[cmd]:
            total += 1
            passed += outcomes[at]
        elif len(outcomes) > totals[cmd]:
            total += 1
            # printed records collide with the real one: fail closed, unless every
            # candidate agrees the command exited 0 -- then success is undisputed
            passed += all(outcomes)
        elif at < len(outcomes):
            total += 1  # a record went missing; trust the ones still there, in order
            passed += outcomes[at]
        # else: no record at all for this occurrence; nothing to count
    return passed, total


def failing_checks(dw_log):
    """Which done-when commands failed, and the last line each of them printed.

    What makes two failures the same failure: `run_done_when` writes one blank-line-separated
    record per command -- `$ <command>`, its marker, then its output -- and the last line is
    what the command finally said about itself.  Earlier lines carry run numbers, temporary
    paths and timings that differ every round, so comparing them would make every failure look
    new; the last line is the assertion or the exit message, which does not move unless
    something about the failure did.
    """
    found, failing = [], None
    for record in (dw_log or "").split("\n\n"):
        if record.startswith("flaky: "):
            continue
        match = re.match(r"\$ ([^\n]*)\n\[([^\]\n]*)\]", record)
        if match:
            # a marker counts only at the start of a record, as `done_when_counts` reads it;
            # a passing command's output is nobody's failure and a new record ends the last
            failing = None
            if match.group(2) != "exit 0":
                failing = [match.group(1), ""]
                found.append(failing)
            record = record[match.end():]
        if failing is None or LOOP_NOTE.match(record.lstrip()):
            continue    # the header, a passing command, or the loop talking about the gate
        # a blank line inside a command's own output split it into parts of its own: they are
        # all that command's, so the last line stays the last thing it said about itself
        printed = [line.strip() for line in record.splitlines() if line.strip()]
        if printed:
            failing[1] = printed[-1]
    return found


def first_failure(dw_log):
    """The first failing command and the line that says what failed: one line, for a person.

    Not the line `failing_checks` compares on.  That last line is what stays still between
    rounds, and a suite ends on its tally -- `acceptance: FAILED (see ...)` -- which says that
    something failed and never what.  This is the first line the failing command started
    with FAIL, FAILED, ERROR or `not ok`, else the last line it printed, else the command
    alone; a gate no command failed says what the loop said about it instead.
    """
    failing, named, last, note = None, None, None, None
    for record in (dw_log or "").split("\n\n"):
        if record.startswith("flaky: "):
            continue
        match = re.match(r"\$ ([^\n]*)\n\[([^\]\n]*)\]", record)
        if match:
            if failing is not None:
                break       # the next command's record: the first failing one said all it had
            if match.group(2) != "exit 0":
                failing = match.group(1)
            record = record[match.end():]
        for line in (line.strip() for line in record.splitlines()):
            if LOOP_NOTE.match(line):
                note = note or line
            elif failing is not None and line:
                named = named or (line if FAILURE_LINE.match(line) else None)
                last = line
    said = named or last or note or ""
    line = f"`{failing}` \u2014 {said}" if failing and said else f"`{failing}`" if failing else said
    return line if len(line) <= 200 else line[:199] + "\u2026"


def changed_test_paths(lp, head="HEAD", named=True):
    """The branch's changed tests: test-shaped paths, and with `named` every file a
    done-when command names."""
    # Include removed paths too: renaming a test out of discovery must remain visible.
    changed = gitcall.git(lp.wt, "diff", "--name-only", "-z", "--no-renames",
                  f"{lp.base_sha}...{head}").split("\0")
    return [p for p in changed if p and (
        any(part in TEST_DIRS for part in Path(p).parts[:-1]) or test_named(p)
        or (named and any(p in cmd for cmd in getattr(lp, "cmds", []))))]


def test_named(path):
    return Path(path).name.startswith("test_") or any(Path(path).match(shape)
                                                       for shape in TEST_NAMES)


# Where tests live and what they are called, in the common languages' own conventions:
# Python's tests/ and test_*.py, Go's *_test.go, Ruby's spec/ and *_spec.rb, JavaScript's
# __tests__/, *.test.js and *.spec.js.
TEST_DIRS = ("tests", "test", "spec", "specs", "__tests__")


TEST_NAMES = ("*_test.*", "*_spec.*", "*.test.*", "*.spec.*")


def hunks(lp, path, since, head):
    """The hunks of `path` from the commit `since` to `head`, no context, as git reads a
    conflict: (old start, old count, new start, new count) each, in order.  Two commits'
    trees, not their merge base's: after a rebased push the coordinates are the reviewed
    commit's own, and the base is already the merge base."""
    diff = gitcall.git(lp.wt, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
               "--unified=0", since, head, "--", f":(literal){path}")
    return [(int(hunk[1]), int(hunk[2] or 1), int(hunk[3]), int(hunk[4] or 1))
            for hunk in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", diff, re.M)]


def in_hunks(line, found):
    """Whether `line` is inside those hunks' new side.  A pure removal leaves an anchor
    between the two surviving neighbouring lines."""
    return any(start <= line < start + count if count else line in (start, start + 1)
               for _, _, start, count in found)


def changed_line(lp, row, head, since=None):
    """Whether the finding's line is inside the diff to `head` from `since`: the base, or the
    commit the last review judged, for a later round."""
    return in_hunks(row["line"], hunks(lp, row["path"], since or lp.base_sha, head))


def capped(lp, diff):
    """A diff cut at DIFF_CAP, saying where the rest is."""
    if len(diff) > DIFF_CAP:
        return diff[:DIFF_CAP] + f"\n\n[diff truncated at {DIFF_CAP} bytes; use git in {lp.wt} for the rest]"
    return diff


def proof_on(lp, command, log_path, revision=None, tests_from=None):
    """Replay evidence with the regression probe's overlay and crash-safe checkout recovery."""
    from . import gate  # here, not at the top: gate reaches run
    run_record.stop_check(lp.run_dir)
    if not lp.scratch:
        head = gitcall.git(lp.wt, "rev-parse", "HEAD")
        branch = gitcall.git(lp.wt, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        before = set(gitcall.dirty_paths(lp.wt))
        paths = changed_test_paths(lp, tests_from) if tests_from else []
        gitcall.save_probe_checkout(lp, head, branch, before, f"proof on {revision}")
    try:
        if not lp.scratch:
            gitcall.reset_checkout(lp.wt, head, before)
            gitcall.git(lp.wt, "checkout", "--quiet", "--detach", revision)
            if paths:
                gitcall.git(lp.wt, "restore", f"--source={tests_from}", "--staged", "--worktree", "--",
                    *(f":(literal){p}" for p in paths))
        run_record.stop_check(lp.run_dir)
        lp.log(f"--- review proof: checking {revision or 'workspace'}")
        env = gate.suite_env()
        env.pop(hand_in.ENV, None)
        env.pop(hand_in.CONTINUE, None)
        with tempfile.TemporaryDirectory(dir=lp.run_dir) as cache, log_path.open("w+b") as progress:
            # Same-size revisions can share a timestamp, making ignored bytecode look valid.
            env["PYTHONPYCACHEPREFIX"] = cache
            progress.write(f"$ {command} (on {revision or 'workspace'})\n".encode())
            progress.flush()
            start = progress.tell()
            try:
                code, _, killed = worker.boxed(
                    ["bash", "-c", command], lp.done_when_limit, silence=lp.turn_limit,
                    activity=log_path, output=progress, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, cwd=str(lp.wt), env=env)
            except (FileNotFoundError, PermissionError) as exc:
                code, killed = (127 if isinstance(exc, FileNotFoundError) else 126), False
                progress.write(str(exc).encode())
            output = hand_in.output_excerpt(progress, start)
            progress.write(f"\n[{'did not finish' if killed or code < 0 else f'exit {code}'}]\n".encode())
        turns.memory_cap_note(lp.run_dir, lp.log)
        return {"returncode": code, "output": output, "killed": killed}
    finally:
        try:
            worker.kill_marked(gitcall.run_child_env().get(worker.RUN_MARKER), log=lp.log)
        finally:
            if not lp.scratch:
                gitcall.restore_probe_checkout(lp, head, branch, before, f"proof on {revision}")


def quoted_sites(lp, submitted, head):
    quotes = {index: row for index, row in enumerate(submitted.records, 1)
              if row["kind"] == "finding" and "quote" in row["evidence"]}
    if not quotes:
        return {}
    with ExitStack() as stack:
        checkout = lp.wt
        if not lp.scratch:
            # Reuse hand-in's filesystem rules without trusting the reviewer's files or refs.
            checkout = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=lp.run_dir)))
            gitcall.git(lp.wt, "clone", "--quiet", "--shared", "--no-checkout", str(lp.wt), str(checkout))
            gitcall.git(checkout, "checkout", "--quiet", "--detach", head)
            # Clone metadata is not part of the reviewed commit.
            shutil.rmtree(checkout / ".git")
        sites = {}
        for index, row in quotes.items():
            try:
                root, path, line = hand_in.checked_site(
                    f"{row['path']}:{row['line']}", checkout, row["evidence"]["quote"])
                sites[index] = {"path": str(path.relative_to(root)), "line": line}
            except (config.Error, OSError, ValueError, RuntimeError):
                sites[index] = None
        return sites


def before_at_base(lp, row):
    before = row.get("before", "").strip()
    if not before:
        return False
    named = re.match(r"(?:base\s+)?([^\s:]+)(?::|\s|$)", before)
    if named:
        commit = gitcall.git(lp.wt, "rev-parse", "--verify", "--end-of-options",
                     f"{named[1]}^{{commit}}", check=False)
        if commit and gitcall.git_out(lp.wt, "merge-base", "--is-ancestor", commit, lp.base_sha)[0] == 0:
            return True
    code, content = gitcall.git_out(lp.wt, "show", f"{lp.base_sha}:{row['path']}")
    return code == 0 and before in content


def reviewed_before(lp, before, head):
    """The commit the last review of this run judged (`before`), when `head` is a later one:
    the delta from it is what a later round reviews.  None in round 1, in a scratch run, and
    for a review of that same commit again."""
    return before if before and not lp.scratch and before != head else None


def earlier_findings(lp):
    """The blocking findings the last review handed in, as weighed then: the copy this review
    took when it started (`review_pending`), which no dying attempt overwrites, else the records."""
    pending = lp.state.get("review_pending")
    if isinstance(pending, dict) and isinstance(pending.get("earlier"), list):
        return [row for row in pending["earlier"] if isinstance(row, dict)]
    return [row for row in (lp.state.get("review_records") or [])
            if isinstance(row, dict) and row.get("kind") == "finding"]


def dispute_rows(lp):
    """The disputes the round's fixer handed in, each once."""
    rows = []
    for file in lp.state.get("dispute_files", []):
        submitted = hand_in.read(file)
        for row in submitted.disputes if submitted is not None else ():
            if row not in rows:
                rows.append(row)
    return rows


def moved_lines(lp, path, line, since, head):
    """(the lines on `head` where line `line` of `path` at `since` can sit, whether the diff
    between them touched the line): one line where a fix above it moved a line it never
    touched; the lines the fix put in its place where it rewrote it; the removal's anchor,
    the line before it, where it deleted it; the line itself where there is no delta."""
    shift = 0
    for start, old, now, new in hunks(lp, path, since, head) if since else ():
        if old == 0:
            start += 1      # lines were added after `start`: what follows it moves
        if line < start:
            break
        if line < start + old:
            return (range(now, now + new) if new else range(max(now, 1), max(now, 1) + 1)), True
        shift += new - old
    return range(line + shift, line + shift + 1), False


def placed(lp, row, since, head):
    """Where an earlier finding stands on `head`: (its line there, whether the fix delta since
    `since` touched the line, every line it may stand at: its own, or those the fix put in its
    place).  A line the fix left alone moved with it; one the fix rewrote stands at the line
    the fix put in its place that reads most like it (a tie goes to the first); one the fix
    deleted stands at the removal's anchor.  The site a finding is listed and handed at,
    whatever the fix did to its line."""
    lines, touched = moved_lines(lp, row["path"], row["line"], since, head)
    line = lines[0]
    if len(lines) > 1:
        was = line_of(lp, since, row["path"], row["line"])
        now = gitcall.git(lp.wt, "show", f"{head}:{row['path']}", check=False).splitlines()
        line = max(lines, key=lambda at: (difflib.SequenceMatcher(
            None, was, now[at - 1] if at <= len(now) else "").ratio(), -at))
    return line, touched, lines


def line_of(lp, commit, path, line):
    """The text of that line of `path` at `commit`, '' where there is none."""
    text = gitcall.git(lp.wt, "show", f"{commit}:{path}", check=False).splitlines()
    return text[line - 1] if 0 < line <= len(text) else ""


def earlier_sites(lp, head, since):
    """Where the last review's blocking findings can stand on `head` (`moved_lines`: moved, or
    any of the lines the fix put in their place): a finding handed in again there upholds an
    earlier one, in whatever words, inside the fix delta or not."""
    return {(row["path"], at) for row in earlier_findings(lp)
            for at in moved_lines(lp, row["path"], row["line"], since, head)[0]}


def replay_findings(lp, rows, head):
    """Each earlier `--run` finding proven again on `head`: (the row, its evidence now, whether
    it blocks).  A failing proof blocks whatever the reviewer hands in; one that cannot run or
    finish is a note, as in the first round."""
    replayed = []
    if rows:
        lp.round_dir.mkdir(parents=True, exist_ok=True)   # the replay logs come before the turn
    for index, row in enumerate(rows, 1):
        command = row["evidence"]["run"]
        now = {"run": command, "commit": head,
               **proof_on(lp, command, lp.round_dir / f"replay-{index}.log", head)}
        replayed.append((row, now, hand_in.proof_failed(now)))
    return replayed


def replay_word(now, failing):
    """How a replayed proof went, for the reviewer and the record."""
    if now.get("killed") or now["returncode"] < 0:
        return "did not finish; kept as a note"
    if now["returncode"] in (126, 127):
        return f"could not run (exit {now['returncode']}); kept as a note"
    return f"still fails (exit {now['returncode']})" if failing else "fixed (the proof passes now)"


def replay_section(replayed, left, since):
    """What the reviewer is told of the earlier findings: ak's own replay of the proven ones,
    and the ones it leaves to the reviewer (`left`: each with why), never a question."""
    lines = [f"- {row['path']}:{row['line']} - {row['what']} - {replay_word(now, failing)}"
             for row, now, failing in replayed]
    yours = [f"- {row['path']}:{row['line']} - {row['what']} - {why}" for row, why in left]
    return (f"## Earlier findings, re-proven by ak on this commit\n"
            + ("\n".join(lines) if lines else "(none)")
            + ("\n\n## Earlier findings left to you\n" + "\n".join(yours) if yours else "")
            + "\nA finding still failing blocks whatever you hand in; one you hand in again at its "
              "site with its proof is weighed as ak's replay is; one fixed needs no word. "
            + (f"A new finding blocks only inside the fix delta since {since[:12]}, or with a "
               "proof that passes on that commit: the fix broke it." if since else
               "This is the commit the last review judged, again: a new finding blocks "
               "wherever it is in the change."))


def weigh_review(lp, submitted, head=None, since=None, replayed=()):
    """The reviewer's editable copy cannot decide what blocks the reviewed commit.

    In a later round (`since` names the commit the last review judged) a new finding blocks
    only inside the fix delta, or with a proof that passes on `since`; one handed in again at
    an earlier finding's site upholds it (a dispute the reviewer rejects) and is weighed as
    ever.  ak's own replay of the earlier findings (`replayed`) is weighed with the
    reviewer's, each where the fix left its line (`placed`): one still failing blocks
    whether or not the reviewer handed it in again; one fixed or unable to run is a note."""
    if not any(row["kind"] in ("finding", "follow-up") for row in submitted.records) and not replayed:
        return submitted
    head = None if lp.scratch else head or gitcall.git(lp.wt, "rev-parse", "HEAD")
    sites = quoted_sites(lp, submitted, head)
    earlier = earlier_sites(lp, head, since)
    records = []
    for index, row in enumerate(submitted.records, 1):
        if row["kind"] not in ("finding", "follow-up"):
            records.append(row)
            continue
        evidence = row["evidence"]
        kind = row["kind"]
        # a follow-up from before the task is proven on base; one of this change (no `before`)
        # on this commit, and on base too, where failing makes it one from before the task
        deferred = kind == "follow-up" and "before" not in row
        if kind == "follow-up":
            if not lp.scratch and "run" in evidence:
                command = evidence["run"]
                base = proof_on(lp, command, lp.round_dir / f"proof-{index}-base.log", lp.base_sha, head)
                evidence = {"run": command, "commit": lp.base_sha, **base}
                if deferred:
                    evidence = {"run": command, "commit": head, **proof_on(
                        lp, command, lp.round_dir / f"proof-{index}-commit.log", head),
                        "base": {"sha": lp.base_sha, **base}}
                    deferred = not (hand_in.proof_failed(evidence) and hand_in.proof_failed(base))
        elif index in sites and sites[index] is None:
            kind = "note"
        elif "run" in evidence:
            command = evidence["run"]
            evidence = {"run": command, "commit": head or "workspace",
                        **proof_on(lp, command, lp.round_dir / f"proof-{index}-commit.log", head)}
            if not lp.scratch:
                evidence["base"] = {"sha": lp.base_sha, **proof_on(
                    lp, command, lp.round_dir / f"proof-{index}-base.log", lp.base_sha, head)}
            if not hand_in.proof_failed(evidence):
                kind = "note"
            elif not lp.scratch and not changed_line(lp, row, head):
                base = evidence["base"]
                if hand_in.proof_failed(base):
                    kind = "follow-up"
                elif base["returncode"] != 0 or base["killed"]:
                    kind = "note"
        else:
            row = {**row, **sites[index]}
            if not lp.scratch and not changed_line(lp, row, head):
                kind = "follow-up"
        # a defect from before the task is a follow-up above, whichever round finds it: only
        # what would still block is held to the fix delta, and a proof passing on the commit
        # the last review judged shows the fix broke that line, wherever it is
        outside = (kind == "finding" and since and (row["path"], row["line"]) not in earlier
                   and not changed_line(lp, row, head, since))
        if outside and "run" in evidence:
            # a proof that cannot run or finish there shows no break, as on base above
            on_since = proof_on(lp, evidence["run"], lp.round_dir / f"proof-{index}-since.log",
                                since, head)
            outside = on_since["returncode"] != 0 or on_since["killed"]
        row = {**row, "kind": "note" if outside else kind, "evidence": evidence}
        if outside:
            row["outside"] = f"the fix delta since {since[:12]}; judged in an earlier round"
            lp.log(f"Kept as a note {row['path']}:{row['line']}: outside the fix delta")
        if kind == "follow-up":
            if "before" not in row and not deferred:
                row["before"] = f"base {lp.base_sha}: " + (
                    "the proof fails there too" if "run" in evidence
                    else "quoted lines outside the change")
            reason = ("no base commit" if lp.scratch else
                      "needs a --run proof" + ("" if deferred else " that fails on base")
                      if "run" not in evidence else
                      ("the command did not fail on this commit" if deferred
                       else "the command did not fail on base") if not hand_in.proof_failed(
                          evidence if deferred else evidence.get("base", evidence)) else
                      "--before names no commit in base's history or quote present at base"
                      if not deferred and not before_at_base(lp, row) else "")
            if reason:
                row.update(kind="note", dropped=reason)
                lp.log(f"Dropped follow-up {row['path']}:{row['line']}: {reason}")
        records.append(row)
    if replayed:
        handed = [row for row in records if isinstance(row.get("evidence"), dict)]
        extra = []
        for row, now, failing in replayed:
            # where the fix left its line, whatever base has there: git's diff tells neither a
            # moved line nor one the change added from one it put back as base has it
            line, touched, sites = placed(lp, row, since, head)
            row = {**row, "line": line}
            if not failing:
                extra.append({**row, "kind": "note", "evidence": now,
                              "replayed": "fixed; its proof passes now"
                              if now["returncode"] == 0 and not now.get("killed")
                              else replay_word(now, failing)})
                continue
            # the reviewer's own hand-in carrying this finding's very proof at its site, and
            # weighed to block, is this finding upheld, and ak adds no copy beside it;
            # anywhere else, or weighed down to a note or a follow-up, it is the reviewer's
            # words, and ak's own copy stands beside them
            if any(each["evidence"].get("run") == now["run"] and each["kind"] == "finding"
                   and each["path"] == row["path"] and each["line"] in sites for each in handed):
                continue
            extra.append({**row, "kind": "finding", "evidence": now, "replayed": (
                "still failing; it blocks until its proof passes"
                + ("; the fix changed its line" if touched else ""))})
            lp.log(f"Earlier finding {row['path']}:{row['line']} still fails on this commit")
        closing = records.pop() if records and records[-1]["kind"] in hand_in.CLOSING else None
        records.extend(extra)
        if closing is not None:
            records.append(closing)
    return hand_in.Review(records)


def review_disputes(lp, head):
    """Keep the finding snapshot the fixer received; replay its dispute on the reviewed work."""
    disputes = []
    for index, row in enumerate(dispute_rows(lp), 1):
        evidence = row["evidence"]
        if "run" in evidence:
            command = evidence["run"]
            evidence = {"run": command, "commit": head or "workspace", **proof_on(
                lp, command, lp.round_dir / f"dispute-{index}.log", head)}
        disputes.append({**row, "evidence": evidence})
    return hand_in.Review(disputes)


def failing_blocks(text, where, cap=None):
    """What a fixer reads of a failed check: its last `cap` characters, as before, and ahead of
    them every block that begins above that end and says what failed.

    A suite run in pieces prints each piece's failures where that piece ends, so the end alone
    can hold none of a red piece printed earlier: a landing fixer handed the last 20 KB never
    saw the red file 32 KB before it.  A block is a line that names a failure
    (`FAILURE_LINE`, at the start of the line) and the indented lines under it, taken whole
    even where the end begins inside it.  The end is kept whole too, so nothing the end alone
    showed is ever traded for a block, and the whole is saved under `where` and named first.
    """
    cap = turns.OUT_CAP if cap is None else cap
    if len(text) <= cap:
        return text
    above, blocks, block, at = len(text) - cap, [], None, 0
    for line in text.splitlines(keepends=True):
        began, at = at, at + len(line)
        line = line.rstrip("\r\n")
        if FAILURE_LINE.match(line):
            if began >= above:
                break       # this block and every later one lie whole in the end
            block = [line]
            blocks.append(block)
        elif block is not None and (not line or line[:1].isspace()):
            block.append(line)
        elif began >= above:
            break
        else:
            block = None
    named = "\n".join("\n".join(block).rstrip() for block in blocks)
    shown = f"{named}\n\n... the end of the output:\n{text[-cap:]}" if named else text[-cap:]
    return f"{turns.kept(io.BytesIO(text.encode()), where, 'failed-check')}\n{shown}"


def red_target_text(cmd, upstream, tip, output, where, piece=None):
    """What a red target's repair is told: the command (its red `piece`, `AK_SHARD=k/N`, named
    where the suite ran in pieces), where it fails, and what it printed there, read as a fixer
    reads a failed check -- indented, so nothing it printed reads as a heading or a fence of
    the task."""
    printed = "\n".join("    " + line for line in failing_blocks(output, where).splitlines())
    what = f"`{cmd}`" + (f", its piece AK_SHARD={piece}," if piece else "")
    return (f"{what} fails on {upstream} at {tip}, the target's own tip, whichever branch runs "
            f"it. What it printed there:\n\n{printed}")


def flaky_test_text(test, repo, upstream, seen):
    """What a flaky test's repair is told: the test, its repository, and each time the landing
    line saw it fail, then pass, on one tree, with the log that shows it."""
    logs = "\n".join(f"- {sight['log']}" for sight in seen)
    return (f"`{test}` in {repo} failed and then passed on the same tree {len(seen)} times "
            f"within a week, on {len({sight['tree'] for sight in seen})} trees of {upstream}: "
            f"each time the landing line ran it again. The logs that show it:\n\n{logs}\n\n"
            "Make it deterministic without weakening what it checks: find why it fails only "
            "sometimes and remove that cause, in the test or in the code it tests. Never make it "
            "retry, skip it or loosen what it asserts.")


def done_when_block(cmds):
    """The `## Done when` section a PR review's task and its fixer's share."""
    return "## Done when\n```bash\n" + (cmds[0] if cmds else "true   # AGENTS.md declares no tests:") + "\n```\n"


def fixer_words(round_dir, name):
    """What the fixer turn in that round said, for the record of the head it left: its
    answer, and the reason of a not-needed it handed in; '' without a turn.  Read where the
    turn wrote it, so a review resumed after a cut finds it too."""
    turn = turns.latest_worker_turn(round_dir, name)
    if turn is None:
        return ""
    answer = turn / "final.md"
    words = (turns.read_answer(answer) if answer.is_file() else "") or ""
    submitted = hand_in.read(turn / hand_in.FILE)
    closing = submitted.closing if submitted is not None else None
    if closing and closing["kind"] == "not-needed":
        words = f"{words}\n\nNot needed: {closing['why']}"
    return words.strip()


def fix_body(state, says, cmds, number):
    """What the fixer of a seat's own PR is told to do: make the pull request pass its review,
    with what the PR says (whole, as GitHub holds it) and the checks it must still pass, never
    the reviewer's goal."""
    return (f"# Fix PR #{number}: {state['title'].partition(': ')[2]}\n\n## Goal\nThe pull "
            "request passes its review: fix each finding below with the least change, on this "
            "branch, and keep its checks passing.\n\n"
            f"## The PR says\n{(says or '(no description)').strip()}\n\n{done_when_block(cmds)}")
