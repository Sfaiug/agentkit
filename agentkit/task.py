"""The task file: front matter, title, done-when commands and size."""

import os
import re
import subprocess

from . import config

# Retired keys stay readable so older run copies still parse: `after:` is refused at launch
# (`launch_refusal`), the time keys draw a warning.
TASK_KEYS = ("after", "base", "done_when_minutes", "files", "from", "merge", "repo",
             "rounds", "stall_minutes", "target", "turn_hours")
TASK_MAX_ROUNDS = 3      # the round budget, not a default: past it, split or re-scope
# Ceilings on what one review takes at once, from the measured round-1 pass rate by size
# (9 Oct 2026: pull requests of 50 changed lines or fewer passed round 1 94% of the time,
# 201-400 lines 43%, over 1,000 lines 20%): a task has at most this many per-round checks,
# one behaviour a reviewer holds in one read, and a seat's own pull request's first review
# this many added lines, generated files aside and nothing deleted counted.  Past either,
# split it.
MAX_CHECKS = 3
MAX_PR_LINES = 400
DONE_WHEN = re.compile(r"^##\s+Done when\s*$(.*?)(?=^##\s|\Z)", re.S | re.M | re.I)
FENCE = re.compile(r"```(?:bash|sh)?\n(.*?)```", re.S)
ONCE_MARKER = re.compile(r"#\s*once\s*$")
# bash's own warning for a heredoc it never closes, from 3.2 (`bash: warning: …`) to 5.2
# (`bash: line 1: warning: …`)
UNCLOSED_HEREDOC = re.compile(r"^[^:\n]+: (?:line \d+: )?warning: here-document at line \d+ "
                              r"delimited by end-of-file", re.M)


def front_matter(path):
    """(pairs, body): each front-matter `key: value` in file order, and the text after it.

    A key may repeat, so `files:` keeps every line; a `#` starts a comment.
    Unknown keys, lines that are not `key: value` and missing closing lines are task errors.
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
        key = key.strip()
        if key not in TASK_KEYS:
            raise config.Error(f"{path}: unknown front-matter key {key!r}; "
                               f"accepted keys: {', '.join(TASK_KEYS)}")
        pairs.append((key, value.split("#", 1)[0].strip()))
    return pairs, match.group(2) if match else text


def parse_task(path):
    pairs, body = front_matter(path)
    title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), path.stem)
    return dict(pairs), body, title


def task_files(path):
    """Allowed Git pathspecs from repeatable, comma-separated `files:` lines."""
    return [part.strip() for key, value in front_matter(path)[0] if key == "files"
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
    once-commands run once at landing on the commit to be merged, or per round
    for scratch and `--no-merge` runs.
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


def launch_refusal(meta, cmds):
    """One sentence when a new task file cannot start as written, else None.

    A heredoc never works in done-when: each line runs as a command of its own, so the
    opening line reads an empty script and its body lines run as commands.  The check
    ceiling (`checks_refusal`) is preflight's, which settles the list a round runs.
    """
    if "after" in meta:
        return ("`after:` is gone: tasks launched together are independent pieces; build work "
                "that waits on another piece in your session, in order")
    heredoc = next((cmd for cmd in cmds if opens_heredoc(cmd)), None)
    if heredoc:
        return (f"done-when line {heredoc!r} opens a heredoc, but each line runs as a command of "
                "its own: put the script in a file the change adds, or on one line")
    return rounds_refusal(meta.get("rounds"), "task rounds")


def checks_refusal(every):
    """One sentence when more than `MAX_CHECKS` checks would run each round, else None:
    `every` as the loop settles it (`run.round_checks`), the repository's suite line, which
    runs once at landing, never among them, a `# once` line among them where the run has no
    landing."""
    if len(every) > MAX_CHECKS:
        return (f"{len(every)} done-when checks: a task has at most {MAX_CHECKS}, one behaviour a "
                "reviewer holds in one read; split it")
    return None


def opens_heredoc(command):
    """Whether bash's own parser, reading `command` as a whole script, meets an unclosed heredoc.

    `bash -n` runs nothing, so a shift in arithmetic, a comment, any quoting and a `<<<`
    here-string are no heredoc, exactly as when the line runs.  What bash parses only when it
    runs it -- a backquoted body, and before bash 5.2 any substitution's -- this leaves as bash
    -n does: reading it any other way would refuse lines bash runs as written.
    """
    if "<<" not in command:
        return False        # no expansion makes a heredoc: its operator is in the text
    # nothing inherited may make bash read a file first or echo the line back (`verbose`)
    env = {key: value for key, value in os.environ.items()
           if key not in ("BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS")}
    try:
        said = subprocess.run(["bash", "-n", "-c", command], capture_output=True, text=True,
                              env={**env, "LC_ALL": "C"}, timeout=30).stderr
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(UNCLOSED_HEREDOC.search(said))


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
