"""`ak standby ALIAS`: one pass of this machine's copy of ak's folder on the home it is a client
of, at the same path, but the runs and their checkouts, which a pass of their own copies.

rsync writes straight into the copy, sending what changed within each file, compressed, over the
owner's line; each file lands whole, the old one or the new one.  A pass cut short leaves some
files newer than others, as any pass over a live home does within its own minutes, and the next
that ends well evens it out.
"""

import subprocess
import sys

from . import command_help, config, move, versions

# This machine's own, which a pass neither sends nor deletes: which server it is a client of,
# its ak install, and what each machine keeps through a move; then the runs and checkouts.
KEPT = (config.STATE / "server", versions.repository(), config.HOME / versions.VERSIONS,
        *move.KEPT, config.RUNS, config.WT, config.WORK)
TIMEOUT = 300   # seconds of silence from the home that fail a pass
GOES = 3        # a go during which files vanished on the home leaves their old copies here


def main(argv):
    if command_help.show("standby", argv):
        return 0
    if len(argv) != 1 or argv[0].startswith("-"):
        raise config.Error(command_help.COMMANDS["standby"][0])
    alias = argv[0]
    if config.server_alias() != alias:
        print(f"ak standby: refused: this machine is not a client of {alias}", file=sys.stderr)
        return 1
    # A home without the folder fails rsync's sender, 23, and rsync then deletes nothing here:
    # as a deletion it would empty the copy.
    for _ in range(GOES):
        code = subprocess.run([
            "rsync", "-aHz", "--no-D", "--delete", f"--timeout={TIMEOUT}",
            *(["--info=progress2"] if sys.stdout.isatty() else []),
            *(f"--exclude=/{path.relative_to(config.HOME)}" for path in KEPT
              if path.is_relative_to(config.HOME)),
            f"{alias}:{config.HOME}/", f"{config.HOME}/"]).returncode
        if code != move.VANISHED:
            break
    if code:
        print(f"ak standby: the pass from {alias} failed: rsync exited {code}", file=sys.stderr)
        return 1
    return 0
