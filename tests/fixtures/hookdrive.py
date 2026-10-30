"""Fire ak's lifecycle hooks in an answer-key Home, the way a harness fires them.

A harness learns its hooks from ak's adapter for it (install.sh runs `adapters/<harness>.sh
hooks`) and from then on runs each command registered for an event with `sh -c`, the event's
JSON on stdin, in the seat's environment, reading what each prints.  `Hooks` does the same: it
runs the adapter's `hooks` verb in the Home, reads back the file that wrote, and fires an event
at every command registered for it, one after another in the order registered.  A test then
judges the hooks by what they wrote under HOME and printed, never by which script holds them, so
a build that registers other commands passes unchanged.  A verb a harness is handed on its
command line instead (Muse's `hook`) runs through `adapter`.

The adapters are the checkout's beside the program `AK_BIN` names, or `AK_ROOT`'s; with none
there nothing installs, and every test fails.

    from fixtures.akbin import Home
    from fixtures.akseat import Seat
    from fixtures.hookdrive import Hooks
    with Home() as home:
        hooks = Hooks(home)                       # Claude's, in ~/.claude/settings.json
        fired = hooks.fire("UserPromptSubmit", {"prompt": "go"}, seat="acme")
        assert fired.code == 0 and fired.said == []
        seat = Seat(home, "beta")                 # with `pane`, a hook can look at the seat
        hooks.fire("Stop", {"background_tasks": []}, seat="beta", pane=seat)
        hooks.prompt("8080", seat)                # the owner's own words, as Claude keeps them
        read_rules(home, "acme")                  # the rulebook file its prompt named is read

`seat=None` fires outside any seat; `env` adds to the environment, and a None value removes a
variable (`{"AK_RUN_ROLE": "worker"}` is a worker's).  `transcript` writes a conversation for a
payload's `transcript_path`.  A prompt fired bare is a turn the harness began itself, a
scheduled check-in or another session's message: only `prompt` writes the owner's words into
the seat's conversation, the one place a harness says whose a turn's words are.
"""

from collections import namedtuple
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import select

from .akbin import AK, Done

ROOT = Path(os.environ.get("AK_ROOT") or Path(AK).resolve().parents[1])
# Where each harness keeps the hooks its adapter registers, under HOME.
FILES = {"claude": ".claude/settings.json", "grokbuild": ".grok/hooks/agentkit.json"}

# What the handlers of one event did together: the first failing exit code (0 when none
# failed), their stdout and stderr one after another, and each JSON object one printed, which
# is what the harness reads back as its answer.
Fired = namedtuple("Fired", "code out err said")


def install(home, harness="claude"):
    """Run the adapter's `hooks` verb in the Home, as install.sh does, and return its Done."""
    adapter = ROOT / "adapters" / f"{harness}.sh"
    if not adapter.is_file():
        return Done(127, "", f"no adapter at {adapter}\n")
    return home.run(str(adapter), "hooks")


class Hooks:
    """The hooks a harness's adapter registered in a Home; the install must succeed."""

    def __init__(self, home, harness="claude"):
        self.home, self.harness = home, harness
        self.file = home.path / FILES[harness]
        self.installed = install(home, harness)
        assert self.installed.code == 0, f"{harness} hooks: {self.installed.err}"
        assert self.settings.get("hooks"), f"{harness} hooks registered nothing in {self.file}"

    @property
    def settings(self):
        """The harness's hook file as it is now."""
        return json.loads(self.file.read_text())

    def commands(self, event, tool=None):
        """Each command registered for the event, in order; with `tool`, only those whose
        matcher takes that tool, as the harness picks them."""
        groups = (self.settings.get("hooks") or {}).get(event) or []
        return [entry["command"] for group in groups
                if tool is None or _matches(group.get("matcher"), tool)
                for entry in group.get("hooks") or [] if entry.get("type") == "command"]

    def fire(self, event, payload=None, *, seat="acme", pane=None, env=None, finished=False):
        """Run every command registered for the event with `payload` on stdin, its
        `hook_event_name` set to the event unless given, and only those a tool-matcher takes
        when it names a tool.  With `finished`, return once every process they started has
        ended, what one left running in the background too, as a harness's model goes on
        after the event before its next: each inherits a pipe, read here to its end."""
        assert self.commands(event), f"{self.harness} registers nothing for {event}"
        payload = {"hook_event_name": event, **(payload or {})}
        tool = payload.get("tool_name") or payload.get("toolName")
        end, held = os.pipe() if finished else (None, None)
        try:
            runs = [self.home.run("sh", "-c", command, input=json.dumps(payload),
                                  env=_env(self.home, seat, pane, env), keep=(held,) * finished)
                    for command in self.commands(event, tool)]
        finally:
            if finished:
                os.close(held)
        if finished:
            _drained(end)
        return _fired(runs)

    def prompt(self, text, seat):
        """The owner submits `text` in a Claude Code seat of tests/fixtures/akseat.py: Claude
        writes it into the seat's conversation, under ~/.claude/projects, and fires
        UserPromptSubmit in the seat's pane."""
        assert self.harness == "claude", f"{self.harness} keeps no conversation here"
        # Claude Code files a directory's conversations under it with each character not an
        # ASCII letter or digit a hyphen; past 200 it adds a hash, which no Home path needs.
        project = "".join(c if c.isascii() and c.isalnum() else "-" for c in str(seat.cwd))
        assert len(project) <= 200, project
        path = (self.home.path / ".claude" / "projects" / project
                / f"{seat.record['conversation']}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with path.open("a") as conversation:
            conversation.write(json.dumps({"type": "user", "timestamp": at, "message": {
                "role": "user", "content": text}}) + "\n")
        return self.fire("UserPromptSubmit", {"prompt": text}, seat=seat.name, pane=seat)


def adapter(home, harness, *args, payload=None, seat="acme", pane=None, env=None):
    """Run `adapters/<harness>.sh ARGS` as its harness runs a hook verb it was handed: the
    event's JSON on stdin, in the seat's environment."""
    run = home.run("bash", str(ROOT / "adapters" / f"{harness}.sh"), *args,
                   input=json.dumps(payload or {}), env=_env(home, seat, pane, env))
    return _fired([run])


def read_rules(home, seat):
    """What a seat's model does with a prompt naming its rulebook's file, too long for the
    prompt to carry (tests/test_key_rulebook_news_too_long.py): runs the `ak orch rules CODE`
    on that file's last line, in the seat."""
    last = (home.path / f".agentkit/state/change-{seat}.md").read_text().rstrip("\n")
    words = last.rsplit("\n", 1)[-1].split()
    assert words[:3] == ["ak", "orch", "rules"], last[-200:]
    done = home.ak(*words[1:], env={"AGENTKIT_SESSION": seat})
    assert done.code == 0, done.err


def transcript(home, name, *entries):
    """Write a conversation as Claude Code keeps one and return its path, for a payload's
    `transcript_path`: a string is a message the model said, a dict a line as it is."""
    lines = [entry if isinstance(entry, dict) else
             {"type": "assistant", "message": {"role": "assistant",
                                               "content": [{"type": "text", "text": entry}]}}
             for entry in entries]
    path = home.write(f"transcripts/{name}.jsonl",
                      "".join(json.dumps(line) + "\n" for line in lines))
    return str(path)


def _matches(matcher, tool):
    return not matcher or matcher == "*" or re.fullmatch(matcher, tool) is not None


def _env(home, seat, pane, env):
    """A seat's harness hands its hooks the seat's name and, inside its tmux pane, that pane."""
    extra = {"AGENTKIT_SESSION": seat}
    if pane is not None:
        done = home.tmux("display-message", "-p", "-t", pane.pane,
                         "#{socket_path},#{pid},#{session_id}")
        assert done.code == 0, done.err
        extra.update(TMUX=done.out.strip().replace("$", ""), TMUX_PANE=pane.pane)
    return {**extra, **(env or {})}


def _drained(end, bound=120):
    """Read a pipe until the last process holding it has ended; a hang fails the test."""
    with os.fdopen(end, "rb", buffering=0) as pipe:
        while True:
            assert select.select([pipe], [], [], bound)[0], \
                f"a process a hook started still runs after {bound} s"
            if not pipe.read(4096):
                return


def _fired(runs):
    said = []
    for run in runs:
        try:
            printed = json.loads(run.out)
        except ValueError:
            continue
        if isinstance(printed, dict):
            said.append(printed)
    return Fired(next((run.code for run in runs if run.code), 0),
                 "".join(run.out for run in runs), "".join(run.err for run in runs), said)
