"""A green delivery takes its turn as soon as the one ahead has left the line, not a slot poll
later.

Two runs on one project pass review and land one after the other.  A run asks GitHub `repo
view` as it joins the line and again right before its delivery asks for the delivery lock; the
GitHub here holds the second's first until the first has joined, so the line's order is theirs,
and the first's second until the test lets it go.  The second, stacked on the first and green,
has its verdict meanwhile and stays parked: only the line's head is woken, so it starts no
process to wait for its place.  Let go, the first merges, and its end wakes the second, which
follows at once: the slot poll (AK_SLOT_POLL) is set far past how long the test waits, so a
second that slept one out never ends here.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, against the bare origin of gitrig.py and the
GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import json
from shlex import quote
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

POLL = 3600
# Each run adds a file named for its own branch, so the two changes never conflict.
WORK = {"sh": 'f=$(git branch --show-current | tr / -).txt; echo work >"$f"; git add -A; '
              'git commit -qm "add $f"',
        "final": "## Summary\nadded a file", "hand_in": [["done"]]}
# The second run's first `repo view` and the first run's later ones wait for the test's word,
# short of ak's own limit on a gh call; a run's worktree is named for its title.
HOLD = """#!/bin/sh
hold() {{ end=$(($(date +%s) + 110)); while [ ! -e "$1" ] && [ "$(date +%s)" -lt "$end" ]; do
  sleep 0.05; done; }}
if [ "$1 $2" = "repo view" ]; then case $PWD in
  *fix-api*) if [ -e {seen} ]; then : >{held}; hold {go}; else : >{seen}; fi;;
  *fix-ui*) [ -e {asked} ] || {{ : >{asked}; hold {joined}; }};;
esac; fi
exec {gh} "$@"
"""


class AGreenDeliveryTakesItsTurnWithoutAPoll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env["AK_SLOT_POLL"] = str(POLL)
        cls.rig = Rig(home, "widgets", files={"AGENTS.md": "---\nhealth: none\ntests: true\n---\n"
                                                           "# widgets\n"})
        cls.base = cls.rig.head()
        cls.gh = GitHub(home)
        cls.gh.grant(cls.rig.slug, "WRITE")      # enough to push and merge without a fork
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude=WORK, codex="pass")
        github = (home.bin / "gh").rename(home.root / "github.sh")
        marks = {name: home.root / name for name in ("seen", "held", "go", "asked", "joined")}
        home.fake("gh", HOLD.format(gh=quote(str(github)),
                                    **{name: quote(str(path)) for name, path in marks.items()}))
        cls.runs = [home.spawn("run", str(taskfile.write(home, cls.rig.path, title,
                                                         done_when=("ls *.txt",))))
                    for title in ("Fix api", "Fix ui")]
        cls.joined = cls.until(lambda: (cls.record("fix-api").get("waiting_on") or {}).get("line"))
        marks["joined"].write_text("")
        cls.held = cls.until(marks["held"].exists)
        cls.landed = cls.held and cls.until(
            lambda: "land" in (cls.record("fix-ui").get("waiting_on") or {}))
        cls.parked = cls.record("fix-ui")
        marks["go"].write_text("")
        cls.codes = [cls.ended(proc) for proc in cls.runs]

    @classmethod
    def until(cls, test, bound=240):
        """Whether `test` came to hold within `bound` seconds while a run still went on."""
        deadline = time.monotonic() + bound
        while not test():
            if time.monotonic() > deadline or all(p.poll() is not None for p in cls.runs):
                return bool(test())
            time.sleep(0.1)
        return True

    @staticmethod
    def ended(proc, bound=240):
        try:
            return proc.wait(timeout=bound)
        except subprocess.TimeoutExpired:
            return None     # still running: its code fails the test, and close ends it

    @classmethod
    def record(cls, slug):
        """The record of the run whose title is `slug`, or {} before it has one."""
        for run in taskfile.runs(cls.home):
            if run.name.endswith(slug):
                try:
                    return json.loads((run / "run.json").read_text())
                except (OSError, ValueError):
                    return {}
        return {}

    def outputs(self):
        return "\n".join(self.home.log(f"spawn-{n}.{kind}").read_text()[-3000:]
                         for n in (1, 2) for kind in ("out", "err"))

    def test_the_second_stays_parked_while_the_first_is_held(self):
        self.assertTrue(self.joined and self.held and self.landed, self.outputs())
        self.assertEqual(self.parked["state"], "waiting", self.outputs())
        self.assertNotIn("delivery_wait", self.parked, self.outputs())

    def test_both_merge_in_line_order_well_inside_a_slot_poll(self):
        self.assertEqual(self.codes, [0, 0], self.outputs())
        merges = {pr["title"]: self.gh.pr(pr["number"])["merge"] for pr in self.gh.prs()}
        self.assertEqual(self.rig.origin("log", "--format=%H", "main").splitlines(),
                         [merges["Fix ui"]["commit"], merges["Fix api"]["commit"], self.base])


if __name__ == "__main__":
    unittest.main()
