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

# This machine's own in ak's folder, which a pass neither sends nor deletes: which server it is
# a client of, its ak install, and what each machine keeps through a move; then the runs and
# checkouts.
KEPT = tuple(path for path in (config.STATE / "server", versions.repository(),
                               config.HOME / versions.VERSIONS, *move.KEPT,
                               config.RUNS, config.WT, config.WORK)
             if path.is_relative_to(config.HOME))
TIMEOUT = 300   # seconds of silence from the home that fail a pass
GOES = 3        # a go during which files vanished on the home leaves their old copies here


def main(argv):
    if command_help.show("standby", argv):
        return 0
    if len(argv) != 1 or argv[0].startswith("-"):
        raise config.Error(command_help.COMMANDS["standby"][0])
    alias = argv[0]
    refused = [f"this machine is not a client of {alias}"] * (config.server_alias() != alias)
    # What is kept are names: rsync would replace a link at one, or at a folder between it and
    # ak's folder, with the home's, or delete what it reaches.
    refused += [f"{config.tilde(part)} is a link here" for part in sorted(
        {part for path in KEPT for part in (path, *path.parents)
         if config.HOME in part.parents and part.is_symlink()})]
    for reason in refused:
        print(f"ak standby: refused: {reason}", file=sys.stderr)
    if refused:
        return 1
    # A home without the folder fails rsync's sender, 23, and rsync then deletes nothing here:
    # as a deletion it would empty the copy.  Times are compared to the nanosecond, as rsync's
    # whole seconds take a same-size write within one for no change, on every pass after.
    for _ in range(GOES):
        code = subprocess.run([
            "rsync", "-aHz", "--no-D", "--delete", "--modify-window=-1", f"--timeout={TIMEOUT}",
            *(["--info=progress2"] if sys.stdout.isatty() else []),
            *(f"--exclude=/{path.relative_to(config.HOME)}" for path in KEPT),
            f"{alias}:{config.HOME}/", f"{config.HOME}/"]).returncode
        if code != move.VANISHED:
            break
    if code:
        print(f"ak standby: the pass from {alias} failed: rsync exited {code}", file=sys.stderr)
        return 1
    return 0
