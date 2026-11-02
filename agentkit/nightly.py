"""A project's failed night starts one reviewed fix by itself, and nobody is told.

A project's merge gate may run only part of the suite its own host runs at night, and nobody reads
a failed night: the owner decided on 2 Nov 2026 that ak does.  Its `nightly:` names a command that
prints the newest night as JSON and exits 0, other fields ignored:
`{"started": "<names the night>", "passed": false, "failed": ["tests/a.py::b"]}`.

Hidden here: reading that, every EVERY at most, in each checkout declaring it on its default
branch; what makes a night usable; the fix run's task and the file of names its done-when hands
the project's suite; and state/nightly.json, holding by checkout when its night was last read
(`asked`) and the last night a run started for.  Whatever starts no run leaves no mark, so the next
read tries again.
"""

import hashlib
import json
import shlex
import time

from . import config, gitcall, orch, task as taskfile, watch

EVERY = 3600    # how often a checkout's night is read
CEILING = 60    # a read still running then fails
# The most names a fix run's check takes: a shell line has a limit, more failures than that
# usually share a cause, and the next night names what is left.
FIRST = 100


def tick(log):
    """The tick's pass: each checkout's night read, once every EVERY.  Each keeps its own stamp,
    taken as its read starts: a slow read before it must not shorten its hour."""
    path = config.STATE / "nightly.json"
    try:
        record = dict(json.loads(path.read_text()))
    except (OSError, TypeError, ValueError):
        record = {}
    asked = record.get("asked")
    record["asked"] = asked = asked if isinstance(asked, dict) else {}
    # Which goes first decides nothing, each stamp being its own; last name first only because the
    # check this fix landed under counts on the first name's slow read coming after the others.
    for checkout in reversed(orch.checkouts()):
        now, last = time.time(), asked.get(str(checkout))
        if isinstance(last, (int, float)) and 0 <= now - last < EVERY:
            continue
        asked[str(checkout)] = now
        started = _read(checkout, record.get(str(checkout)), log)
        if started:
            record[str(checkout)] = started
        orch.replace_file(path, json.dumps(record).encode())


def _one_line(value):
    """Whether a night's value can stand as one line of a task, or of the file of names."""
    return isinstance(value, str) and len(value.strip().splitlines()) == 1


def _read(checkout, handled, log):
    """The checkout's night once a run started for it, `handled` being the last that did; None
    for all else, with one line logged where something is wrong."""
    env = gitcall.project_env(checkout)
    command = gitcall.declared_at(checkout, config.RULES_REF, "nightly", env=env)
    if not command:
        return None
    night, why = gitcall.project_answer(command, checkout, CEILING, "nightly")
    started = night.get("started") if isinstance(night, dict) else None
    if not _one_line(started) or not isinstance(night.get("passed"), bool):
        log(f"WARN {checkout.name}: its night is unread: {why or 'no usable JSON'}")
        return None
    if night["passed"] or started == handled:
        return None
    failed = night.get("failed")
    names = [n.strip() for n in failed if _one_line(n)] if isinstance(failed, list) else []
    tests = gitcall.declared_at(checkout, config.RULES_REF, "tests", env=env)
    try:
        if not names or not tests:
            raise config.Error("no tests: to check a fix by" if names else "no failures named")
        run = watch.launch(str(_write_task(checkout, started, names, tests)))
    except (config.Error, OSError) as exc:
        log(f"WARN {checkout.name}: no fix run for its night {started}: {exc}")
        return None
    log(f"{checkout.name}: its night {started} failed; {run} fixes it")
    return started


def _write_task(checkout, started, names, tests):
    """The fix run's task and the file of names its done-when exports as `AK_ONLY`, the contract
    a red piece's retry uses (`worker.boxed`); the task's path.  Its title is every night's, so
    `ak run` refuses a night's run while another night's is under way.  Their names hash what the
    night says, so a read writing them, refused or not, never changes a running fix's list."""
    held = hashlib.sha256(json.dumps([started, names]).encode()).hexdigest()[:16]
    task = config.HOME / "tasks" / checkout.name / f"night-{held}.md"
    task.parent.mkdir(parents=True, exist_ok=True)
    only = task.with_suffix(".names")
    orch.replace_file(only, "".join(f"{name}\n" for name in names[:FIRST]).encode())
    listed = "".join(f"- {name}\n" for name in names)
    task.write_text(f"---\nrepo: {checkout}\n---\n"
                    f"# Fix the tests {checkout.name}'s last night failed\n\n"
                    f"The night {started} failed these tests:\n\n{listed}\n"
                    f"The command below runs the first {FIRST} at most; the next night names what "
                    f"is left.\n\n{taskfile.FIX_THE_COMMAND}\n\n## Done when\n```bash\n"
                    f"export AK_ONLY={shlex.quote(str(only))}; {tests}\n```\n")
    return task
