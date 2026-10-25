"""The acceptance gates of a harness upgrade, stood in for in an answer-key Home.

`ak update` keeps a harness's new release only once the build's own gates pass: tests/live.sh,
then the fresh-install tests/e2e-fresh.sh, each run with bash.  Those are real model calls,
which no test may start.  `Gates(home)` puts a `bash` first on the program's PATH that answers
for any of the three named among its arguments -- these two and the landing suite's
tests/smoke.sh, which an upgrade never runs -- with the exit status the test set (0 unless set),
and runs everything else as the real bash.  It keeps each gate it answered, in order, with whether
AGENTKIT_ACCEPTANCE_REQUIRED was 1 for it.

    from fixtures.akbin import Home
    from fixtures.akgates import Gates
    with Home() as home:
        gates = Gates(home)
        gates.exit("live", 1)
        home.ak("update")
        assert gates.ran() == ["live"]
"""

import shlex
import shutil
from pathlib import Path

from .akbin import SYSTEM

NAMES = ("smoke", "live", "e2e-fresh")
BASH = """#!/bin/sh
for arg do
  case $arg in
    */tests/smoke.sh|*/tests/live.sh|*/tests/e2e-fresh.sh)
      gate=$(basename "$arg" .sh)
      echo "$gate ${{AGENTKIT_ACCEPTANCE_REQUIRED:-unset}}" >>{log}
      code=$(cat {dir}/"$gate".exit 2>/dev/null || echo 0)
      echo "$gate stand-in: exit $code"
      exit "$code" ;;
  esac
done
exec {bash} "$@"
"""


class Gates:
    def __init__(self, home):
        self.dir = Path(home.root) / "gates"
        self.dir.mkdir(exist_ok=True)
        self.log = self.dir / "ran"
        bash = shutil.which("bash", path=":".join(SYSTEM))
        home.fake("bash", BASH.format(log=shlex.quote(str(self.log)),
                                      dir=shlex.quote(str(self.dir)), bash=shlex.quote(bash)))

    def exit(self, gate, code):
        """The status `gate` (smoke, live or e2e-fresh) exits with from now on."""
        assert gate in NAMES, gate
        (self.dir / f"{gate}.exit").write_text(f"{code}\n")

    def reset(self):
        """Every gate green again, and none ran yet."""
        for path in self.dir.iterdir():
            path.unlink()

    def calls(self):
        """(gate, AGENTKIT_ACCEPTANCE_REQUIRED) for each gate answered, oldest first."""
        try:
            return [tuple(line.split(" ", 1)) for line in self.log.read_text().splitlines()]
        except FileNotFoundError:
            return []

    def ran(self):
        return [gate for gate, _ in self.calls()]
