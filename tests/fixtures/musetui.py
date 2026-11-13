"""The seat's Muse a fake `muse` on a Home's PATH starts, for a seat `ak orch` opens on it.

    python3 ROOT/muse-bin-1.4.12 ROOT SCREEN MUSE-ARGS...

It opens the session `resume` names, or a new one, fires each SessionStart hook its line carries
as Muse 1.4.12 does -- its own child, `sh -c`, the event's JSON on stdin, none of the seat's
environment -- lists the session in Muse's registry under its own pid (`register`), says which
in ROOT/<seat>.json, and shows SCREEN, keeping what is typed into ROOT/<seat>.typed (akpane.py).
`install` names it as Muse's launcher execs its build, `muse-bin-<build>`, which ak tells the
seat's Muse by.

    from fixtures import musetui
    musetui.install(home)                          # with `screen`, the pane it shows
    ...                                            # ak orch acme, on a terminal
    started = musetui.started(home, "acme")        # {argv, pid, session}, once it has
"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent      # past the build's name, which links here
BUILD = "muse-bin-1.4.12"
REGISTRY = ".local/share/muse/runtime/muse/sessions"    # under HOME
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


def register(home, session, pid):
    """Muse's registry under the HOME `home` lists `session` as the one process `pid` holds: in
    place of the one it held before, as Muse's `/new` moves it."""
    registry = Path(home) / REGISTRY
    registry.mkdir(parents=True, exist_ok=True)
    for entry in registry.glob("*.json"):
        if json.loads(entry.read_text())["process_generation_hint"] == f"pid={pid}":
            entry.unlink()
    (registry / f"{session}.json").write_text(json.dumps({
        "schema_version": 1, "session_id": session,
        "endpoint_hint": f"ms-{uuid.uuid4().hex[:12]}.sock",
        "target_eligibility": "message_capable", "process_generation_hint": f"pid={pid}"}))


def main(root, screen, *argv):
    root, home = Path(root), Path(os.environ["HOME"])
    seat = os.environ["AGENTKIT_SESSION"]
    session = argv[argv.index("resume") + 1] if "resume" in argv else str(uuid.uuid4())
    payload = json.dumps({"hook_event_name": "SessionStart", "session_id": session,
                          "source": "resume" if "resume" in argv else "startup",
                          "cwd": os.getcwd(), "transcript_path": None, "model": "unknown"})
    for flag, value in zip(argv, argv[1:]):
        if flag == "-c" and value.startswith("hooks.SessionStart="):
            for group in json.loads(value.partition("=")[2]):
                for hook in group["hooks"]:
                    subprocess.run(["sh", "-c", hook["command"]], input=payload, text=True,
                                   env={"HOME": str(home), "PATH": os.environ["PATH"]})
    register(home, session, os.getpid())
    (root / f"{seat}.json").write_text(json.dumps({"argv": list(argv), "pid": os.getpid(),
                                                   "session": session}))
    import akpane
    akpane.main(screen, root / f"{seat}.typed")


if __name__ == "__main__":
    main(*sys.argv[1:])
