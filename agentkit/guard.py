"""What a seat's tmux may not do: end another seat, or type into it; where its git may not make a
checkout: in ~/code, which holds only the owner's checkouts (`worktree_refusal`); where it may not
stash: in a repository whose checkouts share its one stash list (`stash_refusal`); and where its
scp/rsync/sftp may not put a file: on the live server (`transfer_refusal`).

A `tmux` shim first on a seat's PATH (tools/tmux-shim) runs every tmux call the seat makes, with
the final argv bash has already built -- `$(...)`, `$variables`, comments, backslash
continuations, redirects and heredocs all resolved -- so there is no shell string to parse.  It
refuses a kill (`kill-server`, `kill-session`, `kill-window`, `kill-pane`) that would end another
seat, and a type (`send-keys`, `paste-buffer`, `send-prefix`, `pipe-pane -I`) into one; otherwise
it execs the real tmux.
Each new-session also gets its creator's name in its session environment, for the tick's
cleanup of its auxiliary sessions (`orch.sweep_finished`) and of what runs on from them
(`owner.leftovers`).

What a seat starts in tmux speaks for that seat, as what it runs in its own shell does: tmux starts
a pane's process in its server's environment, not the caller's, so a `tmux new-session` the seat
ran would otherwise start an `ak run --review-pr` that knows no seat -- reviewed as someone
else's PR, merged by no one, its ending told to no one.  Each command that starts a process
(`STARTS`) gets `-e AGENTKIT_SESSION=<seat>` after its name; a `-e` of the seat's own later in the
command wins, as tmux takes the last.  Out of reach, by design: `run-shell`, `if-shell`,
`pipe-pane` and `display-popup`.

Which session a `-t` names is answered by the real tmux, with a read-only command of the SAME
target type as the one guarded -- `list-windows -t` (a session target) for `kill-session`,
`list-panes -t` (a window target) for `kill-window`, `display-message -t` (a pane target) for the
rest -- so the guard's answer is the command's own, never a hand-built copy of tmux's lookup
(AGENTS #520).  The resolver inherits the seat's `$TMUX`, so a current-relative target (`:0`, a
bare index) resolves to the seat's own session, as the real command would from the same pane.

It guards a seat's mistakes, not a seat that means to get round it; what it does not reach is by
design, and named so the claim is exact:
  * a tmux reached by an absolute path, or started before the shim was on PATH, and tmux's own
    `run-shell`/`if-shell` -- none pass through the shim;
  * a `-t` left off, or on another server -- the current pane, the seat's own on its server;
  * the commands that move, replace or respawn a pane or window -- `swap`/`move`/`join`/
    `break-pane`, `respawn-pane`/`respawn-window`, `new-window`, `swap`/`move`/`link`/
    `unlink-window`.
The bypass-proof form is a `tmux -L <seat>` socket per seat (en2f, heavier -- it restarts every
seat); this is the mistake-guard that holds a checkable claim.

A `gh` shim (tools/gh-shim) on the same PATH refuses a seat's `gh pr merge`: merging is ak's job,
once a PR passes review with green checks, and a seat lets it land through the line.  The one seat
that may run it by hand is the inbox, which `ak watch` asks before merging someone else's PR.  ak's
own merges (the lander, a review run, `merge_own_pr`) run seatless, so the shim never engages for
them.  Like the tmux guard, this catches the merge a seat reflexively types, not a seat that means
to get round it; out of reach, by design: merging through gh's API (`gh api ... pulls/N/merge`, or a
GraphQL `mergePullRequest`), a user's gh alias for `pr merge`, and gh reached by an absolute path.
It also refuses a seat's `gh pr create` whose branch adds more lines than the seat builds
(`pr_create_refusal`), before the PR exists; the review gate still holds what it does not reach.

`scp`/`rsync`/`sftp` shims on the same PATH refuse a transfer that WRITES to the live host; a read
FROM live runs, as the rulebook has a seat operate live freely, editing no file there.
`config.live_host()` names it: `live_host` in config.toml, the owner's own deploy host -- ak ships with
no alias for it and guards none until the owner names theirs (not `config.server_alias()`, the ak
coordination server, a different machine).  A file reaches the live host only through the repo, never a
seat's hand.  scp/rsync write to an operand after the first (the first operand is a download's source,
which runs); a live spec in any later operand is a write and is refused.  Testing by position, not by
the last operand, catches a write a trailing `--exclude x` or `-e ssh` (rsync permutes its options)
would hide from a last-word rule, and needs no list of each tool's value-taking options -- parsing
those out only re-derives their grammars (AGENTS #520).  sftp connects to its host operand, so a live
host there is refused.  Out of reach, by design and named: a download whose first operand is a
value-option's argument (`scp -i key live:/x .`), and a write run inside `ssh live "<command>"`, whose
remote shell tokenizes the command the shim never sees.  A transfer to any other host, a read from
live, and any transfer when the seat reaches no live host, run.

An `ssh` shim on the same PATH refuses nothing: a seat's ssh naming the live host is written down
(`live_reach`), so a turn that worked there and left its plan no open line goes back once to record
it (`stop.live_unrecorded`).  Like the scp/rsync/sftp shims it reads the final argv, never a
command's text, and with no live host named it writes nothing.

Every shim is one sh body, tools/shim (each `tools/<name>-shim` links to it, and `install_shim` links
each as `<HOME>/bin/<name>`): it runs the real binary at once for a worker and for whatever runs
seatless, and asks `main` here only for a seat's own call, so no hot call pays for a Python start.
A new shim is a link to that body and an entry in `REFUSALS`.
"""

import os
import stat
import subprocess
import sys
import time

from . import config
from .warm import TMUX_OWNER   # its home there, as the warm client imports no agentkit

ENDS = ("kill-server", "kill-session", "kill-window", "kill-pane")
TYPES = ("send-keys", "paste-buffer", "send-prefix", "pipe-pane")
VALUED = {"send-keys": "cN", "paste-buffer": "bs"}   # options besides -t that take a value
REQUIRES = {"pipe-pane": "I"}         # pipe-pane types into the pane only with -I (else it reads out)
STARTS = ("new-session", "new-window", "split-window", "respawn-pane", "respawn-window")
ALIASES = {"killp": "kill-pane", "killw": "kill-window", "send": "send-keys",
           "pasteb": "paste-buffer", "pipep": "pipe-pane", "new": "new-session",
           "neww": "new-window", "splitw": "split-window", "respawnp": "respawn-pane",
           "respawnw": "respawn-window"}
SERVER_VALUED = set("fLScT")                            # tmux server options that take a value


def tmux_owned(args):
    """Tag each new session at creation, including unnamed ones and commands chained with `;`,
    and give each command that starts a process (`STARTS`) the seat's name.

    `-e` belongs to new-session itself: no later lookup can tag the wrong session, and `-A`
    attaching an existing session leaves its ownership alone.
    """
    _, i = server_opts(args)
    result = args[:i]
    changed = False
    own = config.current_session()
    for cmd in commands(args[i:]):
        if len(result) > i:
            result.append(";")
        command = guarded(cmd[0], STARTS)
        if command == "new-session":
            cmd = [cmd[0], "-e", f"{TMUX_OWNER}={own}", *cmd[1:]]
        if command:
            cmd = [cmd[0], "-e", f"{config.SESSION_ENV}={own}", *cmd[1:]]
            changed = True
        result.extend(cmd)
    return result if changed else args


def guarded(name, known=(*ENDS, *TYPES)):
    """The guarded tmux command that word runs: a full name, an alias, or a unique prefix of one
    (tmux takes any unambiguous prefix; an ambiguous one tmux refuses, so it runs nothing)."""
    name = ALIASES.get(name, name)
    if name in known:
        return name
    hits = [k for k in known if name and k.startswith(name)]
    return hits[0] if len(hits) == 1 else None


def server_opts(args):
    """(the -L/-S server a tmux call names, the index of its first non-option word), as getopt:
    bundled booleans and a valued option's value in the same word (`-uL name`, `-Lname`)."""
    server, i = [], 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        flags, i, at = args[i][1:], i + 1, 0
        while at < len(flags):
            flag = flags[at]
            if flag in SERVER_VALUED:
                value = flags[at + 1:] or (args[i] if i < len(args) else "")
                i += not flags[at + 1:]
                if flag in ("L", "S"):
                    server += ["-" + flag, value]
                break
            at += 1
    if i < len(args) and args[i] == "--":          # tmux's end-of-options marker
        i += 1
    return server, i


def has_flag(args, letter, valued):
    """Is that boolean flag present among the command's option clusters, read as getopt (a letter
    after a valued option, or after -t, is that option's value, not a flag)?"""
    for arg in args:
        if arg == "--":
            break
        if not arg.startswith("-") or arg.startswith("--"):
            continue
        for ch in arg[1:]:
            if ch == letter:
                return True
            if ch in valued or ch == "t":     # the rest of this cluster is this option's value
                break
    return False


def options(args, valued):
    """(-t target or None, -a given, -C given) from a command's args, read as tmux's getopt: a
    valued option's value may ride in the same word (`-tname`) or be the next word (`-t name`)."""
    target, every, clear, i = None, False, False, 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        flags, i, at = args[i][1:], i + 1, 0
        while at < len(flags):
            flag = flags[at]
            if flag == "a":
                every = True
            elif flag == "C":
                clear = True
            elif flag == "t" or flag in valued:
                inline = flags[at + 1:]
                value = inline or (args[i] if i < len(args) else "")
                if not inline:
                    i += 1            # a separate value word belongs to this option, not the next
                if flag == "t":
                    target = value
                break                 # the rest of the cluster is this option's value
            at += 1
    return target, every, clear


def commands(args):
    """Each tmux command in one invocation's args.  tmux ends a command only at a word whose last
    character is an unescaped `;`; a `;` elsewhere in a word, or escaped as `\\;`, is literal."""
    current_cmd = []
    for token in args:
        if token.endswith(";") and not token.endswith("\\;"):
            head = token[:-1]
            if head:
                current_cmd.append(head)
            if current_cmd:
                yield current_cmd
            current_cmd = []
        else:
            current_cmd.append(token)
    if current_cmd:
        yield current_cmd


def sessions(tmux, server):
    """{session id: name} on that tmux server, ak's control session aside; none when there is no
    server to ask."""
    from .orch import CONTROL   # here, not at the top: orch imports this module
    try:
        proc = subprocess.run([tmux, *server, "list-sessions", "-F",
                               "#{session_id}\t#{session_name}"],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return {sid: name for sid, name in (line.split("\t", 1) for line in proc.stdout.splitlines()
                                        if "\t" in line) if name != CONTROL}


def resolve_target(tmux, server, command, target):
    """The session this command's `-t target` falls on, or "" when it names none -- asked of the
    real tmux with a read-only command of the SAME target type, so the answer is the command's own:
    a session target (`kill-session`) through `list-windows -t`, a window target (`kill-window`)
    through `list-panes -t`, a pane target (every other) through `display-message -t`.  This copies
    none of tmux's lookup (AGENTS #520), and, inheriting the seat's `$TMUX`, reads a current-relative
    target as the seat's own session."""
    if command == "kill-session":
        sub = ["list-windows", "-t", target, "-F", "#{session_name}"]
    elif command == "kill-window":
        sub = ["list-panes", "-t", target, "-F", "#{session_name}"]
    else:
        sub = ["display-message", "-p", "-t", target, "#{session_name}"]
    try:
        proc = subprocess.run([tmux, *server, *sub], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()] if proc.returncode == 0 else []
    return lines[0] if lines else ""


def seat(name):
    """Is that tmux session a seat ak keeps a record of?"""
    try:
        return config.session_path(name).exists()
    except config.Error:
        return False


def resolve(name):
    """The name a session goes by now (config's own lookup), following a rename."""
    try:
        return config.resolve_session(name)
    except (config.Error, OSError):
        return config.normalize_session(name)


def refusal(args, tmux="tmux"):
    """Why the calling seat may not run this tmux call (its argv after `tmux`), or None.  Every
    command the argv holds is checked, since tmux runs each; `tmux` is the real binary the shim
    resolves, used only to read the server, so the shim never calls itself."""
    own = config.current_session()
    if not own:
        return None
    server, i = server_opts(args)
    live = None
    for cmd in commands(args[i:]):
        command = guarded(cmd[0]) if cmd else None
        if not command:
            continue
        rest = cmd[1:]
        requires = REQUIRES.get(command)
        if requires and not has_flag(rest, requires, VALUED.get(command, "")):
            continue              # e.g. pipe-pane without -I reads the pane's output, types nothing
        if command == "kill-server":
            live = sessions(tmux, server) if live is None else live
            hit = set(live.values())
        else:
            target, every, clear = options(rest, VALUED.get(command, ""))
            if command == "kill-session" and clear:
                continue          # -C clears alerts; the session lives, so it is no kill
            has_target = target not in (None, "")
            if command == "kill-session" and every:
                live = sessions(tmux, server) if live is None else live
                keep = {resolve_target(tmux, server, command, target)} - {""} if has_target else {own}
                hit = set(live.values()) - keep   # -a ends every session but the one kept
            elif not has_target:
                continue          # no -t: the current pane, this seat's own on its server
            else:
                hit = {resolve_target(tmux, server, command, target)} - {""}
        others = sorted(n for n in hit if n and resolve(n) != own and seat(n))
        if not others:
            continue
        whose = "another session's seat" if len(others) == 1 else "other sessions' seats"
        if command in TYPES:
            return (f"ak refused `tmux {command}`: it would type into {', '.join(others)}, {whose}. "
                    "Nothing a seat writes is typed into another seat.")
        return (f"ak refused `tmux {command}`: it would end {', '.join(others)}, {whose}. A seat "
                "never ends another seat; ask the owner.")
    return None


GH_VALUED = {"-R", "--repo"}            # the gh persistent flag that takes a value before a subcommand


def gh_command(args):
    """The first two command words of a gh call (`pr merge`, `pr create`): the options between
    them are skipped, including -R/--repo's value (`gh pr -R acme/x merge 7` and
    `gh pr --repo acme/x merge 7` are merges), gh's one persistent value flag before a subcommand."""
    words, skip = [], False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in GH_VALUED:
            skip = True
            continue
        if arg.startswith("-"):             # a boolean flag, or --repo=X with the value attached
            continue
        words.append(arg)
        if len(words) == 2:
            break
    return words


# `gh pr create`'s options, as gh reads them: its switches, and those that take a value (-R/--repo
# among them), each short name by its long one.  A call holding any other -- help, or one a later
# gh adds -- runs unmeasured: what that option makes of the next word cannot be told.
PR_CREATE_SWITCHES = {"-d", "-e", "-f", "-w", "--draft", "--dry-run", "--editor", "--fill",
                      "--fill-first", "--fill-verbose", "--no-maintainer-edit", "--web"}
PR_CREATE_VALUED = {"-a": "--assignee", "-B": "--base", "-b": "--body", "-F": "--body-file",
                    "-H": "--head", "-l": "--label", "-m": "--milestone", "-p": "--project",
                    "-R": "--repo", "-r": "--reviewer", "-T": "--template", "-t": "--title",
                    "--recover": "--recover"}


def pr_create_options(args):
    """{the long name of each valued option a `gh pr create` call gives: the value gh reads, the
    last one}, or None when it holds an option not known here.  A value rides in its option's
    word (`--base=x`, `-Bx`, `-B=x`, `-fBx` after switches; `-t=` is an empty title) or is the
    next word, whatever that reads like (`--title --base=x` is a title).  A switch may carry
    its own value (`--fill=true`, `-f=false`), which ends its word."""
    letters = "".join(name[1] for name in PR_CREATE_SWITCHES if len(name) == 2)
    found, at = {}, 0
    while at < len(args) and args[at] != "--":
        word, at = args[at], at + 1
        if word.startswith("--"):
            name, attached, value = word.partition("=")
            if name in PR_CREATE_SWITCHES:
                continue
        elif word.startswith("-") and word != "-":
            rest = word[1:].lstrip(letters)
            if not rest or rest[0] == "=":
                continue
            name, attached = f"-{rest[0]}", rest[1:]
            value = attached.removeprefix("=")
        else:
            continue                                    # `pr`, `create`
        name = PR_CREATE_VALUED.get(name, name)
        if name not in PR_CREATE_VALUED.values():
            return None
        if not attached:
            if at == len(args):
                return None
            value, at = args[at], at + 1
        found[name] = value
    return found


def gh_refusal(args, gh="gh"):
    """Why the calling seat may not run this gh call (its argv after `gh`), or None.  Merging is
    ak's job once a PR passes review with green checks, so a seat's `gh pr merge` is refused -- it
    lets the work land through the line, as is a `gh pr create` too big for the seat
    (`pr_create_refusal`).  Only these commands are caught, the ones a seat reflexively
    types; merging through gh's API or a GraphQL mutation, a gh alias for it, or gh by an absolute
    path is out of reach by design (the module docstring names these).  The one seat that may run
    `gh pr merge` by hand is the inbox, which `ak watch` asks before merging someone else's PR.
    ak's own merges run through `run.tool_env`, which drops the seat's name, so the shim never
    reaches here for them."""
    own = config.current_session()
    command = gh_command(args) if own else None
    if command == ["pr", "create"]:
        return pr_create_refusal(args)
    if command != ["pr", "merge"] or own == resolve(config.inbox()):
        return None
    return ("ak refused `gh pr merge`: merging is ak's job once a PR passes review with green "
            "checks. Leave it to land through the line; a seat runs no `gh pr merge` of its own.")


def pr_create_refusal(args):
    """Why a seat may not open this pull request, or None: its branch adds more lines than the
    seat builds, as the review gate counts and limits them (`transitions.seat_lines`, with the
    project's `config.policy`), against the PR's base, so no PR is left open to close.  It reads
    `--base`/`-B` (else the default branch, origin/HEAD) and `--head`/`-H` (else the branch
    checked out).  What it cannot measure runs and meets the gate: an option it does not know
    (`pr_create_options`), a checkout of no project ak knows, a repository named by
    `--repo`/`-R` or GH_REPO (which one gh means hangs on its host settings, not on the
    checkout), a base with no `origin/` ref here, and a head that is no local branch -- a fork's
    `owner:branch`, or a detached HEAD."""
    options = pr_create_options(args)
    if options is None:
        return None
    from . import gitcall, orch, transitions     # only now: every seat's gh call starts this guard
    top = gitcall.git(os.getcwd(), "rev-parse", "--show-toplevel", check=False)
    project = top and orch.checkout_of(top)
    if not project:
        return None
    if options.get("--repo") or os.environ.get("GH_REPO"):
        return None
    base = options.get("--base")
    branch = options.get("--head") or gitcall.git(top, "symbolic-ref", "--short", "-q", "HEAD",
                                                  check=False)
    target = f"refs/remotes/origin/{base}" if base else config.RULES_REF
    head = f"refs/heads/{branch}"
    if not (branch and all(gitcall.git(top, "rev-parse", "--verify", "--quiet", ref, check=False)
                           for ref in (target, head))):
        return None
    numbers = config.policy(project)
    limit = numbers["orchestrator_lines"]
    read, over = transitions.seat_lines(top, target, head, limit)
    if not over:
        return None
    way = ("Split it into smaller PRs." if numbers["executor_lines"] == 0 else
           f"Write it as a task; `from: {branch}` keeps what was built.")
    return (f"ak refused `gh pr create`: {branch} adds {read} lines (generated files and unchanged "
            f"moves aside): too big for the seat, which builds at most {limit} added lines. {way}")


# git's options before its command that take the next word as their value
GIT_VALUED = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
              "--super-prefix", "--attr-source")


def git_refusal(args, git):
    """Why a seat's git call (its argv after `git`) may not run, or None: its command is read past
    git's own options before it, from the working directory and each `-C` among them.  An alias
    of `worktree add` or of `stash`, or a git reached by its absolute path, passes."""
    base, i = os.getcwd(), 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C" and i + 1 < len(args):
            base = os.path.join(base, args[i + 1])
        i += 2 if args[i] in GIT_VALUED else 1
    if args[i:i + 2] == ["worktree", "add"]:
        return worktree_refusal(args[i + 2:], base)
    if args[i:i + 1] == ["stash"]:
        return stash_refusal(args[:i], args[i + 1:], git)
    return None


def worktree_refusal(rest, base):
    """Why a `git worktree add` (`rest`, its argv after `add`, run from `base`) may not run, or
    None: its new checkout lands in ~/code, which holds only the owner's checkouts (owner, 5 Oct)
    -- a seat's goes under ~/.agentkit/wt.  The path is read as git reads it, past `worktree
    add`'s options (`-b`, `-B` and `--reason` take a value)."""
    from . import worktrees        # only now: every seat's git call starts this guard
    j = 0
    while j < len(rest) and rest[j].startswith("-") and rest[j] not in ("-", "--"):
        word, j = rest[j], j + 1
        if word == "--reason":
            j += 1
        elif not word.startswith("--"):
            for at, letter in enumerate(word[1:]):
                if letter in "bB":            # its value rides in this word, or is the next one
                    j += not word[at + 2:]
                    break
    j += j < len(rest) and rest[j] == "--"
    if j >= len(rest) or not worktrees.under_code(os.path.join(base, rest[j])):
        return None
    return (f"ak refused `git worktree add {rest[j]}`: ~/code holds only the owner's checkouts. "
            f"Make a seat's checkout under ~/.agentkit/wt/ instead: "
            f"`git worktree add ~/.agentkit/wt/<name> ...`.")


def stash_refusal(options, rest, git):
    """Why a `git stash` (`options`, git's own before it; `rest`, its argv after `stash`) may not
    run, or None: its repository has more than one checkout, as the real git lists them, and they
    share one stash list, so a pop, apply or drop takes the entry on top, whoever put it there.
    `list` and `show` only read it; no word, or an option, is `push`.  Where that git cannot list
    the checkouts nothing is refused, and git answers the call as typed."""
    if rest[:1] in (["list"], ["show"]):
        return None
    listed = subprocess.run([git, *options, "worktree", "list", "--porcelain"],
                            capture_output=True)
    if listed.returncode or sum(line.startswith(b"worktree ")
                                for line in listed.stdout.splitlines()) < 2:
        return None
    return ("ak refused `git stash`: this repository's checkouts share one stash list, so an entry "
            "is any checkout's to take and the one on top may not be yours. Keep the change in a "
            "file (`git diff HEAD > FILE`, and `git apply FILE` brings it back) or on a commit of "
            "its own.")


TRANSFER_SCHEMES = ("scp://", "sftp://", "rsync://", "ssh://")   # a remote spec's URI scheme


def arg_host(arg, tool):
    """The remote host an scp/rsync/sftp argument names, or "" when it names no host: a URI
    (`scheme://[user@]host[:port]/path`), an `[user@]host:path` (scp, rsync), or -- for sftp, whose
    operand is itself a host -- a bare `[user@]host`.  A local path (absolute, relative, or a bare
    word for scp/rsync) names no host."""
    for scheme in TRANSFER_SCHEMES:
        if arg.startswith(scheme):
            return arg[len(scheme):].split("/", 1)[0].split("@")[-1].split(":", 1)[0]
    if ":" in arg and not arg.startswith(("/", "./", "../")):
        return arg.split(":", 1)[0].split("@")[-1]
    if tool == "sftp":
        return arg.split("@")[-1]
    return ""


def transfer_refusal(args, real):
    """Why the calling seat may not run this scp/rsync/sftp (its argv after the command), or None.
    A file reaches the live host only through the repo, so a transfer that WRITES to the live host
    (`config.live_host()`, the ssh alias the owner set in config.toml) is refused; a read FROM live
    runs, as the rulebook has a seat operate live freely, editing no file there.

    scp and rsync write to an operand after the first: the first operand is a download's source, so a
    live spec there runs, and a live spec in any later operand is a write target and is refused.
    Testing by position, not by the last operand, catches a write that a trailing `--exclude x` or
    `-e ssh` (rsync permutes its options) would hide from a last-word rule, and needs no list of each
    tool's value-taking options -- parsing those out only re-derives their grammars (AGENTS #520).
    sftp connects to its host operand and can put files, so a live host there is refused outright.

    Out of reach, by design and named: a download whose first operand is a value-option's argument
    (`scp -i key live:/x .`, `rsync -e ssh live:/x b` -- name the key or transport in ssh config), and
    a write run inside `ssh live "..."`, whose remote shell the shim never sees."""
    own = config.current_session()
    alias = config.live_host()
    if not own or not alias:
        return None
    tool = os.path.basename(real)
    operands = [a for a in args if not a.startswith("-")]
    # sftp's operand is the host it connects to; scp/rsync write to an operand after the first.
    suspect = operands if tool == "sftp" else operands[1:]
    if any(arg_host(a, tool) == alias for a in suspect):
        return (f"ak refused `{tool}` to {alias}: a file reaches the live host only through the "
                f"repo. Commit the change and let it deploy; a seat writes nothing onto {alias} by hand.")
    return None


def live_reach(args, real):
    """None, always: a seat's ssh runs wherever it goes.  One that names the live host in any
    argument (`prod`, `deploy@prod`) is written down as reaching it, the moment kept under the
    name its harness was launched with, as its hooks keep its turn (`reached_live`)."""
    alias, launched = config.live_host(), os.environ.get(config.SESSION_ENV)
    if alias and any(arg_host(arg, "sftp") == alias for arg in args):
        path = config.seat_file("live", launched)
        tmp = path.with_name(f"{path.name}.{os.getpid()}")
        tmp.write_text(f"{time.time()}\n")
        tmp.replace(path)
    return None


def reached_live(name):
    """Whether that seat's own ssh reached the live host this turn: since the turn's start
    hooks/seat-state.sh writes in its stop file.  Both are under the name its running launch
    stamps (`plan.prompted`), so an earlier launch's reach never counts."""
    from . import plan        # only now: every seat's git call starts this guard
    turn, launched = plan.prompted(name)
    if launched is None:
        return False
    try:
        return float(config.seat_file("live", launched).read_text(encoding="utf-8")) >= turn
    except (OSError, ValueError, config.Error):
        return False


# What each shim asks: its refusal, called with the call's argv and the real binary's path.
REFUSALS = {"tmux": refusal, "gh": gh_refusal, "git": git_refusal,
            "scp": transfer_refusal, "rsync": transfer_refusal, "sftp": transfer_refusal,
            "ssh": live_reach}


def main(args):
    """Refuse or exec a seat's call; a broken guard still runs the original command."""
    name, real, *rest = args
    try:
        reason = REFUSALS[name](rest, real) if name in REFUSALS else None
        run = tmux_owned(rest) if name == "tmux" and not reason else rest
    except Exception:
        reason, run = None, rest
    if reason:
        sys.stderr.write(reason + "\n")
        return 1
    os.execv(real, [real, *run])


def shim_dir():
    """The directory whose `tmux`, `gh` and `git` are the shims: first on every seat's PATH."""
    return config.HOME / "bin"


def real(name):
    """The `name` ak's own calls run: the first on PATH that is not its shim, tested as tools/shim
    tests them, so a wrapper or a test's fake ahead of the shim still answers.  The guard is for a
    seat's own commands; asked of ak's code it cost each tmux call of a look a Python start.
    `name` itself where PATH holds no other, so the call fails as a bare one would."""
    try:
        shim = os.stat(shim_dir() / name)
    except OSError:
        shim = None
    for folder in filter(None, os.environ.get("PATH", "").split(os.pathsep)):
        found = os.path.join(folder, name)
        try:
            info = os.stat(found)
        except OSError:
            continue
        if (stat.S_ISREG(info.st_mode) and os.access(found, os.X_OK)
                and not (shim and os.path.samestat(info, shim))):
            return found
    return name


def install_shim():
    """Ensure every `tools/<name>-shim` is linked as `<HOME>/bin/<name>` (so `<name>` on a seat's
    PATH is its shim), and return their directory.  A new shim is picked up by its name alone, with
    no change here.  Idempotent: a stale or wrong link is replaced, so an upgrade that moves or adds
    a shim repoints it.  Each is the live checkout's (`versions.live`): a seat outlives any run."""
    from . import versions     # here, not at the top: each command a seat guards imports this
    link_dir = shim_dir()
    link_dir.mkdir(parents=True, exist_ok=True)
    for target in sorted((versions.live() / "tools").glob("*-shim")):
        name = target.name[: -len("-shim")]       # tmux-shim -> tmux, gh-shim -> gh
        link = link_dir / name
        try:
            if link.resolve() == target.resolve():
                continue
        except OSError:
            pass
        tmp = link.with_name(f".{name}.{os.getpid()}")
        tmp.symlink_to(target)
        os.replace(tmp, link)
    return link_dir


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
