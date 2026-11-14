"""A terminal following a run starts no second lander as the run's driver leaves for its line.

The driver starts its line's lander as it leaves; the follower starts one again only a while after
that leaving, however long the driver ran before it: one started before the first holds the line's
lock would check the same pass beside it.

Black-box: the program `AK_BIN` names runs a task in the foreground through
tests/fixtures/akbin.py, against gitrig.py's origin, fakegh.py's GitHub and fakeadapter.py's
harnesses.  Its executor's turn takes over a minute, the interval at which a follower starts a
lander again, so the run reaches its line after that.  Every lander start runs the installed ak, which
here notes the start and waits a few seconds, longer than a follower's look takes to come round,
before it runs the program.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import AK, Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

INSTALLED = """#!{python}
import os, sys, time
if sys.argv[1:3] == ["run", "--lander"]:
    with open({starts!r}, "a") as starts:
        starts.write("lander\\n")
    time.sleep(5)
os.execv({ak!r}, [{ak!r}, *sys.argv[1:]])
"""


class AFollowerStartsNoLanderAsTheDriverLeaves(unittest.TestCase):
    def test_the_line_is_checked_by_the_one_lander_its_driver_started(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={"AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        claude = fakeadapter.install(home, claude="work", codex="pass")["claude"]
        claude.behave({**fakeadapter.WORK, "sh": "sleep 61"})
        starts = home.root / "landers"
        home.write(".local/bin/ak", INSTALLED.format(python=sys.executable, starts=str(starts),
                                                     ak=AK)).chmod(0o755)
        done = home.ak("run", str(taskfile.write(home, rig.path)), timeout=600)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(starts.read_text(), "lander\n")


if __name__ == "__main__":
    unittest.main()
