"""A helper's piece whose launch ended non-zero with nothing run ends 253, the helper's code for a
piece it could not run, which ak runs on its own host: the command's own shell takes a file away
as it starts, and that file is still there.  A command that ran keeps its own exit, and a piece
with no temporary file ends 253 unlaunched.  piece.sh's own lines, the sandbox's size to its
preflight, then from the kills for memory counted before the command's launch to the piece's
end, under a stand-in `awk` that counts no kill for memory and a stand-in `unshare` that builds
as the real one does but on the runs named, where it ends 1 with nothing run, as the real one
does where it builds no sandbox.
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


def piece(command, fails=(), mktemp=""):
    """How piece.sh's lines end on `command` under an unshare that builds nothing on its runs
    `fails`, the preflight its first, with `mktemp` put before the lines: the piece's exit, how
    often unshare was run, what was said and the temporary files left."""
    with tempfile.TemporaryDirectory() as tmp:
        stand_in = Path(tmp, "unshare")
        stand_in.write_text(f'#!/bin/sh\necho >>"$0.runs"\ncase "$(wc -l <"$0.runs")" in '
                            f'{"|".join(map(str, fails)) or "-"}) exit 1 ;; esac\n'
                            f'exec {shlex.quote(UNSHARE)} "$@"\n')
        stand_in.chmod(0o755)
        Path(tmp, "awk").write_text("#!/bin/sh\n")  # piece.sh's awk counts kills for memory
        Path(tmp, "awk").chmod(0o755)
        proc = subprocess.run(
            ["bash", "-c", f"command={shlex.quote(command)}\n{mktemp}\n{SANDBOX}{LAUNCH}"],
            env={**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "TMPDIR": tmp},
            capture_output=True, text=True, timeout=60)
        return (proc.returncode, len(Path(f"{stand_in}.runs").read_text().splitlines()),
                proc.stderr, list(Path(tmp).glob("tmp.*")))


class AHelperHandsBackARedPieceWhoseSandboxNoLongerBuilds(unittest.TestCase):
    def test_a_launch_that_ran_nothing_ends_the_piece_253_though_the_sandbox_builds_again(self):
        code, runs, said, left = piece("exit 0", fails=[2])
        self.assertEqual((code, runs, left), (253, 2, []), said)

    def test_a_command_that_failed_keeps_its_exit(self):
        code, runs, said, left = piece("exit 7")
        self.assertEqual((code, runs, left), (7, 2, []), said)

    def test_a_command_that_passed_ends_the_piece_0(self):
        code, runs, said, left = piece("exit 0")
        self.assertEqual((code, runs, left), (0, 2, []), said)

    def test_a_piece_with_no_temporary_file_ends_253_unlaunched(self):
        code, runs, said, _ = piece("exit 0", mktemp="mktemp() { return 1; }")
        self.assertEqual((code, runs), (253, 1), said)


if __name__ == "__main__":
    unittest.main()
