"""Every gate's real run lands on a branch of its own in one sandbox repository.

Two smoke suites' check 4 and one fresh-install gate's step f, each lifted out of its script, run
at once against one bare origin, missing until a gate makes it, through a fake `gh` and a fake
`ak`; the real tests/sandbox_branch.py and tests/verify_delivery.py do the rest.  Each lands on
and then removes only its own branches, and no repository but `agentkit-smoke` is made.  How the
module makes the repository and clears what killed suites left: tests/test_sandbox_branch.py.
Offline: nothing reaches GitHub or a model.
"""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SMOKE = (REPO / "tests/smoke.sh").read_text()
FRESH = (REPO / "tests/e2e-fresh.sh").read_text()
CHECK4 = SMOKE[SMOKE.index("# --- 4: ak run end to end"):SMOKE.index("# --- 5: notify")]
STEP_F = FRESH[FRESH.index("# ==== f) a real task"):FRESH.index("# ==== g)")]
MUST = FRESH[FRESH.index('bad="" ASSERTION=0'):FRESH.index("say() {")]

GH = r'''#!/bin/bash
echo "$*" >>"$FAKE/gh.log"
case "$*" in
  "api user --jq .login") echo caller ;;
  # made whole or not at all: a gate that loses the race to make it clones the winner's
  "repo create caller/agentkit-smoke --private")
    new=$(mktemp -d "$FAKE/new-XXXXXX") && git init -q --bare "$new" &&
      install -m 755 "$FAKE/update" "$new/hooks/update" && mv -T "$new" "$FAKE/origin.git" ;;
  "repo clone caller/agentkit-smoke "*" -- -q") git clone -q "$FAKE/origin.git" "$4" ;;
  *) exit 97 ;;
esac
'''
# Origin's update hook says which gate wrote which ref, and refuses `main` once it is made.
HOOK = '''#!/bin/sh
echo "$WORK $1" >>"$FAKE/updates"
[ "$1" != refs/heads/main ] || [ "$2" = 0000000000000000000000000000000000000000 ]
'''
# A run cut from the base the task or the clone's origin/HEAD names, its fix pushed as `ak/<id>`
# and merged into that base once every gate's run is this far, all three gates' branches on
# origin then.
AK = r'''#!/bin/bash
if [ "$2" = clean ]; then rm -rf -- "$HOME/wt-$3"; exit 0; fi
task=$2 id=fake-$$ wt=$HOME/wt-fake-$$
repo=$(sed -n 's/^repo: //p' "$task") && repo=${repo:-$PWD}
base=$(sed -n 's/^base: /origin\//p' "$task")
[ -n "$base" ] || base=$(git -C "$repo" symbolic-ref --short refs/remotes/origin/HEAD) || exit 1
echo "[12:00:00] run $id: on $base"
git -C "$repo" worktree add -q -b "ak/$id" "$wt" "$base" || exit 1
marker=$(sed -n "s/^grep -qxF '\(.*\)' \(.*\)$/\2 \1/p" "$task")
if [ -n "$marker" ]; then echo "${marker#* }" >"$wt/${marker%% *}"
else printf 'def hello():\n    return "hello"\n' >"$wt/hello.py"; fi
git -C "$wt" add -A && git -C "$wt" commit -qm fix && git -C "$wt" push -q origin "ak/$id" || exit 1
touch "$FAKE/merging-$$"
for _ in $(seq 600); do
  [ "$(ls "$FAKE" | grep -c '^merging-')" = 3 ] && break
  sleep .1
done
[ "$(ls "$FAKE" | grep -c '^merging-')" = 3 ] || { echo "the other gates never ran" >&2; exit 1; }
git -C "$wt" push -q origin "HEAD:refs/heads/${base#origin/}" || exit 1
mkdir -p "$HOME/.agentkit/runs/$id"
printf 'VERDICT: PASS\nmerged: yes\npr: https://example.invalid/pull/%s\n' $$ \
  >"$HOME/.agentkit/runs/$id/result.md"
printf '{"repo": "%s", "worktree": "%s"}\n' "$repo" "$wt" >"$HOME/.agentkit/runs/$id/run.json"
echo "[12:00:01] round 1: PASS" >"$HOME/.agentkit/runs/$id/log.txt"
'''
PYTEST = '''import pathlib, runpy
for path in pathlib.Path("tests").glob("test_*.py"):
    for name, test in runpy.run_path(str(path)).items():
        if name.startswith("test_"):
            test()
'''


class OneSandboxRepo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="one-sandbox-repo-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        stub = root / "repo/tests"
        for path in (stub, root / "bin", root / "py/pytest"):
            path.mkdir(parents=True)
        (stub / "check4_pair.py").write_text('print("exec-model review-model")')
        for name in ("sandbox_branch.py", "verify_delivery.py"):
            (stub / name).symlink_to(REPO / "tests" / name)
        (root / "py/pytest/__main__.py").write_text(PYTEST)
        (root / "update").write_text(HOOK)
        for name, text in (("gh", GH), ("ak", AK)):
            (root / "bin" / name).write_text(text)
            (root / "bin" / name).chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("AGENTKIT_", "AK_"))}
        self.env.update(FAKE=str(root), REPO=str(root / "repo"), PYTHONPATH=str(root / "py"),
                        PATH=f"{root / 'bin'}:{os.environ['PATH']}", GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_GLOBAL=str(root / "gitconfig"))
        (root / "gitconfig").write_text("[user]\n\tname = fixture\n\temail = fixture@localhost\n")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root / "origin.git"), *args], check=True,
                              text=True, capture_output=True, env=self.env).stdout.split()

    def gate(self, name, script, **env):
        (self.root / name / "home").mkdir(parents=True, exist_ok=True)
        return subprocess.Popen(
            ["bash", "-c", f"set -uo pipefail\n. {REPO}/tests/acceptance.sh\n{script}\nfinish"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env={**self.env, "WORK": str(self.root / name), **env})

    def smoke(self, name):
        home = str(self.root / name / "home")
        return self.gate(name, CHECK4, HOME=home, SMOKE_CALLER_HOME=home)

    def fresh(self):
        home = self.root / "fresh/home"
        (home / "e2e").mkdir(parents=True)
        (home / "agentkit").symlink_to(self.root / "repo")
        stubs = ('doing() { :; }; here() { :; }\n'
                 'as() { HOME="$UH" bash -c "cd \\"\\$HOME\\" || exit 1; $1"; }\n')
        return self.gate("fresh", MUST + stubs + STEP_F, UH=str(home),
                         HOME=str(self.root / "caller"), MARKER="e2e-marker.txt", TS="0")

    def test_two_smoke_suites_and_a_fresh_gate_share_one_repository_at_once(self):
        gates = {"smoke-1": self.smoke("smoke-1"), "smoke-2": self.smoke("smoke-2"),
                 "fresh": self.fresh()}
        outs = {name: proc.communicate(timeout=300)[0] for name, proc in gates.items()}
        self.assertEqual({name: proc.returncode for name, proc in gates.items()},
                         dict.fromkeys(gates, 0), "\n".join(outs.values()))
        for name, out in outs.items():
            if name == "fresh":
                self.assertIn("PASS  f  a real task, orchestrated headlessly: pr: https://", out)
            else:
                self.assertIn("PASS  4 ak run: pr: https://example.invalid/pull/", out)
                self.assertIn("PASS  4b ak run clean", out)
        updates = [line.split() for line in (self.root / "updates").read_text().splitlines()]
        for name in gates:
            work = self.root / name
            branch = re.search(r"^caller/agentkit-smoke: (\S+)$", (work / "seed.log").read_text(),
                               re.M)[1]
            # its run based on its own branch, and that branch and the run's are all it wrote
            run_id = re.search(rf"^\[[\d:]+\] run (\S+): on origin/{branch}$",
                               (work / "run.log").read_text(), re.M)[1]
            self.assertEqual({ref for who, ref in updates if who == str(work)} - {"refs/heads/main"},
                             {f"refs/heads/{branch}", f"refs/heads/ak/{run_id}"})
        # all gone, `main` as it was made
        self.assertEqual(self.git("for-each-ref", "--format=%(refname)"), ["refs/heads/main"])
        self.assertEqual(self.git("rev-list", "--count", "main"), ["1"])
        # one repository, made by whichever gate came first
        self.assertEqual({" ".join(line.split()[:3]) for line in
                          (self.root / "gh.log").read_text().splitlines()},
                         {"api user --jq", "repo create caller/agentkit-smoke",
                          "repo clone caller/agentkit-smoke"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
