"""Landing reds count at merge: an unchanged patch is a flake, a changed patch a break.

Black-box through AK_BIN, Home, Rig, GitHub and fakeadapter.py. The suite fails twice per
tree before passing, or stays red until the fixer removes bad.txt. A red that never merges
counts neither. Git decides whether the patch changed, regardless of what the fixer says.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_history_db import OWNERS, read

SUITE = "python3 suite.py"
RUNNER = """\
from pathlib import Path
import subprocess
if not Path('retry.txt').exists():
    raise SystemExit(0)
def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()
seen = Path(git('rev-parse', '--git-common-dir')) / ('seen-' + git('rev-parse', 'HEAD^{tree}'))
n = int(seen.read_text()) + 1 if seen.exists() else 1
seen.write_text(str(n))
raise SystemExit(n <= 2 if TRANSIENT else Path('bad.txt').exists())
"""
WORK = {"write": {"retry.txt": "hello\n", "bad.txt": "stale\n"}, "commit": "add retry file",
        "final": "## Summary\nAdded retry file.", "hand_in": [["done"]]}
FIX = {"sh": "git rm -q bad.txt", "commit": "fix landing",
       "final": "## Summary\nFixed landing.", "hand_in": [["done"]]}


class LandingFlakeCountsApart(unittest.TestCase):
    def landing(self, transient, fixer):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": f"---\ntests: {SUITE}\n---\n# widgets\n",
            "suite.py": RUNNER.replace("TRANSIENT", str(transient))})
        gh = GitHub(home)
        gh.grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        heads = home.root / "adapters/heads"
        review = {"sh": f"git rev-parse HEAD >>{shlex.quote(str(heads))}",
                  "final": "Handed in.", "hand_in": [["done"]]}
        fakes = fakeadapter.install(home, claude=[WORK, fixer], codex=review)
        task = taskfile.write(home, rig.path, "Add retry file")
        done = home.ak("run", str(task), env=OWNERS, timeout=300)
        directory = taskfile.only_run(home)
        state = json.loads((directory / "run.json").read_text())
        row, = read(home, "SELECT * FROM runs")
        self.assertEqual([turn["role"] for turn in fakes["claude"].runs()],
                         ["executor", "fixer"], done.out + done.err)
        self.assertEqual(len(state["round_summaries"]), 1)
        if fixer == "blocked":
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertFalse(state.get("merged"))
            self.assertEqual(row["final_state"], "blocked")
        else:
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertTrue(state["merged"])
            self.assertEqual((state["verdict"], row["final_state"]), ("PASS", "pass"))
            self.assertEqual(fakes["codex"].n, 2)
            self.assertEqual(gh.pr(1)["merge"]["head"], state["delivery_sha"])
            self.assertEqual(rig.origin("rev-parse", "main^{tree}"),
                             rig.git("rev-parse", f"{state['delivery_sha']}^{{tree}}"))
        return home, row, heads.read_text().splitlines()

    def test_twice_red_then_green_without_a_fix_counts_one_flake(self):
        home, row, heads = self.landing(True, "pass")
        self.assertEqual((row["landing_breaks"], row["landing_flakes"]), (0, 1))
        self.assertEqual(heads[0], heads[1], "the fixer committed a change")
        checks = read(home, f"SELECT exit FROM checks WHERE kind='landing' "
                            f"AND command='{SUITE}' ORDER BY rowid")
        self.assertEqual([check["exit"] for check in checks], [1, 1, 0])

    def test_red_until_the_fixer_changes_the_patch_counts_one_break(self):
        _home, row, heads = self.landing(False, FIX)
        self.assertEqual((row["landing_breaks"], row["landing_flakes"]), (1, 0))
        self.assertNotEqual(heads[0], heads[1])

    def test_a_new_commit_with_the_same_patch_is_still_a_flake(self):
        fixer = {"sh": "git commit -q --allow-empty -m 'retry landing'",
                 "final": "## Summary\nRetry landing.", "hand_in": [["done"]]}
        _home, row, heads = self.landing(True, fixer)
        self.assertEqual((row["landing_breaks"], row["landing_flakes"]), (0, 1))
        self.assertNotEqual(heads[0], heads[1])

    def test_an_unmerged_red_counts_neither(self):
        _home, row, _heads = self.landing(False, "blocked")
        self.assertEqual((row["landing_breaks"], row["landing_flakes"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
