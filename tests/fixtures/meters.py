"""A harness that is only its meter: the `echo` fixture adapter, answering the usage a test sets.

`install` puts `echo.sh` and `echo.toml` in `<root>/meters` and names that directory in the
Home's AGENTKIT_ADAPTER_DIR, so every ak the test runs from then on reads these.  The toml is
tests/fixtures/adapters/echo.toml, saying `[usage] reset = true` when `reset`: that adapter
counts usage-limit resets with `reset-status` and spends one with `reset`.  The script logs
every verb it is called with, for the provider and account ak names in AGENTKIT_PROVIDER and
AGENTKIT_ACCOUNT (`default` for the usual login), and answers:

    usage         a weekly meter as `week` set it for that provider and account, a day from
                  its reset, with whatever else `week` was given (`credits=12`)
    reset-status  {"available": N} as `resets` set it for that account (ak names no provider
                  for this verb), 0 unless set
    interactive   /bin/sh, the program a seat on it runs
    auth          logged in; any other verb, a line and exit 0

    from fixtures.akbin import Home
    from fixtures import akconfig, meters
    with Home() as home:
        meter = meters.install(home, reset=True)
        meter.week("acme", "default", used=100, credits=12)
        akconfig.write(home, {"beta": {"harness": "echo", "provider": "acme"}})
        assert meters.cell(home.ak("usage").out, "acme", "outlook") == "on credits"
        assert "reset" not in [verb for verb, *_ in meter.calls()]
"""

import json
from pathlib import Path
import re
import shlex
import time

ECHO = Path(__file__).resolve().parent / "adapters" / "echo.toml"
WEEK = 604800
SCRIPT = """#!/bin/sh
dir={dir}
account=${{AGENTKIT_ACCOUNT:-default}}
printf '%s\\t%s\\t%s\\n' "$1" "$AGENTKIT_PROVIDER" "$account" >>"$dir/calls.tsv"
case "$1" in
  usage) cat "$dir/$AGENTKIT_PROVIDER.$account.usage.json" 2>/dev/null ||
           echo '{{"meters": [], "error": "unknown: no meter scripted"}}' ;;
  reset-status) cat "$dir/$account.resets.json" 2>/dev/null ||
                  echo '{{"available": 0}}' ;;
  interactive) echo /bin/sh ;;
  auth) echo "the meter fixture needs no login" ;;
  *) echo "the meter fixture: $1" ;;
esac
"""


class Meters:
    def __init__(self, directory):
        self.dir = directory
        self.resets_at = int(time.time()) + 86400   # one moment, the same for every meter

    def week(self, provider, account="default", *, used, **extra):
        """What `usage` answers for that account from now on: its week `used`% spent."""
        meter = {"name": "weekly", "used": used, "resets_at": self.resets_at,
                 "window_secs": WEEK}
        (self.dir / f"{provider}.{account}.usage.json").write_text(
            json.dumps({"meters": [meter], "error": None, **extra}))

    def resets(self, account, available):
        """How many usage-limit resets `reset-status` says that account holds."""
        (self.dir / f"{account}.resets.json").write_text(json.dumps({"available": available}))

    def calls(self):
        """Each call so far, oldest first, as (verb, provider, account)."""
        try:
            rows = (self.dir / "calls.tsv").read_text().splitlines()
        except FileNotFoundError:
            return []
        return [tuple(row.split("\t")) for row in rows]


def install(home, *, reset=False):
    directory = home.root / "meters"
    directory.mkdir(exist_ok=True)
    home.env["AGENTKIT_ADAPTER_DIR"] = str(directory)
    script = directory / "echo.sh"
    script.write_text(SCRIPT.format(dir=shlex.quote(str(directory))))
    script.chmod(0o755)
    (directory / "echo.toml").write_text(ECHO.read_text()
                                         + ("\n[usage]\nreset = true\n" if reset else ""))
    return Meters(directory)


def cell(out, label, heading):
    """What `ak usage` printed in its table's row for `label` (`acme II`) under `heading`
    (`held`, `outlook`): from where that heading starts to where the next one does."""
    lines = out.splitlines()
    head = next(line for line in lines if line.startswith("provider "))
    starts = [found.start() for found in re.finditer(r"\S+", head)] + [None]
    row = next(line for line in lines if line[:starts[1]].strip() == label)
    at = head.split().index(heading)
    return row[starts[at]:starts[at + 1]].strip()
