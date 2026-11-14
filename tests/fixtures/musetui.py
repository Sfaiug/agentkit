"""The seat's Muse a fake `muse` on a Home's PATH starts, for a seat `ak orch` opens on it.

    python3 ROOT/muse-bin-1.4.12 ROOT SCREEN MUSE-ARGS...

It opens the session `resume` names, or a new one, fires each SessionStart hook its line carries
as Muse 1.4.12 does -- its own child, `sh -c`, the event's JSON on stdin, none of the seat's
environment but the Home's tmux server -- says which in ROOT/<seat>.json, and shows SCREEN,
keeping what is typed into ROOT/<seat>.typed (akpane.py).  `fire` has it fire one more event
that way, through the hooks its line carries for that event, and `stop` a turn's end in a
session, as Muse 1.4.12 handed it (muse-hook-payloads.jsonl).  `install` names it as Muse's
launcher execs its build, `muse-bin-<build>`, which ak tells the seat's Muse by.

    from fixtures import musetui
    musetui.install(home)                          # with `screen`, the pane it shows
    ...                                            # ak orch acme, on a terminal
    started = musetui.started(home, "acme")        # {argv, pid, session}, once it has
    musetui.stop(home, "acme", started["session"])
"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time
import uuid

HERE = Path(__file__).resolve().parent      # past the build's name, which links here
BUILD = "muse-bin-1.4.12"
ENDED = {event["hook_event_name"]: {key: value for key, value in event.items() if key != "cwd"}
         for event in map(json.loads, (HERE / "muse-hook-payloads.jsonl").read_text().splitlines())
         if event["hook_event_name"] in ("Stop", "Interrupt")}    # a turn's end, as 1.4.12 named it
# muse: the schema of one that runs hooks, and this TUI, the one call made on a terminal.
# Anything else fails, as offline.
MUSE = """#!/bin/sh
if [ "$1 $2 $3" = "schema generate-json-schema --out" ]; then
  exec printf '%s' '{{"enum": ["sessionStart", "stop", "notification"]}}' >"$4/msp.schema.json"
fi
[ -t 0 ] || exit 1
exec {python} {tui} {root} {screen} "$@"
"""


def install(home, screen=HERE / "muse-prompt-pane.txt"):
    """A fake `muse` first on the Home's PATH, whose TUI shows the text of the file `screen` at,
    again whenever it changes: by default Muse's prompt."""
    tui = home.root / BUILD
    if not tui.exists():
        tui.symlink_to(HERE / Path(__file__).name)
    home.fake("muse", MUSE.format(python=shlex.quote(sys.executable),
                                  tui=shlex.quote(str(tui)), root=shlex.quote(str(home.root)),
                                  screen=shlex.quote(str(screen))))


def started(home, seat, bound=60):
    """What the seat's Muse said it opened, once it has: {argv, pid, session}.  Each start is
    told once, so the next call waits for the seat's next Muse."""
    said = home.root / f"{seat}.json"
    deadline = time.monotonic() + bound
    while not said.exists() or not said.read_text().endswith("}"):
        assert time.monotonic() < deadline, f"no muse started for {seat}"
        time.sleep(0.05)
    told = json.loads(said.read_text())
    said.unlink()
    return told


def fire(home, seat, payload, bound=60):
    """The seat's Muse fires that event through the hooks its line carries for it, and returns
    once they have run."""
    asked, fired = home.root / f"{seat}.fire", home.root / f"{seat}.fired"
    before = _count(fired)
    with asked.open("a") as out:
        out.write(json.dumps(payload) + "\n")
    deadline = time.monotonic() + bound
    while _count(fired) <= before:
        assert time.monotonic() < deadline, f"{seat}'s muse never fired {payload}"
        time.sleep(0.05)


def stop(home, seat, session, event="Stop"):
    """The seat's Muse ends a turn in that session: its Stop names it, or an Esc's Interrupt."""
    fire(home, seat, {**ENDED[event], "session_id": session})


def _count(path):
    return path.read_text().count("\n") if path.exists() else 0


def main(root, screen, *argv):
    root, home = Path(root), Path(os.environ["HOME"])
    seat = os.environ["AGENTKIT_SESSION"]
    asked, fired = root / f"{seat}.fire", root / f"{seat}.fired"
    # what Muse hands a hook, and the Home's tmux server, which a real HOME names alone
    # (agentkit/orch.py `home_socket`)
    env = {"HOME": str(home), "PATH": os.environ["PATH"],
           "AGENTKIT_TMUX_SOCKET": os.environ["AGENTKIT_TMUX_SOCKET"]}

    def hooks(payload):
        for flag, value in zip(argv, argv[1:]):
            if flag == "-c" and value.startswith(f"hooks.{payload['hook_event_name']}="):
                for group in json.loads(value.partition("=")[2]):
                    for hook in group["hooks"]:
                        subprocess.run(["sh", "-c", hook["command"]], input=json.dumps(payload),
                                       text=True, env=env)

    def listen(seen):
        while True:
            for line in (asked.read_text().splitlines() if asked.exists() else [])[seen:]:
                seen += 1
                hooks({"cwd": os.getcwd(), "transcript_path": None, **json.loads(line)})
                with fired.open("a") as out:
                    out.write(line + "\n")
            time.sleep(0.05)

    session = argv[argv.index("resume") + 1] if "resume" in argv else str(uuid.uuid4())
    hooks({"hook_event_name": "SessionStart", "session_id": session, "cwd": os.getcwd(),
           "source": "resume" if "resume" in argv else "startup", "transcript_path": None,
           "model": "unknown"})
    threading.Thread(target=listen, args=(_count(asked),), daemon=True).start()
    (root / f"{seat}.json").write_text(json.dumps({"argv": list(argv), "pid": os.getpid(),
                                                   "session": session}))
    import akpane
    akpane.main(screen, root / f"{seat}.typed")


if __name__ == "__main__":
    main(*sys.argv[1:])
