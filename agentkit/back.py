"""`ak back [--when-broken]`: the last move of ~/agentkit put back, by the version it replaced.

A move links that version's bin/ak at `versions.keep_link` until a tick of the version it put
live completes (`versions.final`), and while the link is there the cron line runs it with
--when-broken before each tick, which puts the move back once `WAIT` has passed from the link's
time: the move gives it, and the tick that made the move sets it to its own end.  `ak back` puts
it back at once.  The commit put back first gets a ref under `update.FAILED`, so no move goes
to it again, and the owner is paged once it is back.  The exchange puts the version it undoes in
the folder this process came from, so all of its code loads before it, and every later step
reads and runs from the version put back at ~/agentkit.
"""

import fcntl
import importlib
import os
import pkgutil
import sys
import time

import agentkit
from . import config, notify, terminal, update, versions, watch

WAIT = 2 * watch.TICK_HUNG      # where ak pages that ticks stopped ending: 36 min ones were healthy


def main(argv):
    if argv not in ([], ["--when-broken"]):
        raise config.Error("usage: ak back [--when-broken]")
    config.ensure_dirs()
    with (config.TMP / update.MOVING).open("a") as lock:
        try:
            # never waited for: the tick after the keeper in the cron line waits for that move
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("ak back: ak is moving now; nothing is put back", file=sys.stderr)
            return 1
        live, link = update.agentkit_dir().resolve(), versions.keep_link()
        with versions.holding():    # as a tick making the move final holds it
            kept = versions.kept()
            if not kept:
                print("ak back: nothing to put back: no move of ak waits on a tick of the version "
                      "it put live", file=sys.stderr)
                return 1
            if argv and time.time() - os.lstat(link).st_mtime < WAIT:
                return 0
            for module in pkgutil.walk_packages(agentkit.__path__, "agentkit."):
                importlib.import_module(module.name)
            moved, back = (versions.git(path, "rev-parse", "HEAD")[1] for path in (live, kept))
            # before anything sees the version put back: a move chosen before it looks again
            # under the lock this holds (update_agentkit)
            failed, why = versions.git(live, "update-ref", update.FAILED + moved, moved)
            if failed:
                print(f"ak back: {moved[:12]} could not be marked failed: {why}", file=sys.stderr)
                return 1
            try:
                versions.exchange(live, kept)
            except OSError as exc:
                print(f"ak back: {kept} could not be swapped in for {live}: {exc}", file=sys.stderr)
                return 1
            link.unlink()
        # its version is at ~/agentkit now: the adapters every child's environment is made from
        config.REPO = live
        pending = config.STATE / update.PENDING     # each tick runs install.sh until it passes
        pending.touch()
        versions.repair(live, kept)
        said = f"went back from {moved[:12]} to {back[:12]}" + (
            f": no tick of {moved[:12]} completed within {terminal.format_age(WAIT)}" if argv
            else " by hand")
        print(f"ak back: {said}")
        notify.page(f"back:{moved}", "ak", f"🔴 ak {said}", line=f"🔴 ak {said}", happened=True)
        code, output = versions.run([str(live / "install.sh")], live, **update.PINS)
        if code:
            print(f"{output}\nak back: {live / 'install.sh'} exited {code}", file=sys.stderr)
            return 1
        pending.unlink()
        return 0
