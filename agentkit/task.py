"""The task file: front matter, title, `after:` lines, done-when commands and size."""

import re

from . import config

AFTER_KEY = "after"  # front matter `after:` names another task file in the same job
TASK_MAX_POINTS = 3      # numbered points in ## Goal: more is more than one behaviour
TASK_MAX_WORDS = 500     # words outside the checks block: past this, split the task
TASK_MAX_CHECKS = 6      # done-when commands: past this, split the task
TASK_MAX_ROUNDS = 3      # the round budget, not a default: past it, split or re-scope
DONE_WHEN = re.compile(r"^##\s+Done when\s*$(.*?)(?=^##\s|\Z)", re.S | re.M | re.I)
FENCE = re.compile(r"```(?:bash|sh)?\n(.*?)```", re.S)
ONCE_MARKER = re.compile(r"#\s*once\s*$")


def front_matter(path):
    """(pairs, body): each front-matter `key: value` in file order, and the text after it.

    A key may repeat, so `after:` keeps every line; a `#` starts a comment.  A line that is
    not `key: value`, or a front matter with no closing line, is the task's error.
    """
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not match and text.startswith("---\n"):
        raise config.Error(f"{path}: front matter needs a closing --- line")
    pairs = []
    for line in (match.group(1).splitlines() if match else []):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise config.Error(f"{path}: front matter line is not `key: value`: {line!r}")
        key, value = line.split(":", 1)
        pairs.append((key.strip(), value.split("#", 1)[0].strip()))
    return pairs, match.group(2) if match else text


def parse_task(path):
    pairs, body = front_matter(path)
    title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), path.stem)
    return dict(pairs), body, title


def task_afters(path):
    """`after:` values from a task file's front matter, one per line, repeatable.

    Each line names the basename or title of another task file in the same job;
    a comma-separated line names several. Blank values are ignored.
    """
    return [part.strip() for key, value in front_matter(path)[0] if key == AFTER_KEY
            for part in value.split(",") if part.strip()]


def done_when(body, path):
    section = DONE_WHEN.search(body)
    if not section:
        raise config.Error(f"{path}: no `## Done when` section")
    fence = FENCE.search(section.group(1))
    if not fence:
        raise config.Error(f"{path}: `## Done when` has no ```bash fenced command block")
    cmds = [l.strip() for l in fence.group(1).splitlines() if l.strip() and not l.strip().startswith("#")]
    if not cmds:
        raise config.Error(f"{path}: `## Done when` block is empty; done means commands that exit 0")
    return cmds


def split_once(cmd):
    """(command, is_once): strip a trailing `# once` marker, when the line has one.

    The marker is the tail the spec names -- whitespace, `#`, `once` -- and only when
    its `#` is outside any quotes: `echo "# once"` names no marker, it runs one.  The
    stripped command is what the loop executes; bash would ignore the comment anyway,
    so an older loop that runs the line whole runs the same command.
    """
    single = double = False
    escaped = False
    for i, ch in enumerate(cmd):
        if escaped:
            escaped = False
        elif ch == "\\" and not single:
            escaped = True
        elif ch == "'" and not double:
            single = not single
        elif ch == '"' and not single:
            double = not double
        elif ch == "#" and not single and not double:
            if i > 0 and cmd[i - 1] in " \t" and ONCE_MARKER.match(cmd[i:]):
                return cmd[:i].rstrip(), True
    return cmd, False


def group_commands(cmds):
    """(every, once): a command list split on the `# once` marker, markers stripped."""
    every, once = [], []
    for cmd in cmds:
        bare, is_once = split_once(cmd)
        (once if is_once else every).append(bare)
    return every, once


def done_when_groups(body, path):
    """(every, once): the task's done-when commands, split on a trailing `# once` marker.

    `done_when` itself is unchanged -- the flat list, markers intact, for callers that
    want every command plus the once ones.  The every-commands run per round; the
    once-commands run alongside the review on the commit under review, and again at
    landing only when the target moved in the branch's files.
    """
    return group_commands(done_when(body, path))


def task_points(body):
    """Numbered points in the task's `## Goal` section: `1.` or `1)` with text after it."""
    section = re.search(r"^##\s+Goal\s*$(.*?)(?=^##\s|\Z)", body, re.S | re.M | re.I)
    if not section:
        return 0
    return len(re.findall(r"^[ \t]*\d+[.)][ \t]+\S", section.group(1), re.M))


def task_words(body):
    """Words outside the checks block: the fenced done-when commands are not prose."""
    section = DONE_WHEN.search(body)
    if section:
        fence = FENCE.search(section.group(1))
        if fence:
            body = body.replace(fence.group(0), "", 1)
    return len(body.split())


def task_size(body, cmds):
    """(words outside the checks block, numbered goal points, checks) for one task."""
    return task_words(body), task_points(body), len(cmds)


def task_size_refusal(body, cmds):
    """One sentence when the task is bigger than one behaviour, else None.

    Points first, then words, then checks: the first rule the task breaks is the one
    named, with its count, so the refusal is one sentence however far over it is.
    """
    points = task_points(body)
    if points > TASK_MAX_POINTS:
        return f"task has {points} numbered goal points (at most {TASK_MAX_POINTS})"
    words = task_words(body)
    if words > TASK_MAX_WORDS:
        return (f"task body has {words} words outside the checks block "
                f"(at most {TASK_MAX_WORDS})")
    if len(cmds) > TASK_MAX_CHECKS:
        return f"task has {len(cmds)} checks (at most {TASK_MAX_CHECKS})"
    return None


def rounds_refusal(value, what):
    """One sentence when a round budget asked for is over the rule, else None.

    Three rounds is the budget and never a default to raise: a run that has not passed by
    then goes back to its orchestrator with its findings, to split or re-scope, and no
    flag carries it further.  A value that is no number is left to the check that says so.
    """
    try:
        rounds = int(value)
    except (TypeError, ValueError):
        return None
    if rounds <= TASK_MAX_ROUNDS:
        return None
    return (f"{what} {rounds} is over the budget: {TASK_MAX_ROUNDS} rounds, then a run goes "
            "back to its orchestrator to split or re-scope")
