"""Changes landing into one repository together are each tested on top of those ahead of them,
and merge one at a time, in that order.

Two runs on one project pass review, the second while the first is merging.  The project's
`tests:` suite prints the commits under the tree it runs on, so what it printed shows how each
change was tested: the second stacked on the first, before the first has landed.  The GitHub
here holds every `pr merge` until the test lets it go, and while the first is held the second,
passed and tested, starts none: one merge per repository is a correctness lock, not capacity,
as a merge beside another could land a tree no suite ran.  The second then merges rebased onto
the first.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, against the bare origin of gitrig.py and the GitHub of fakegh.py,
with scripted harnesses from fakeadapter.py.
"""

import os
import re
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

# The subject of every commit under the tree the suite runs on, newest first, on one line.
SUITE = "echo SUITE-SAW $(git log --format=%s | tr '\\n' '|')"
SAW = re.compile(r"^SUITE-SAW (.*)$", re.M)
# Each run adds a file named for its own branch, so the two changes never conflict.
WORK = {"sh": 'f=$(git branch --show-current | tr / -).txt; echo work >"$f"; git add -A; '
              'git commit -qm "add $f"',
        "final": "## Summary\nadded a file", "hand_in": [["done"]]}
# Every `pr merge` waits for the test's word, short of ak's own limit on a gh call, and the
# log says when each one started and when it ended, by the PR's number.
HOLD = """#!/bin/sh
pr=
[ "$1 $2" = "pr merge" ] && for a do case $a in */pull/*|[0-9]|[0-9][0-9]) pr=${{pr:-$a}};; esac
done
if [ -n "$pr" ]; then echo "start ${{pr##*/}}" >>{log}
  i=0; while [ ! -e {go} ] && [ $i -lt 1800 ]; do sleep 0.05; i=$((i+1)); done; fi
{gh} "$@"; code=$?
[ -n "$pr" ] && echo "end ${{pr##*/}}" >>{log}
exit $code
"""


def second_waits(directory):
    """A review that hands in at once the first time it runs, and after that only once the
    first change's merge has begun."""
    place = quote(str(directory))
    return {"sh": f"mkdir {place}/reviewed 2>/dev/null || {{ i=0; "
                  f"while [ ! -e {place}/merges.log ] && [ $i -lt 2400 ]; "
                  "do sleep 0.05; i=$((i+1)); done; }",
            "final": "Handed in.", "hand_in": [["done"]]}


class LandingTrain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rig = Rig(home, "widgets", files={"AGENTS.md": f"---\ntests: {SUITE}\n---\n"
                                                           "# widgets\n"})
        cls.base = cls.rig.head()
        cls.gh = GitHub(home)
        cls.gh.grant(cls.rig.slug, "WRITE")      # enough to push and merge without a fork
        akconfig.write(home, ["opus", "astra"])
        fakes = fakeadapter.install(home, claude=WORK, codex="pass")
        fakes["codex"].behave(second_waits(fakes["codex"].dir))
        github = (home.bin / "gh").rename(home.root / "github.sh")
        # The merge log is where a review turn can read it too.
        cls.merges, go = fakes["codex"].dir / "merges.log", home.root / "go"
        home.fake("gh", HOLD.format(log=quote(str(cls.merges)), go=quote(str(go)),
                                    gh=quote(str(github))))
        cls.runs = [home.spawn("run", str(taskfile.write(home, cls.rig.path, title,
                                                         done_when=("ls *.txt",))))
                    for title in ("Fix api", "Fix ui")]
        # The second review waits for the first merge, so the second change joins the line
        # once the first's check is over, and is checked as it joins.
        cls.stacked = (cls.until(lambda: cls.merged_log()) and cls.until(
            lambda: any(line.count("add ") == 2 for line in cls.saw()), bound=60))
        # The second merge is given time to start beside the first; it must not.
        cls.until(lambda: len(cls.merged_log()) > 1, bound=5)
        cls.held = cls.merged_log()
        go.write_text("")
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
    def merged_log(cls):
        """Each `pr merge` start and end, oldest first, as (word, PR number)."""
        try:
            lines = cls.merges.read_text().split("\n")[:-1]    # a line being written waits
        except FileNotFoundError:
            return []
        return [(word, int(number)) for word, number in map(str.split, lines)]

    @classmethod
    def saw(cls):
        """Every line the suite printed, wherever ak keeps what its checks print."""
        lines = []
        for top, _, names in os.walk(cls.home.path / ".agentkit"):
            for path in (Path(top, name) for name in names):
                try:
                    if path.is_file() and path.stat().st_size < 1 << 20:
                        lines += SAW.findall(path.read_text(errors="replace"))
                except OSError:
                    continue        # a checkout or log ak removed while this one read
        return lines

    def outputs(self):
        return "\n".join(self.home.log(f"spawn-{n}.{kind}").read_text()[-3000:]
                         for n in (1, 2) for kind in ("out", "err"))

    def order(self):
        """The PRs in the order their merges started."""
        return [number for word, number in self.merged_log() if word == "start"]

    def added(self, number):
        """The one file a merged PR's commit adds to the target."""
        commit = self.gh.pr(number)["merge"]["commit"]
        return self.rig.origin("diff", "--name-only", f"{commit}^", commit)

    def test_both_runs_pass_and_each_merges_its_own_pr(self):
        self.assertEqual(self.codes, [0, 0], self.outputs())
        prs = self.gh.prs()
        self.assertEqual(sorted(pr["title"] for pr in prs), ["Fix api", "Fix ui"])
        self.assertEqual([pr["state"] for pr in prs], ["MERGED", "MERGED"])
        self.assertEqual(sorted(self.added(pr["number"]) for pr in prs),
                         sorted(f"{pr['headRefName'].replace('/', '-')}.txt" for pr in prs))

    def test_the_second_change_is_tested_on_top_of_the_first_before_the_first_lands(self):
        self.assertTrue(self.stacked, self.outputs())
        first, second = map(self.added, self.order())
        # The first change is its own commit beneath the second: it had not merged yet.
        self.assertEqual(set(self.saw()), {f"add {first}|init|",
                                           f"add {second}|add {first}|init|"})

    def test_a_second_merge_never_starts_while_the_first_is_merging(self):
        log = self.merged_log()
        self.assertEqual(len(self.order()), 2, log)
        first, second = self.order()
        self.assertEqual(self.held, [("start", first)])
        self.assertNotEqual(first, second)
        self.assertEqual(log, [("start", first), ("end", first), ("start", second),
                               ("end", second)])

    def test_the_second_merges_rebased_onto_the_first(self):
        first, second = (self.gh.pr(number)["merge"] for number in self.order())
        self.assertEqual(self.rig.origin("log", "--format=%H %P", "main").splitlines(),
                         [f"{second['commit']} {first['commit']}",
                          f"{first['commit']} {self.base}", self.base])
        self.assertEqual(self.rig.origin("rev-parse", f"{second['head']}^"), first["commit"])
        self.assertEqual(self.rig.origin("rev-parse", f"{second['head']}^{{tree}}"),
                         self.rig.origin("rev-parse", "main^{tree}"))


if __name__ == "__main__":
    unittest.main()
