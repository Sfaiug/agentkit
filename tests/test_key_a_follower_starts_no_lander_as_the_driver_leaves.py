"""A terminal following a run starts no second lander as the run's driver leaves for its line.

The driver starts its line's lander as it leaves; the follower starts one again only once the
picker's interval, a minute, has passed since its first look at the driver gone, however long the
driver ran before it: one started sooner, before the first holds the line's lock, would check the
same pass beside it.  The driver's lander can die with its run's unit, and the follower's lands
the run.

Black-box: the program `AK_BIN` names runs a task in the foreground through
tests/fixtures/akbin.py, against gitrig.py's origin, fakegh.py's GitHub and fakeadapter.py's
harnesses.  Its executor's turn takes over a minute, so the run reaches its line after that.  Every
lander start runs the installed ak, which here notes how long after the run joined its line
(`line_since`, written before its driver starts that line's lander) it was started; the first
start, the driver's, dies there, and the next runs the program.
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
import glob, json, os, sys, time
if sys.argv[1:3] == ["run", "--lander"]:
    first = not os.path.exists({starts!r})
    (member,) = glob.glob({runs!r} + "/*/run.json")
    with open(member) as record, open({starts!r}, "a") as starts:
        starts.write(f"{{time.time() - json.load(record)['line_since']}}\\n")
    if first:
        sys.exit()
os.execv({ak!r}, [{ak!r}, *sys.argv[1:]])
"""


class AFollowerStartsNoLanderAsTheDriverLeaves(unittest.TestCase):
    def test_the_follower_starts_the_line_s_lander_again_a_minute_after_the_driver_left(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={"AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        claude = fakeadapter.install(home, claude="work", codex="pass")["claude"]
        claude.behave({**fakeadapter.WORK, "sh": "sleep 61"})
        starts = home.root / "landers"
        home.write(".local/bin/ak", INSTALLED.format(
            python=sys.executable, starts=str(starts), runs=str(home.path / ".agentkit" / "runs"),
            ak=AK)).chmod(0o755)
        done = home.ak("run", str(taskfile.write(home, rig.path)), timeout=600)
        self.assertEqual(done.code, 0, done.out + done.err)
        after = [float(line) for line in starts.read_text().split()]
        self.assertEqual(len(after), 2, after)   # the driver's, which died, then the follower's
        self.assertGreaterEqual(after[1], 60, after)


if __name__ == "__main__":
    unittest.main()
