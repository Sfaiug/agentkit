"""A helper's piece whose launch ran nothing ends 253, the helper's code for a piece it could not
run, which ak runs on its own host, whatever its sandbox builds a moment later: built, the
sandbox says so on a descriptor of its own, and that launch's said nothing.  A command that ran
keeps its own exit, its first line and its variables.  piece.sh's own lines, the sandbox's size
to its preflight, then from the kills for memory counted before the command's launch to the
piece's end, under a stand-in `awk` that counts no kill for memory and a stand-in `unshare` that
builds as the real one does but on the runs named, where it ends 1 with nothing run, as the real
one does where it builds no sandbox.
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
# piece.sh's own lines: from the sandbox's size to its preflight, and from the kills for memory
# counted before the command's launch to the piece's end.
SANDBOX, LAUNCH = (re.search(lines, PIECE, re.M).group(0) for lines in (
    r'^notes=(?s:.*?)^"\$@" sh -c :.*\n', r"^before=(?s:.*)"))
UNSHARE = shutil.which("unshare")


def piece(command, fails=()):
    """How piece.sh's lines end on `command` under an unshare that builds nothing on its runs
    `fails`, the preflight its first, where the suite's image exports `built`: the piece's exit,
    how often unshare was run and what was said."""
    with tempfile.TemporaryDirectory() as tmp:
        stand_in = Path(tmp, "unshare")
        stand_in.write_text(f'#!/bin/sh\necho >>"$0.runs"\ncase "$(wc -l <"$0.runs")" in '
                            f'{"|".join(map(str, fails)) or "-"}) exit 1 ;; esac\n'
                            f'exec {shlex.quote(UNSHARE)} "$@"\n')
        stand_in.chmod(0o755)
        Path(tmp, "awk").write_text("#!/bin/sh\n")  # piece.sh's awk counts kills for memory
        Path(tmp, "awk").chmod(0o755)
        proc = subprocess.run(
            ["bash", "-c", f"command={shlex.quote(command)}\n{SANDBOX}{LAUNCH}"],
            env={**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "built": "acme"},
            capture_output=True, text=True, timeout=60)
        return proc.returncode, len(Path(f"{stand_in}.runs").read_text().splitlines()), proc.stderr


class AHelperHandsBackARedPieceWhoseSandboxNoLongerBuilds(unittest.TestCase):
    def test_a_launch_that_ran_nothing_ends_the_piece_253_though_the_sandbox_builds_again(self):
        for fails in ([2], [2, 3]):
            code, runs, said = piece("exit 0", fails)
            self.assertEqual((code, runs), (253, 2), said)

    def test_a_command_that_failed_keeps_its_exit(self):
        code, runs, said = piece("exit 1")
        self.assertEqual((code, runs), (1, 2), said)

    def test_a_command_runs_as_it_was_written(self):
        code, runs, said = piece('[ "$LINENO $built" = "1 acme" ] && ! [ -e /dev/fd/8 -o -e /dev/fd/9 ]')
        self.assertEqual((code, runs), (0, 2), said)


if __name__ == "__main__":
    unittest.main()
