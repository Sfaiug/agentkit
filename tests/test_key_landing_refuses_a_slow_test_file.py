"""Landing measures a test file against the passing suite's own piece target.

Black-box through AK_BIN: fabricated PASS times, with the eight-piece helper of
test_key_a_suite_is_cut_for_the_whole_machine.py, never wall-clock assertions. A test file
holds the seconds the suite prints for it, in its pieces and alone (`AK_ONLY`).
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

FILE = "tests/test_sprout.py"
ANCHOR = "tests/test_anchor.py"
SUITE = ': "$AK_SHARD"; sh suite.sh'
RUNNER = f"""if [ -n "${{AK_ONLY:-}}" ]; then
  : "${{AK_RAN:?}}"
  while read -r test; do
    printf 'PASS  %s (%ss)\\n' "$test" "$(cat "$test")"; echo "$test" >>"$AK_RAN"
  done <"$AK_ONLY"
  exit
fi
case ${{AK_SHARD:-1/1}} in
  1/*) printf 'PASS  {ANCHOR} (%ss)\\n' "$(cat {ANCHOR})" ;;
  2/*) if [ "${{1:-}}" != anchor ] && [ -f {FILE} ]; then
         printf 'PASS  {FILE} (%ss)\\n' "$(cat {FILE})"; fi ;;
esac
"""
# The fake helper runs the command in the throwaway checkout ssh was called from.
SSH = f"""#!{sys.executable}
import os, shlex, subprocess, sys
words = shlex.split(sys.argv[-1])
verb, *args = words[words.index("mac.sh") + 1:]
if verb == "probe":
    print("cpus 8\\nload 6\\nroom_mb 524288")
elif verb == "prepare":
    sys.stdin.buffer.read()
elif verb == "run":
    sys.exit(subprocess.call(["bash", "-c", args[-1]],
                            env={{**os.environ, "AK_SHARD": args[6]}}))
"""


class Landing(unittest.TestCase):
    """A change writing `seconds` into FILE, which holds `before` on the target if not None."""

    def land(self, seconds, *, before=None, anchor=1000, revised=False):
        home = Home()
        self.addCleanup(home.close)
        rules = f"---\nhealth: none\ntests: {SUITE}\n---\n# sprouts\n"
        rig = Rig(home, "sprouts", files={
            "AGENTS.md": rules.replace(SUITE, SUITE + " anchor") if revised else rules,
            "suite.sh": RUNNER, ANCHOR: f"{anchor}\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n",
            **({FILE: f"{before}\n"} if before is not None else {})})
        gh = GitHub(home)
        gh.grant(rig.slug, "WRITE")
        akconfig.write(home, {"maker": "claude", "judge": "codex"},
                       workers=["maker"], reviewers=["judge"],
                       settings={"suite_helper": "acme-mac"})
        home.fake("ssh", SSH)
        work = {"write": {FILE: f"{seconds}\n", **({"AGENTS.md": rules} if revised else {})},
                "commit": "add sprout coverage",
                "final": "## Summary\nAdded sprout coverage.", "hand_in": [["done"]]}
        fix = {"write": {FILE: "100\n"}, "commit": "split sprout coverage",
               "final": "## Summary\nSplit sprout coverage.", "hand_in": [["done"]]}
        # Keep every reviewed head outside the checkout, so the test sees a fresh review.
        reviews = home.root / "adapters/reviews"
        review = {"sh": f"git rev-parse HEAD >>{shlex.quote(str(reviews))}",
                  "final": "Handed in.", "hand_in": [["done"]]}
        fakes = fakeadapter.install(home, claude=[work, fix], codex=[review])
        task = taskfile.write(home, rig.path, "Add sprout coverage", front={"rounds": 1},
                              done_when=(f"test -f {FILE}",
                                         f"printf 'PASS  {ANCHOR} (99000.0s)\\n'"))
        done = home.ak("run", str(task), timeout=300,
                       env={"AK_HOST_READINGS": json.dumps({"cpus": 4, "load": 0,
                                                            "free_mb": 16000})})
        self.assertEqual(done.code, 0, done.out + done.err)
        directory = taskfile.only_run(home)
        state = json.loads((directory / "run.json").read_text())
        self.assertTrue(state["merged"], state)
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertEqual(state["final_check"]["outcome"], "passed")
        self.assertEqual(gh.pr(1)["merge"]["head"], state["delivery_sha"])
        heads = reviews.read_text().splitlines()
        self.assertEqual(heads[-1], state["delivery_sha"])
        return rig, directory, fakes, heads

    def refused(self, **how):
        rig, directory, fakes, heads = self.land(600, **how)
        self.assertEqual([turn["role"] for turn in fakes["claude"].runs()],
                         ["executor", "fixer"], (directory / "log.txt").read_text())
        self.assertEqual(len(heads), 2)
        self.assertNotEqual(*heads)
        prompt = (directory / "round-1/final-fixer/prompt.md").read_text()
        self.assertIn(FILE, prompt)
        self.assertRegex(prompt, r"600(?:\.0)?s")
        self.assertRegex(prompt, r"target[^\n]*200(?:\.0)?s")
        self.assertIn(heads[0], prompt)
        self.assertTrue(any(f"PASS  {FILE} (100s)" in log.read_text()
                            for log in directory.glob("lander-*.log")))
        green, = directory.parent.glob(".merge-*.green")
        trees = json.loads(green.read_text())["trees"]
        self.assertNotIn(rig.git("rev-parse", f"{heads[0]}^{{tree}}"), trees)
        self.assertIn(rig.git("rev-parse", f"{heads[1]}^{{tree}}"), trees)
        self.assertEqual(rig.origin("show", f"main:{FILE}"), "100")
        return prompt


class LandingRefusesASlowTestFile(Landing):
    def test_a_revised_suite_refuses_a_new_file_it_alone_covers(self):
        self.refused(revised=True)

    def test_a_new_file_under_the_target_lands_without_a_fixer(self):
        # 140s is above the old suite's 125s target, below this pass's own 142.5s.
        _, _, fakes, heads = self.land(140, revised=True)
        self.assertEqual([turn["role"] for turn in fakes["claude"].runs()], ["executor"])
        self.assertEqual(len(heads), 1)

    def test_many_pieces_do_not_refuse_an_ordinary_short_file(self):
        _, _, fakes, _ = self.land(20, anchor=0)
        self.assertEqual([turn["role"] for turn in fakes["claude"].runs()], ["executor"])


if __name__ == "__main__":
    unittest.main()
