"""A turn nobody keeps, run only to read its login's windows: every turn of a harness that
streams them reads them (`Harness.turn_meters`), and a turn a spent login refuses spends nothing.

A usage endpoint may answer for a login only every fifteen minutes, and not for an hour after it
refused, and a spent login has no turn or seat of its own to read it in.  Weighed:
A (refused) ask the endpoint more often: each refusal there costs an hour without a reading.
B (refused) type `continue` into a waiting seat: each try leaves a line in its conversation.
C (this) a real turn of the harness's `[check]` model, in a conversation nobody keeps.
"""

import subprocess
import tempfile
from pathlib import Path

from . import config, usage_probe
from .harness import load as harness_plugin


def meters(harness, account=None):
    """The meters one turn of `harness`'s `[check]` model on `account`'s login streamed, the
    usual login for none; [] where the turn exited non-zero, ran past `usage_probe.budget()` or
    said nothing of a window.

    One adapter `run` like any other call (`config.run_adapter`), on no seat and as that login,
    in no box, its prompt ak's own; with $AGENTKIT_UNKEPT set, the adapter runs it with no tool
    and keeps no conversation.
    """
    check = config.manifest(harness)["check"]
    config.ensure_dirs()
    with tempfile.TemporaryDirectory(prefix="usage-turn-", dir=config.TMP,
                                     ignore_cleanup_errors=True) as tmp:
        prompt, out = Path(tmp, "prompt.md"), Path(tmp, "out")
        prompt.write_text("hi\n")
        try:
            # every such turn in the one directory, so a harness keeping a record of each
            # directory it ran in keeps one for them all
            done = config.run_adapter(
                [str(config.adapter(harness)), "run", check["model"], check["effort"],
                 str(config.TMP), str(prompt), str(out)], timeout=usage_probe.budget(),
                env={**config.seatless_env(), **config.account_env(account),
                     "AGENTKIT_UNKEPT": "1"})
        except (config.Error, OSError, subprocess.TimeoutExpired):
            return []
        return harness_plugin(harness).turn_meters(out) if done.returncode == 0 else []
