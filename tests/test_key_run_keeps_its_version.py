"""A run keeps the ak it was admitted on for its rounds and hand-ins; its landing runs the install.

Each version of the install holds this test's `bin/ak` (`AK`), which notes its commit and its
arguments, then runs that version's program, kept beside it: a hand-in's version and a landing's
are what their `ak` noted.  A round's is the commit of the `ak` its worker is handed, which each
executor turn writes down (`HANDED`): the Home's PATH holds none, so it can only be ak's."""

import json
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, rerun_boxed
from fixtures.akinstall import Install
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# A script runs in this process, as `python3 bin/ak` ran this one, so it still sees itself as
# bin/ak, the name Python's tells a run's own process by; a binary replaces this process.
AK = '''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
program = Path(__file__).resolve().with_name("program")
commit = subprocess.run(["git", "-C", program.parent, "rev-parse", "HEAD"], capture_output=True,
                        text=True).stdout.strip()
with open({noted!r}, "a") as noted:
    noted.write(json.dumps([commit, *sys.argv[1:]]) + "\\n")
with program.open("rb") as start:
    script = start.read(2) == b"#!"
if script:
    __file__ = str(program)
    exec(compile(program.read_bytes(), __file__, "exec"))
else:
    os.execv(program, sys.argv)
'''
HANDED = 'git -C "$(dirname "$(command -v ak)")" rev-parse HEAD >>{}'


def wait_for(read):
    until = time.monotonic() + 120
    while not (value := read()) and time.monotonic() < until:
        time.sleep(0.1)
    assert value, "the run did not reach its next step"
    return value


def steps(notes):
    """The commits the hand-ins' ak noted, and the landings'."""
    return ({commit for commit, *argv in notes if argv[:1] == ["hand-in"]},
            {commit for commit, *argv in notes if argv[:2] == ["run", "--lander"]})


class RunKeepsItsVersion(unittest.TestCase):
    def test_rounds_and_hand_ins_keep_the_admitted_commit_while_landing_uses_the_install(self):
        with Home() as home:
            install = Install(home)
            # where a worker's box lets a turn, and the hand-in it runs, write
            noted, handed = home.root / "adapters/noted", home.root / "adapters/handed"
            ak = install.seed / "bin/ak"
            ak.rename(ak.with_name("program"))
            ak.write_text(AK.format(noted=str(noted)))
            ak.chmod(0o755)
            first = install._push("note each step's ak version")
            install.git("fetch", "-q", "origin")
            install.git("reset", "--hard", first)
            akconfig.write(home, ["opus", "astra"])
            rig = Rig(home, "widgets")
            gh = GitHub(home)
            gh.grant(rig.slug, "WRITE")
            release = home.root / "adapters/release"
            hand = HANDED.format(shlex.quote(str(handed)))
            wait = f"while [ ! -f {shlex.quote(str(release))} ]; do sleep 0.1; done"
            held = {**fakeadapter.WORK, "write": {"retry.txt": "hello\n", "fault.txt": "fault\n"},
                    "sh": f"timeout 120 sh -c '{wait}'; {hand}"}
            failure = {**fakeadapter.FAIL, "hand_in": [["finding", "fault.txt:1", "fixture defect",
                       "blocks delivery", "--run", "test ! -f fault.txt"], ["done"]]}
            fixed = {**fakeadapter.WORK, "sh": f"rm fault.txt; {hand}"}
            fakes = fakeadapter.install(home, claude=[held, fixed], codex=[failure, "pass"])
            task = taskfile.write(home, rig.path)
            done = home.run(install.ak, "run", str(task), "--bg", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            directory = taskfile.only_run(home)
            wait_for(lambda: fakes["claude"].n == 1)
            second = install.advance()
            tick = home.run(install.ak, "watch", timeout=300)
            self.assertEqual(tick.code, 0, tick.out + tick.err)
            self.assertEqual(install.head(), second)
            release.touch()
            wait_for(lambda: json.loads((directory / "run.json").read_text()).get("state")
                     in ("pass", "fail", "error", "blocked", "exhausted"))
            state = json.loads((directory / "run.json").read_text())
            self.assertTrue(state.get("merged"), (directory / "log.txt").read_text()
                            + str([call["hand_ins"] for fake in fakes.values() for call in fake.runs()]))
            notes = [json.loads(line) for line in noted.read_text().splitlines()]
            self.assertEqual(steps(notes), ({first}, {second}), notes)
            self.assertEqual(handed.read_text().split(), [first, first])
            rig = Rig(home, "gears")
            gh.grant(rig.slug, "WRITE")
            fakes["claude"].behave({**fakeadapter.WORK, "sh": hand})
            fakes["codex"].behave("pass")
            task = taskfile.write(home, rig.path, "Another retry file")
            done = home.run(install.ak, "run", str(task), timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            newer = [json.loads(line) for line in noted.read_text().splitlines()][len(notes):]
            self.assertEqual(steps(newer), ({second}, {second}), newer)
            self.assertEqual(handed.read_text().split(), [first, first, second])


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
