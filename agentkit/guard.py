"""What a seat's tmux may not do: end another seat, or type into it.

A `tmux` shim first on a seat's PATH (tools/tmux-shim) runs every tmux call the seat makes, with
the final argv bash has already built -- `$(...)`, `$variables`, comments, backslash
continuations, redirects and heredocs all resolved -- so there is no shell string to parse.  It
refuses a kill (`kill-server`, `kill-session`, `kill-window`, `kill-pane`) that would end another
seat, and a type (`send-keys`, `paste-buffer`, `send-prefix`, `pipe-pane -I`) into one; otherwise
it execs the real tmux.

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

Every shim runs through `agentkit.shim` (which imports the guard lazily, so a guard it cannot
import stops no seat's command), and `install_shim` links each `tools/<name>-shim` as
`<HOME>/bin/<name>`, so a new shim needs no change there.
"""

import os
import subprocess

from . import config

ENDS = ("kill-server", "kill-session", "kill-window", "kill-pane")
TYPES = ("send-keys", "paste-buffer", "send-prefix", "pipe-pane")
VALUED = {"send-keys": "cN", "paste-buffer": "bs"}   # options besides -t that take a value
REQUIRES = {"pipe-pane": "I"}         # pipe-pane types into the pane only with -I (else it reads out)
ALIASES = {"killp": "kill-pane", "killw": "kill-window", "send": "send-keys",
           "pasteb": "paste-buffer", "pipep": "pipe-pane"}
SERVER_VALUED = set("fLScT")                            # tmux server options that take a value


def guarded(name):
    """The guarded tmux command that word runs: a full name, an alias, or a unique prefix of one
    (tmux takes any unambiguous prefix; an ambiguous one tmux refuses, so it runs nothing)."""
    name = ALIASES.get(name, name)
    known = (*ENDS, *TYPES)
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
    """{session id: name} on that tmux server; none when there is no server to ask."""
    try:
        proc = subprocess.run([tmux, *server, "list-sessions", "-F",
                               "#{session_id}\t#{session_name}"],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return dict(line.split("\t", 1) for line in proc.stdout.splitlines() if "\t" in line)


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
                    f"Tell it instead: `ak tell {others[0]} \"...\"`.")
        return (f"ak refused `tmux {command}`: it would end {', '.join(others)}, {whose}. A seat "
                f"never ends another seat; ask it with `ak tell {others[0]} \"...\"` or ask the owner.")
    return None


GH_VALUED = {"-R", "--repo"}            # the gh persistent flag that takes a value before a subcommand


def gh_merges(args):
    """Does this gh call run `pr merge`?  Its first two command words are `pr` then `merge`; the
    options between them are skipped, including -R/--repo's value (`gh pr -R acme/x merge 7` and
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
    return words == ["pr", "merge"]


def gh_refusal(args, gh="gh"):
    """Why the calling seat may not run this gh call (its argv after `gh`), or None.  Merging is
    ak's job once a PR passes review with green checks, so a seat's `gh pr merge` is refused -- it
    lets the work land through the line.  Only this command is caught, the one a seat reflexively
    types; merging through gh's API or a GraphQL mutation, a gh alias for it, or gh by an absolute
    path is out of reach by design (the module docstring names these).  The one seat that may run
    `gh pr merge` by hand is the inbox, which `ak watch` asks before merging someone else's PR.
    ak's own merges run through `run.tool_env`, which drops the seat's name, so the shim never
    reaches here for them."""
    own = config.current_session()
    if not own or not gh_merges(args):
        return None
    if own == resolve(config.inbox()):
        return None
    return ("ak refused `gh pr merge`: merging is ak's job once a PR passes review with green "
            "checks. Leave it to land through the line; a seat runs no `gh pr merge` of its own.")


def shim_dir():
    """The directory whose `tmux` and `gh` are the shims: first on every seat's PATH."""
    return config.HOME / "bin"


def install_shim():
    """Ensure every `tools/<name>-shim` is linked as `<HOME>/bin/<name>` (so `<name>` on a seat's
    PATH is its shim), and return their directory.  A new shim is picked up by its name alone, with
    no change here.  Idempotent: a stale or wrong link is replaced, so an upgrade that moves or adds
    a shim repoints it."""
    link_dir = shim_dir()
    link_dir.mkdir(parents=True, exist_ok=True)
    for target in sorted((config.REPO / "tools").glob("*-shim")):
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
