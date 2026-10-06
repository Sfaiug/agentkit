"""What a seat's shell may not run: the rules its harness asks before every command starts.

hooks/seat-guard.sh hands `main` the harness's PreToolUse payload; a rule reads the command's
words and returns why it is refused, in plain words, or nothing.  Each adapter whose harness
has a blocking pre-command hook installs it; elsewhere the rule is only in the seat's rulebook.
It guards against a seat's mistakes, not against a seat that means to get round it: it reads
the command as plain shell words and resolves a tmux target through tmux itself, so a kill hidden
behind a shell expansion (a `$(...)` substitution, a `$variable`), tmux's own command language
(`run-shell`, `if-shell`, a chained command), a bundled shell option (`bash -lc`), a wrapper's
own options, or a window linked across sessions, is beyond it, as the rulebook also says.
"""

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys

from . import config

KILLS = ("kill-server", "kill-session", "kill-window", "kill-pane")
ALIASES = {"killp": "kill-pane", "killw": "kill-window"}
SHELL_BREAK = set(";&|()\n")       # a token of only these is where the shell starts a command
SERVER_VALUED = set("fLScT")       # tmux's server options that take a value, as getopt reads them
SHELLS = {"bash", "sh", "dash", "zsh", "ksh"}   # `<shell> -c '<script>'` runs that script
HEREDOC = re.compile(r"^<<-?(.*)$")             # `cat <<EOF`: its body is text, not commands


def words(command):
    """The shell words of a command; a run of shell punctuation is its own token."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace, lexer.whitespace_split = " \t\r", True
    try:
        return list(lexer)
    except ValueError:                    # unbalanced quotes: the shell refuses it anyway
        return command.split()


def is_break(token):
    """A token the shell reads as a command separator (`;`, `&&`, `|`, a newline, a run of them)."""
    return bool(token) and all(ch in SHELL_BREAK for ch in token)


def server_opts(tokens, i):
    """(the -L/-S server a tmux call names, the index after its server options), read as getopt:
    bundled booleans and a valued option's value in the same word (`-uL name`, `-Lname`)."""
    server = []
    while i < len(tokens) and tokens[i].startswith("-") and tokens[i] != "--" \
            and not is_break(tokens[i]):
        flags, i, at = tokens[i][1:], i + 1, 0
        while at < len(flags):
            flag = flags[at]
            if flag in SERVER_VALUED:
                value = flags[at + 1:] or (tokens[i] if i < len(tokens) else "")
                i += not flags[at + 1:]
                if flag in ("L", "S"):
                    server += ["-" + flag, value]
                break
            at += 1
    return server, i


def strip_heredocs(tokens):
    """The tokens with every `<<DELIM` ... `DELIM` body removed: its lines are text, not commands."""
    out, i, n = [], 0, len(tokens)
    while i < n:
        out.append(tokens[i])
        here = HEREDOC.match(tokens[i])
        i += 1
        if not here:
            continue
        delim = here.group(1).strip().strip("'\"")
        if not delim and i < n:           # `<< DELIM` with a space: the delimiter is the next word
            delim = tokens[i].strip().strip("'\"")
            out.append(tokens[i])
            i += 1
        while i < n and tokens[i] != "\n":   # the rest of the command's own line stays
            out.append(tokens[i])
            i += 1
        if i < n:
            out.append(tokens[i])         # the newline that ends the command line
            i += 1
        while i < n and tokens[i].strip() != delim:   # drop the body up to the delimiter line
            i += 1
        i += 1                            # and the delimiter line itself
    return out


def tmux_calls(tokens):
    """(server options, subcommand, its args) for each tmux command the shell actually runs.

    Only a word in command position -- the start, or after a separator, past assignments -- is a
    command; a `tmux` among another command's arguments (an echo, a grep) runs nothing.  A
    `<shell> -c '<script>'` is scanned as the commands it runs, and a heredoc body is skipped.
    """
    tokens = strip_heredocs(tokens)
    i, n, at_command = 0, len(tokens), True
    while i < n:
        token = tokens[i]
        if is_break(token):
            at_command, i = True, i + 1
            continue
        if not at_command:
            i += 1
            continue
        if re.match(r"\w+=", token):      # VAR=value before the command
            i += 1
            continue
        base = os.path.basename(token)
        if base != "tmux":
            if base in SHELLS:            # a -c '<script>' argument is run
                at = i + 1
                while at < n and not is_break(tokens[at]):
                    if tokens[at] == "-c" and at + 1 < n:
                        yield from tmux_calls(words(tokens[at + 1]))
                        break
                    at += 1
            while i < n and not is_break(tokens[i]):   # its other arguments are not commands
                i += 1
            at_command = False
            continue
        i += 1                            # a tmux invocation: its server options, then its command
        server, i = server_opts(tokens, i)
        if i < n and tokens[i] == "--":   # tmux's end-of-options marker, before the subcommand
            i += 1
        if i < n and not is_break(tokens[i]):
            name, args, i = tokens[i], [], i + 1
            while i < n and not is_break(tokens[i]):
                args.append(tokens[i])
                i += 1
            yield server, name, args
        at_command = False


def kill(name):
    """The kill command tmux runs for that word: its full name, an alias or a unique prefix."""
    name = ALIASES.get(name, name)
    hits = [k for k in KILLS if k.startswith(name)] if name.startswith("kill-") else []
    return name if name in KILLS else (hits[0] if len(hits) == 1 else None)


def kill_options(args):
    """(-t target or None, -a given, -C given) from a kill command's args, read as tmux's getopt.
    `-C` clears a session's alerts and leaves it alive, so it is no kill."""
    target, every, clear, i = None, False, False, 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        flags, i, at = args[i][1:], i + 1, 0
        while at < len(flags):
            flag = flags[at]
            if flag == "a":
                every = True
            elif flag == "C":
                clear = True
            elif flag == "t":
                target = flags[at + 1:] or (args[i] if i < len(args) else "")
                i += not flags[at + 1:]
                break
            at += 1
    return target, every, clear


def sessions(server):
    """{session id: name} on that tmux server; none when there is no server to ask."""
    try:
        proc = subprocess.run(["tmux", *server, "list-sessions", "-F",
                               "#{session_id}\t#{session_name}"],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return dict(line.split("\t", 1) for line in proc.stdout.splitlines() if "\t" in line)


def display(server, target):
    """The session name tmux resolves a target to (the current one when target is None), or ""."""
    cmd = ["tmux", *server, "display-message", "-p"]
    if target is not None:
        cmd += ["-t", target]
    try:
        proc = subprocess.run(cmd + ["#{session_name}"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def target_sessions(server, target, live):
    """The session names a kill's `-t target` may hit, by tmux's own target lookup: an id, a
    contextual or marked target tmux resolves, the exact name, else every name it is a prefix
    or pattern of.  A target whose session part is empty (`:0`) is the current session."""
    sess = target.split(":", 1)[0] if ":" in target else target
    if sess == "" or sess[:1] in ("%", "@", "~", "{"):
        return {display(server, target if sess else None)} - {""}
    if sess[:1] == "$":
        return {live[sess]} if sess in live else set()
    names = set(live.values())
    if sess.startswith("="):
        return {sess[1:]} & names
    if sess in names:
        return {sess}
    hits = {name for name in names if name.startswith(sess) or fnmatch.fnmatchcase(name, sess)}
    # an unmatched target may still be one tmux resolves: a client's tty, a window index
    return hits or {display(server, target)} - {""}


def seat(name):
    """Is that tmux session a seat ak keeps a record of?"""
    try:
        return config.session_path(name).exists()
    except config.Error:
        return False


def resolved(name):
    """The name a session goes by now, following a rename; the name itself when it cannot say."""
    try:
        return config.resolve_session(name)
    except (config.Error, OSError):
        return config.normalize_session(name)


def another_seats_tmux(tokens, env):
    """A seat never ends another seat: no kill of its tmux session, window, pane or server."""
    own = resolved(env.get(config.SESSION_ENV, ""))
    for server, name, args in tmux_calls(tokens):
        command = kill(name)
        if not command:
            continue
        live = sessions(server)
        if command == "kill-server":
            hit = set(live.values())
        else:
            target, every, clear = kill_options(args)
            if command == "kill-session" and clear:
                continue                  # -C clears alerts; the session lives, so it is no kill
            if command == "kill-session" and every:
                keep = target_sessions(server, target, live) if target else current(server)
                hit = set(live.values()) - keep
            elif target in (None, "", "="):
                # a kill with no target ends the current session, or the current window or pane,
                # all of which belong to the current session
                hit = current(server)
            else:
                hit = target_sessions(server, target, live)
        others = sorted(n for n in hit if n and resolved(n) != own and seat(n))
        if others:
            whose = "another session's seat" if len(others) == 1 else "other sessions' seats"
            return (f"ak refused this command: `tmux {command}` would end {', '.join(others)}, "
                    f"{whose}. A seat never ends another seat; ask it with "
                    f"`ak tell {others[0]} \"...\"` or ask the owner.")
    return None


def current(server):
    """The current session on that server, as a set: what a kill with no target ends."""
    return {display(server, None)} - {""}


RULES = (another_seats_tmux,)


def refusal(command, env=os.environ):
    """Why this seat may not run that shell command, or None."""
    tokens = words(command)
    for rule in RULES:
        reason = rule(tokens, env)
        if reason:
            return reason
    return None


def main():
    """Read a PreToolUse payload; print the harness's refusal for a command a rule refuses."""
    try:
        payload = json.load(sys.stdin)
        command = (payload.get("tool_input") or {}).get("command")
        reason = refusal(command) if isinstance(command, str) else None
    except Exception:                    # a guard that fails stops no seat's every command
        return
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": reason}}))
