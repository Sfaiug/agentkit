"""The task file: front matter, title, decisions, done-when commands and size."""

import os
import re
import subprocess

from . import config

# Retired keys stay readable so older run copies still parse: `after:` is refused at launch
# (`launch_refusal`), the time keys draw a warning.
TASK_KEYS = ("after", "base", "done_when_minutes", "files", "from", "merge", "repo",
             "rounds", "stall_minutes", "target", "turn_hours")
# What a task tells its run to make a given failing command pass: a repair, a follow-up, a night.
FIX_THE_COMMAND = (
    "Your checkout starts on the target branch's tip, fetched when this run "
    "started. ak checked the command below there before your first turn. "
    "Fix the root cause so it passes, and show it failing before the "
    "fix and passing afterwards in your summary. If only the owner can decide, "
    'run `ak hand-in blocked "<question>"`.')
# Queued and interrupted tasks keep their original instructions.
OLD_FIX_THE_COMMAND = (
    "Your checkout starts on the target branch's tip, fetched when this run "
    "started: run the command below there first. If it "
    'passes there now, run `ak hand-in not-needed "<why>"`, with no edits or PR. '
    "Otherwise fix the root cause so it passes, and show it failing before the "
    "fix and passing afterwards in your summary. If only the owner can decide, "
    'run `ak hand-in blocked "<question>"`.')
# One behaviour a reviewer holds in one read; past it, split the task.
MAX_CHECKS = 3
DONE_WHEN = re.compile(r"^##\s+Done when\s*$(.*?)(?=^##\s|\Z)", re.S | re.M | re.I)
FENCE = re.compile(r"```(?:bash|sh)?\n(.*?)```", re.S)
ONCE_MARKER = re.compile(r"#\s*once\s*$")
# bash's own warning for a heredoc it never closes, from 3.2 (`bash: warning: …`) to 5.2
# (`bash: line 1: warning: …`)
UNCLOSED_HEREDOC = re.compile(r"^[^:\n]+: (?:line \d+: )?warning: here-document at line \d+ "
                              r"delimited by end-of-file", re.M)


def front_matter(path, text=None):
    """(pairs, body): each front-matter `key: value` in file order, and the text after it.

    A key may repeat, so `files:` keeps every line; a `#` starts a comment.
    Unknown keys, lines that are not `key: value` and missing closing lines are task errors.
    """
    text = path.read_text() if text is None else text
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


def parse_task(path, text=None):
    pairs, body = front_matter(path, text)
    decided(body)
    title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), path.stem)
    return dict(pairs), body, title


def goal_text(body):
    """Keep the Goal's indentation and examples; headings inside fences are its text."""
    return next(_sections(body, "Goal"), "")


def _sections(body, heading):
    lines, found, fence = [], False, ""
    for line in body.splitlines(keepends=True):
        marker = re.match(r" {0,3}(`{3,}|~{3,})(.*)", line)
        if fence:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = ""
        elif marker and (marker[1][0] == "~" or "`" not in marker[2]):
            fence = marker[1]
        elif re.match(r"##[ \t]+", line):
            if found:
                yield "".join(lines).strip("\n")
            found = bool(re.fullmatch(rf"##[ \t]+{heading}[ \t]*\n?", line, re.I))
            lines = []
            continue
        if found:
            lines.append(line)
    if found:
        yield "".join(lines).strip("\n")


def task_files(path):
    """Allowed Git pathspecs from repeatable, comma-separated `files:` lines."""
    return [part.strip() for key, value in front_matter(path)[0] if key == "files"
            for part in value.split(",") if part.strip()]


def decided(body):
    """Settled decision lines, in order; malformed sections cannot launch."""
    sections = list(_sections(body, "Decided"))
    if len(sections) > 1:
        raise config.Error("`## Decided` may appear only once; keep decisions in one section")
    lines = [line.strip() for line in sections[0].splitlines() if line.strip()] if sections else []
    invalid = next((line for line in lines if not line.startswith(("Not wanted:", "Accepted:"))), None)
    if invalid is not None:
        raise config.Error(f"`## Decided` lines must start with `Not wanted:` or `Accepted:`; "
                           f"got {invalid!r}")
    return lines


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


def launch_refusal(meta, cmds, budget):
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
    return rounds_refusal(meta.get("rounds"), "task rounds", budget)


def checks_refusal(every):
    """One sentence when more than `MAX_CHECKS` checks would run each round, else None:
    `every` as the loop settles it (`run.round_commands`), the target's suite line, which
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
    said = bash_reads("-n", "-c", command)
    return bool(said and UNCLOSED_HEREDOC.search(said.stderr))


def bash_reads(*args, **run):
    """bash, set by `args` to read a line with its own parser and run none of it: the finished
    process, or None where no bash answers."""
    # nothing inherited may make bash read a file first or echo the line back (`verbose`)
    env = {key: value for key, value in os.environ.items()
           if key not in ("BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS")}
    try:
        return subprocess.run(["bash", *args], capture_output=True, encoding="utf-8",
                              errors="surrogateescape", env={**env, "LC_ALL": "C"}, timeout=30,
                              **run)
    except (OSError, subprocess.SubprocessError):
        return None


def printed(line):
    """`line` as bash prints the command its own parser reads it as: in bash's one layout,
    comments gone, and so each substitution in it that bash parses as it reads the line (from
    5.2).  None where bash prints none: a line it cannot parse, a bash with no
    `--pretty-print`, or a line a backslash ends, which escapes the line's end where bash
    reads a file and stays a backslash in the `-c` that runs the line."""
    if line.endswith("\\"):
        return None
    said = bash_reads("--pretty-print", input=line)             # never `-c`: that runs the line
    return said.stdout.rstrip("\n") if said and said.returncode == 0 else None


# what opens a quote or a bracket, and what closes it
CLOSES = {"'": "'", "$'": "'", '"': '"', "`": "`", "(": ")", "$(": ")", "<(": ")", ">(": ")",
          "${": "}"}
SEPARATOR = re.compile(r"[ \t]+|\n|;;&?|;&|&&|&>>?|\|[|&]|<<[<-]?|<[&>]|>[>&|]|[|&;<>]")
DESCRIPTOR = re.compile(r"\d+|\{\w+\}")     # what a redirection may name before its `<` or `>`
PLAIN = r"[\w./:@%+,-]"                     # a character that is itself to bash, quoted or not
# a piece of a word nothing in which expands: such a character, an escaped one, a quoted run
LITERAL = re.compile(rf"""({PLAIN})|\\(.)|'([^']*)'|"([^"$`\\]*)\"""")
# what bash knows by its unquoted spelling, so that a quote makes it another word: a keyword,
# an option of `time`, a builtin whose arguments it reads as assignments or, `unset`, as array
# references, and `command` before one
SYNTAX = ("case coproc do done elif else esac fi for function if in select then time until while "
          "-p -- alias declare export local readonly typeset unset command").split()
NAMES = ("coproc", "for", "function", "select")     # what a name bash keeps as written follows
WRITES = re.compile(r"(\d+|\{\w+\})?(>[>|&]?|&>>?)")     # a redirection of output


def split(text):
    """(words, held): `text`'s words as bash splits them, and the spans of it that hold
    commands of their own.  Blanks and a comment are dropped, and each operator (`|`, `&&`,
    `;`, `>>`, a line's end) is a word of its own, with the descriptor its redirection names
    (`2>`).  What a quote or a bracket (`CLOSES`) holds is as written, blanks and all: a
    backslash escapes there but in `'...'`, a bracket holds further quotes and brackets, and
    `"..."` holds `$(...)`, `${...}` and backquotes.  Commands are what a substitution holds
    wherever it stands and a subshell where it opens a word, each inside no other parenthesis
    and starting with none, which arithmetic does."""
    words, nest, held, start, i = [], [], [], 0, 0
    while i < len(text):
        top, since = nest[-1] if nest else ("", 0)
        opens = (() if top in ("'", "$'", "`") else ("$(", "${", "`") if top == '"'
                 else tuple(CLOSES))
        end = i + 1
        if text[i] == "\\" and top != "'":
            end += 1                                    # with the character it escapes
        elif top and text[i] == CLOSES[top]:
            nest.pop()
            if ((top in ("$(", "<(", ">(") or top == "(" and since - 1 == start)
                    and not any(opener[-1] == "(" for opener, _ in nest)
                    and text[since:i].strip() and text[since] != "("):
                held.append((since, i))
        elif text.startswith(opens, i):
            opener = next(opener for opener in opens if text.startswith(opener, i))
            end = i + len(opener)
            nest.append((opener, end))
        elif nest:
            pass                                        # as written
        elif text[i] == "#" and start == i:
            break
        elif text[i] in " \t\n|&;<>":
            end = SEPARATOR.match(text, i).end()        # blanks, or one operator
            cut = start if text[i] in "<>" and DESCRIPTOR.fullmatch(text, start, i) else i
            words += [text[start:cut], text[cut:end].strip(" \t")]
            start = end
        i = end
    return [word for word in words + [text[start:i]] if word], held


def shell_words(text):
    """The words of `text`, a line or bash's print of one (`printed`), such that two texts of
    the same words are one command: split as bash splits them (`split`), the commands a
    bracket holds read the same way in turn, and each word outside quote and bracket one word
    however it is quoted (`unquoted`), but a name bash keeps as written (`NAMES`, and a
    function's before its `()`).  A line with `[[`, whose words bash reads by their quotes,
    stays as split."""
    words, held = split(text)
    if "[[" in words:
        return words
    for since, until in reversed(held):
        text = f"{text[:since]} {' '.join(shell_words(text[since:until]))} {text[until:]}"
    words = split(text)[0] if held else words
    return [word if words[at + 1:at + 2] == ["()"] or at and words[at - 1] in NAMES
            else unquoted(word) for at, word in enumerate(words)]


def unquoted(word):
    """`word` as bash takes the quotes off it, where it holds a quote and nothing in it expands
    (`LITERAL`): its characters alone where each is `PLAIN` and they spell no `SYNTAX`, else
    in single quotes."""
    if not re.search(r"""['"\\]""", word) or not re.fullmatch(f"(?:{LITERAL.pattern})+", word):
        return word
    value = LITERAL.sub(lambda piece: piece.group(piece.lastindex), word)
    if re.fullmatch(f"{PLAIN}+", value) and value not in SYNTAX:
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def bare(words):
    """`words` (`shell_words`) without the output plumbing that ends them: each redirection of
    output, and a last pipe into `tee`.  Only one that names plain words: a substitution among
    them could run anything."""
    def plain(named):
        return not any(re.search(r"[|&;<>\n()`]", word) for word in named)
    while True:
        pipe = max((at for at, word in enumerate(words) if word in ("|", "|&")), default=0)
        if len(words) > 2 and WRITES.fullmatch(words[-2]) and plain(words[-1:]):
            words = words[:-2]
        elif pipe and words[pipe + 1:pipe + 2] == ["tee"] and plain(words[pipe + 2:]):
            words = words[:pipe]
        else:
            return words


def is_suite(line, suite):
    """Whether done-when `line` is the declared `suite`: the two are one command (`shell_words`)
    as bash reads each (`printed`; as it is written where bash prints none), once the output
    plumbing that ends each is gone (`bare`).  Any other spelling is another command here, so
    that no focused check is taken for the suite."""
    words, whole = (bare(shell_words(printed(text) or text)) for text in (line, suite))
    return bool(words) and words == whole


def rounds_refusal(value, what, budget):
    """One sentence when a round budget asked for is over the rule, else None.

    `budget`, the `review_rounds` in force (`config.policy`), is never a default to raise: a run
    that has not passed by then goes back to its orchestrator with its findings, to split or
    re-scope, and no flag carries it further.  A value that is no number is left to the check
    that says so.
    """
    try:
        rounds = int(value)
    except (TypeError, ValueError):
        return None
    if rounds <= budget:
        return None
    return (f"{what} {rounds} is over the budget: {budget} rounds, then a run goes "
            "back to its orchestrator to split or re-scope")
