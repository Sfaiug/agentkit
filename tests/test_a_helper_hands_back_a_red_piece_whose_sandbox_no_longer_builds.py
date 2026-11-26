"""A helper's piece whose launch ran nothing ends 253, the helper's code for a piece it could not
run, which ak runs on its own host, whatever its sandbox builds a moment later: the sandbox
empties the launch's note as it starts the command, and that launch's is as the piece wrote it.
A command that ran keeps its own exit, though it took origin.git away, its first line, its
read-only startup variables and the descriptors its image handed it.  piece.sh's own lines, the
sandbox's size to its preflight, then from the kills for memory counted before the command's
launch to the piece's end, where origin.git is and descriptors 3 to 9 are open, under a stand-in
`awk` that counts no kill for memory and stand-ins for `unshare` and `setpriv` that are the real
ones, but the one named at the launch, its second run, where it ends 1 with nothing run, as the
real `unshare` does where it builds no sandbox.
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


def piece(command, unrun=None, startup=""):
    """How piece.sh's lines end on `command` where the stand-in `unrun` runs nothing at the
    launch, with `startup` as BASH_ENV: the piece's exit, how often unshare was run and what was
    said."""
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "origin.git").mkdir()
        for program in ("unshare", "setpriv"):
            Path(tmp, program).write_text(
                f'#!/bin/sh\necho >>"$0.runs"\n'
                f'[ "$(wc -l <"$0.runs")" != {2 if program == unrun else 0} ] || exit 1\n'
                f'exec {shlex.quote(shutil.which(program))} "$@"\n')
            Path(tmp, program).chmod(0o755)
        Path(tmp, "awk").write_text("#!/bin/sh\n")  # piece.sh's awk counts kills for memory
        Path(tmp, "awk").chmod(0o755)
        env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"}
        if startup:
            Path(tmp, "startup").write_text(startup)
            env["BASH_ENV"] = f"{tmp}/startup"
        proc = subprocess.run(
            ["bash", "-c", f"exec 3<&0 4<&0 5<&0 6<&0 7<&0 8<&0 9<&0\n"
                           f"command={shlex.quote(command)}\n"
                           f"{SANDBOX}{LAUNCH.replace('/home/ak', tmp)}"],
            cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
        return proc.returncode, len(Path(tmp, "unshare.runs").read_text().splitlines()), proc.stderr


class AHelperHandsBackARedPieceWhoseSandboxNoLongerBuilds(unittest.TestCase):
    def test_a_launch_that_ran_nothing_ends_the_piece_253_though_the_sandbox_builds_again(self):
        for unrun in ("unshare", "setpriv"):
            code, runs, said = piece("exit 0", unrun)
            self.assertEqual((code, runs), (253, 2), said)

    def test_a_command_that_failed_keeps_its_exit(self):
        for command in ("exit 1", "rm -r origin.git; exit 1"):
            code, runs, said = piece(command)
            self.assertEqual((code, runs), (1, 2), said)

    def test_a_command_runs_as_it_was_written(self):
        code, runs, said = piece(
            '[ "$LINENO $0 $# $built" = "1 bash 0 acme" ] && '
            'for fd in 3 4 5 6 7 8 9; do : <&"$fd" || exit; done && exit 42',
            startup="declare -rx built=acme\nset -C\n")
        self.assertEqual((code, runs), (42, 2), said)


if __name__ == "__main__":
    unittest.main()
