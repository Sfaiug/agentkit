"""What a seat's shell may not run: the rules its harness asks before every command starts.

hooks/seat-guard.sh hands `main` the harness's PreToolUse payload; a rule reads the command's
words and returns why it is refused, in plain words, or nothing.  Each adapter whose harness
has a blocking pre-command hook installs it; elsewhere the rule is only in the seat's rulebook.
It guards against a seat's mistakes, not against a seat that means to get round it.
"""

import fnmatch
import json
import os
import shlex
import subprocess
import sys

from . import config

KILLS = ("kill-server", "kill-session", "kill-window", "kill-pane")
ALIASES = {"killp": "kill-pane", "killw": "kill-window"}
BREAKS = {"&&", "||", "|", "|&", "&", "(", ")", "\n"}   # where a shell starts another command
VALUED = {"-L", "-S", "-f", "-c", "-T"}                   # tmux's own options that take a value


def words(command):
    """The shell words of a command; a quoted word holding a tmux call is scanned as one too."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace, lexer.whitespace_split = " \t\r", True
    try:
        found = list(lexer)
    except ValueError:                    # unbalanced quotes: the shell refuses it anyway
        found = command.split()
    out = []
    for word in found:
        out.append(word)
        if "tmux" in word and word.strip() != word.strip().split()[0]:   # `bash -c '...'`
            out += ["\n", *words(word), "\n"]
    return out


def tmux_calls(tokens):
    """(server options, command, its arguments) for each tmux command the words run."""
    i = 0
    while i < len(tokens):
        if os.path.basename(tokens[i]) != "tmux":
            i += 1
            continue
        i, server = i + 1, []
        while i < len(tokens) and tokens[i].startswith("-") and tokens[i] not in BREAKS:
            flag, i = tokens[i], i + 1
            if flag in VALUED and i < len(tokens):
                server += [flag, tokens[i]] if flag in ("-L", "-S") else []
                i += 1
            elif flag[:2] in ("-L", "-S") and len(flag) > 2:
                server += [flag[:2], flag[2:]]
        while i < len(tokens) and tokens[i] not in BREAKS:
            name, args, i = tokens[i], [], i + 1
            while i < len(tokens) and tokens[i] not in BREAKS and tokens[i] != ";":
                args.append(tokens[i])
                i += 1
            yield server, name, args
            i += i < len(tokens) and tokens[i] == ";"


def kill(name):
    """The kill command tmux runs for that word: its full name, an alias or a unique prefix."""
    name = ALIASES.get(name, name)
    hits = [k for k in KILLS if k.startswith(name)] if name.startswith("kill-") else []
    return name if name in KILLS else (hits[0] if len(hits) == 1 else None)


def options(args):
    """(-t target or None, -a given) from a kill command's arguments, read as tmux's getopt."""
    target, every, i = None, False, 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        flags, i = args[i][1:], i + 1
        for at, flag in enumerate(flags):
            if flag == "a":
                every = True
            elif flag == "t":
                target = flags[at + 1:] or (args[i] if i < len(args) else "")
                i += not flags[at + 1:]
                break
    return target, every


def sessions(server):
    """{session id: name} on that tmux server; none when there is no server to ask."""
    try:
        proc = subprocess.run(["tmux", *server, "list-sessions", "-F",
                               "#{session_id}\t#{session_name}"],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return dict(line.split("\t", 1) for line in proc.stdout.splitlines() if "\t" in line)


def named(server, target, live):
    """The sessions a target may name, by tmux's own order: an id, the exact name, else every
    name it is a prefix or a pattern of (tmux takes one of them, or refuses if there are two)."""
    if target[:1] in ("%", "@"):
        try:
            proc = subprocess.run(["tmux", *server, "display-message", "-p", "-t", target,
                                   "#{session_name}"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return set()
        return {proc.stdout.strip()} - {""}
    if target[:1] == "$":
        return {live[target]} if target in live else set()
    names = set(live.values())
    if target.startswith("="):
        return {target[1:]} & names
    if target in names:
        return {target}
    return {name for name in names if name.startswith(target) or fnmatch.fnmatchcase(name, target)}


def seat(name):
    """Is that tmux session a seat ak keeps a record of?"""
    try:
        return config.session_path(name).exists()
    except config.Error:
        return False


def another_seats_tmux(tokens, env):
    """A seat never ends another seat: no kill of its tmux session, window, pane or server."""
    own = config.normalize_session(env.get(config.SESSION_ENV, ""))
    for server, name, args in tmux_calls(tokens):
        command = kill(name)
        if not command:
            continue
        live = sessions(server)
        if command == "kill-server":
            hit = set(live.values())
        else:
            target, every = options(args)
            if target is None or target in ("", "="):
                hit = set(live.values()) if every and command == "kill-session" else set()
            else:
                # a window or pane named without its session's colon may be a session's name
                hit = named(server, target.split(":", 1)[0] if ":" in target else target, live)
                if every and command == "kill-session":
                    hit = set(live.values()) - hit
        others = sorted(n for n in hit if config.normalize_session(n) != own and seat(n))
        if others:
            whose = "another session's seat" if len(others) == 1 else "other sessions' seats"
            return (f"ak refused this command: `tmux {command}` would end {', '.join(others)}, "
                    f"{whose}. A seat never ends another seat; ask it with "
                    f"`ak tell {others[0]} \"...\"` or ask the owner.")
    return None


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
