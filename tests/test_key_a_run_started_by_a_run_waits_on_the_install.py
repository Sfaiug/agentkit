"""A run started by another run waits, picks up and is admitted on the install, as a seat's is.

A run's own processes run the version it was admitted on; a fix run its merge starts for a
reviewer's follow-up is a new launch all the same, and starts on the install, not its starter's
version.  Each version of the install holds `AK`, test_key_run_keeps_its_version.py's `bin/ak`,
which notes its commit and its arguments, then runs that version's program, kept beside it: every
`ak` started with the fix run's launch -- its start, any pickup, its admission -- notes `run` and
the fix run's task.  The seat's run is admitted on one commit; the install moves to a second
before that run merges.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, rerun_boxed
from fixtures.akinstall import Install
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_run_keeps_its_version import AK, ended, notes, wait_for

CHECK = "test -f sturdy.txt"
REVIEW = {"final": "One more defect.", "hand_in": [
    ["follow-up", "retry.txt:1", "flimsy widget", "it breaks later", "--run", CHECK], ["done"]]}
FIX = {"write": {"sturdy.txt": "ok\n"}, "commit": "make the widget sturdy",
       "final": "## Summary\nsturdy", "hand_in": [["done"]]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RunStartedByARunWaitsOnTheInstall(unittest.TestCase):
    def test_a_fix_run_its_merge_starts_launches_on_the_install_moved_since_admission(self):
        with Home() as home:
            install = Install(home)
            noted = home.root / "adapters/noted"
            ak = install.seed / "bin/ak"
            ak.rename(ak.with_name("program"))
            ak.write_text(AK.format(noted=str(noted)))
            ak.chmod(0o755)
            first = install._push("note each step's ak version")
            install.git("fetch", "-q", "origin")
            install.git("reset", "--hard", first)
            akconfig.write(home, ["opus", "astra"])
            rig = Rig(home, "widgets")
            GitHub(home).grant(rig.slug, "WRITE")
            Seat(home, "acme", cwd=rig.path, record={"reviewers": ["astra"]}, planned=True)
            release = home.root / "adapters/release"
            wait = f"while [ ! -f {shlex.quote(str(release))} ]; do sleep 0.1; done"
            held = {**fakeadapter.WORK, "sh": f"timeout 600 sh -c '{wait}'"}
            fakes = fakeadapter.install(home, claude=[held, FIX], codex=[REVIEW, "pass"])
            task = taskfile.write(home, rig.path)
            done = home.run(install.ak, "run", str(task), "--bg", env={"AGENTKIT_SESSION": "acme"},
                            timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            parent = taskfile.only_run(home)
            wait_for(lambda: fakes["claude"].n == 1)
            second = install.advance()
            tick = home.run(install.ak, "watch", timeout=300)
            self.assertEqual(tick.code, 0, tick.out + tick.err)
            self.assertEqual(install.head(), second)
            release.touch()
            # its record says it passed before its merge hands its follow-ups on
            fixes = wait_for(lambda: (ended(parent) or {}).get("followup_runs"))
            self.assertEqual(len(fixes), 1, fixes)
            fix = parent.parent / fixes[0]
            # nothing of the fix run outlives this Home
            wait_for(lambda: ended(fix))
            launched = [note[0] for note in notes(noted)
                        if note[1:] == ["run", str(fix / "task.md")]]
            self.assertTrue(launched, notes(noted))
            self.assertEqual(set(launched), {second}, json.dumps(notes(noted), indent=1))


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
