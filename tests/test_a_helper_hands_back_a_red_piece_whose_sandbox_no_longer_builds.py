"""A helper's piece whose launch ended non-zero builds its sandbox for nothing once more, as its
preflight does: where it no longer builds, the piece ends 253, the helper's code for a piece it
could not run, which ak runs on its own host; where it builds, the launch's own exit stands.  A
launch that ended 0 is asked nothing.  piece.sh's own lines, `fail`, the sandbox's size to its
preflight, then the command's launch to the piece's end, under no kill for memory and a stand-in
`unshare` that builds as the real one does for its first runs, then ends 1 with nothing run, as
the real one does where it can no longer build one.
"""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PIECE = (Path(__file__).resolve().parents[1] / "tools/helper/piece.sh").read_text()
# piece.sh's own lines: `fail`, from the sandbox's size to its preflight, and from the command's
# launch to the piece's end.
FAIL, SANDBOX, LAUNCH = (re.search(lines, PIECE, re.M).group(0) for lines in (
    r"^fail\(\).*\n", r"^notes=(?s:.*?)^offline .*\n", r"^offline .*\$command(?s:.*)"))
UNSHARE = shutil.which("unshare")


def piece(command, builds):
    """How piece.sh's lines end on `command` under an unshare that builds its first `builds` runs:
    the piece's exit, how often unshare was run and what was said."""
    with tempfile.TemporaryDirectory() as tmp:
        runs, stand_in = Path(tmp, "runs"), Path(tmp, "unshare")
        stand_in.write_text(f'#!/bin/sh\necho >>"{runs}"\n[ "$(wc -l <"{runs}")" -le {builds} ] '
                            f'|| exit 1\nexec "{UNSHARE}" "$@"\n')
        stand_in.chmod(0o755)
        proc = subprocess.run(
            ["bash", "-c", f"{FAIL}oom() {{ :; }}\ncommand={shlex.quote(command)}\n{SANDBOX}{LAUNCH}"],
            env={**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"},
            capture_output=True, text=True, timeout=60)
        return proc.returncode, len(runs.read_text().splitlines()), proc.stderr


class AHelperHandsBackARedPieceWhoseSandboxNoLongerBuilds(unittest.TestCase):
    def test_a_launch_whose_sandbox_stopped_building_ends_the_piece_253(self):
        code, runs, said = piece("exit 0", builds=1)
        self.assertEqual((code, runs), (253, 3), said)

    def test_a_command_that_failed_where_the_sandbox_builds_keeps_its_exit(self):
        code, runs, said = piece("exit 1", builds=9)
        self.assertEqual((code, runs), (1, 3), said)

    def test_a_command_that_passed_is_asked_nothing(self):
        code, runs, said = piece("exit 0", builds=9)
        self.assertEqual((code, runs), (0, 2), said)


if __name__ == "__main__":
    unittest.main()
