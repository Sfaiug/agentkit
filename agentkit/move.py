"""`ak move ALIAS`: copy this account's home to the same path on the machine `ssh ALIAS` reaches,
while ak runs; run again, it sends only what changed and deletes there what was deleted here.

Hidden here: rsync's flags, what stays out of the copy, and the refusals that keep a copy from
landing where it would do harm.  A pass made while ak runs gets the bulk across, and a file
written during it may arrive torn: the handover's last pass, made with ak stopped, is the one the
other machine carries on from.  Nothing here writes on this machine.
"""

import shlex
import subprocess
from pathlib import Path

from . import browser, command_help, config

# never a prompt, which nobody may be there to answer, and a dead link ends the pass
SSH = ("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15")
# Neither sent nor deleted there: ak's scratch, the keys that reach that machine, and the
# profile's locks, which tie it to the Chromium running here.
LEFT_OUT = (config.TMP, Path.home() / ".ssh/authorized_keys",
            browser.BRIDGE / "profile" / "Singleton*")
VANISHED = 24       # rsync's exit when a file it listed was gone by its turn: no failure
# Run there with this machine's id and home path: its exit names the refusal, if any.  The
# tick is a live line of the crontab install.sh writes, tagged `# agentkit watch`.
PROBE = """[ "$(cat /etc/machine-id 2>/dev/null)" != "$1" ] || exit 3
[ "$HOME" = "$2" ] || exit 4
if crontab -l 2>/dev/null | grep -Eq '^[[:space:]]*[^#[:space:]].*#[[:space:]]*agentkit[[:space:]]+watch([[:space:]]|$)'; then
  exit 5
fi"""
REFUSALS = {3: "{alias} is this machine",
            4: "the home on {alias} is not {home}, and run records hold absolute paths",
            5: "ak's tick is installed on {alias}, and two servers would work on one home"}


def main(argv):
    if command_help.show("move", argv):
        return 0
    if len(argv) != 1 or argv[0].startswith("-"):
        raise config.Error(command_help.COMMANDS["move"][0])
    alias, home = argv[0], Path.home()
    machine = Path("/etc/machine-id").read_text().strip()
    probe = subprocess.run([*SSH, alias, shlex.join(["sh", "-c", PROBE, "probe", machine, str(home)])],
                           stdin=subprocess.DEVNULL).returncode
    if probe:
        raise config.Error(REFUSALS.get(probe, "ssh {alias} failed").format(alias=alias, home=home)
                           + "; nothing was copied")
    copied = subprocess.run(["rsync", "-aH", "--no-D", "--delete", "-e", shlex.join(SSH),
                             *(f"--exclude=/{path.relative_to(home)}" for path in LEFT_OUT),
                             f"{home}/", f"{alias}:{home}/"], stdin=subprocess.DEVNULL).returncode
    if copied not in (0, VANISHED):
        raise config.Error(f"rsync stopped with exit {copied}; run ak move again")
    print(f"{home} is copied to {alias}")
    return 0
