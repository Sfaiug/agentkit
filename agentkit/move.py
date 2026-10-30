"""`ak move ALIAS`: copy this account's home to the same path on the machine `ssh ALIAS` reaches.

It hides rsync's flags and the refusals.  The whole home goes, so nothing ak no longer names is
left behind, but what each machine keeps of its own (`KEPT`), neither sent nor deleted there;
`--delete` mirrors deletions with no memory of earlier passes, so a repeat sends only what changed.
A pass made while ak runs gets the bulk across and may tear a file being written: the handover's
last pass, with ak stopped, is the one the other machine carries on from.
"""

import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from . import browser, command_help, config

KEYS = Path.home() / ".ssh/authorized_keys"     # the keys that reach that machine
PROFILE = browser.BRIDGE / "profile"
# ak's tmp folder, the keys, and the profile's lock files, which tie it to the Chromium running
# on its own machine.  Sockets, pipes and devices are not sent either (`--no-D`).
KEPT = (config.TMP, KEYS, *(PROFILE / lock for lock in ("SingletonLock", "SingletonSocket",
                                                         "SingletonCookie")))
# What is kept are names, and `--delete` would go past a link to what it reaches: a link at or
# above one of these, on either machine, refuses the copy.  A lock file is a link by nature.
ASKED = (config.TMP, KEYS, PROFILE)
TICK = r"#+[[:space:]]*agentkit[[:space:]]+watch([[:space:]]|$)"   # install.sh's CRON_MATCH
VANISHED = 24   # rsync's exit for a file gone between its listing and its sending


def says(shell, script):
    """What a machine's shell, in its home, says of it, a fact a line: first `link PATH` for
    each path at or above what is asked that is a link, then what `script` says."""
    home = Path.home()
    parts = sorted({part.relative_to(home) for path in ASKED for part in (path, *path.parents)
                    if part.is_relative_to(home) and part != home})
    done = subprocess.run([*shell, shlex.join(["sh", "-c", f"""cd || exit
for part in {shlex.join(map(str, parts))}; do [ ! -L "$part" ] || echo "link $part"; done
{script}"""])], stdout=subprocess.PIPE, text=True)
    if done.returncode:
        raise config.Error(f"`{shlex.join(shell)}` failed")
    return done.stdout.splitlines()


def main(argv):
    if command_help.show("move", argv):
        return 0
    if len(argv) != 1 or argv[0].startswith("-"):
        raise config.Error(command_help.COMMANDS["move"][0])
    alias, home = argv[0], Path.home()
    refused = [f"~/{fact[5:]} is a link here" for fact in says(["sh", "-c"], "")]
    if not refused:
        config.TMP.mkdir(parents=True, exist_ok=True)
        # a name only this run has made: a machine whose home holds it shares this home
        with tempfile.NamedTemporaryFile(dir=config.TMP) as token:
            facts = says(["ssh", alias], f"""printf 'home %s\\n' "$HOME"
[ ! -e {shlex.quote(str(Path(token.name).relative_to(home)))} ] || echo here
if command -v crontab >/dev/null; then
  tab=$(crontab -l) || echo tick
  ! printf '%s\\n' "$tab" | grep -qE {shlex.quote(TICK)} || echo tick
fi""")
        refused += [f"{alias} is this machine"] * ("here" in facts)
        refused += [f"the home on {alias} is not {home}"] * (f"home {home}" not in facts)
        refused += [f"ak's tick is in the crontab on {alias}, or that crontab cannot be "
                    "read"] * ("tick" in facts)
        refused += [f"~/{fact[5:]} is a link on {alias}" for fact in facts
                    if fact.startswith("link ")]
    for reason in refused:
        print(f"ak move: refused: {reason}", file=sys.stderr)
    if refused:
        return 1
    # -H: what is one file here, a local clone's objects, stays one there; the first pass takes hours
    code = subprocess.run(["rsync", "-aH", "--no-D", "--delete", "--info=progress2",
                           *(f"--exclude=/{path.relative_to(home)}" for path in KEPT),
                           f"{home}/", f"{alias}:{home}/"]).returncode
    return 0 if code == VANISHED else code
