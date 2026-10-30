"""A landing line waiting for its lander, checked once by `ak run --lander`, black-box.

`Line` makes a project in a throwaway Home (tests/fixtures/akbin.py) with a bare origin
(tests/fixtures/gitrig.py) whose `tests:` line is a fake sharded suite, `suite.sh`: each test
`t/<name>` in the share `AK_SHARD` names, or those `AK_ONLY` lists, named as run (`AK_RAN`) and,
failing, as failed (`AK_FAILED`), with the words after `suite.sh` given to every test, each
run logged where a boxed check may write, in the project's Git storage (`Line.runs`).  Each
member is a reviewed branch off main and a run directory (`run.json`, `task.md`) parked in the
line, in join order, numbered with the members of every line in its Home.  Host readings are
injected (`AK_HOST_READINGS`), and a woken member's resume refuses at once (a worker's worker's
run), so a verdict stays on its record to be read.

    from fixtures.akline import Line
    line = Line({"t/ok.sh": "true\\n"})
    line.member({"api.txt": "x\\n"})
    assert line.land().code == 0 and "land" in line.verdict(1)
    line.close()
"""

import json

from fixtures.akbin import Home
from fixtures.gitrig import Rig

READINGS = json.dumps({"cpus": 4, "load": 0, "free_mb": 16000})
SUITE = ': "$AK_SHARD"; sh suite.sh'
RUNNER = """share=${AK_SHARD:-1/1}; k=${share%/*}; n=${share#*/}
log="$(git rev-parse --git-common-dir)/suite.log"
if [ -n "${AK_ONLY:-}" ]; then echo "alone $*" >>"$log"; tests=$(cat "$AK_ONLY")
else echo "piece $share $*" >>"$log"; tests=; i=0
  for t in $(ls t); do [ $((i % n + 1)) = "$k" ] && tests="$tests $t"; i=$((i + 1)); done; fi
code=0
for t in $tests; do
  [ -f "t/$t" ] || continue
  echo "$t" >>"${AK_RAN:-/dev/null}"
  sh "t/$t" "$@" || { echo "FAIL $t"; echo "$t" >>"${AK_FAILED:-/dev/null}"; code=1; }
done
exit $code
"""


def rules(suite):
    """An AGENTS.md declaring `suite` as the `tests:` line."""
    return f"---\ntests: {suite}\n---\n# acme\n"


class Line:
    def __init__(self, tests, home=None, name="acme"):
        """`tests`, path -> text, are the target's tests (`t/<name>`) and any other files; a
        `home` holding another line, which closes it, holds this one's project `name` too."""
        self.home = home or Home()
        self.rig = Rig(self.home, name, files={"AGENTS.md": rules(SUITE), "suite.sh": RUNNER,
                                               **tests})
        self.line = f".merge-{name}.lock"
        self.base = self.rig.head()
        self.members = []

    def close(self):
        self.home.close()

    def member(self, files):
        """Park the next member, its branch adding `files`, behind those before it."""
        n = len(list((self.home.path / ".agentkit" / "runs").glob("fix-*"))) + 1
        name = f"fix-{n}"
        head = self.rig.branch(f"ak/{name}", files)
        directory = self.home.path / ".agentkit" / "runs" / name
        directory.mkdir(parents=True)
        (directory / "task.md").write_text(f"# {name}\n\n## Done when\n```bash\ntrue\n```\n")
        tree = self.rig.git("rev-parse", f"{head}^{{tree}}")
        (directory / "run.json").write_text(json.dumps({
            "run_id": name, "state": "waiting", "rounds": 3, "scope": "none", "run_depth": 2,
            "repo": str(self.rig.path), "worktree": str(self.rig.path), "branch": f"ak/{name}",
            "base": "origin/main", "target": "main", "base_sha": self.base,
            "merge_method": "squash",
            "review": {"verdict": "PASS", "done_when": True, "passed_head_sha": head,
                       "head_sha": head, "tree_sha": tree},
            "waiting_on": {"line": self.line, "joined": n}}))
        self.members.append(directory)

    def land(self, timeout=600):
        """One lander pass over the line."""
        return self.home.ak("run", "--lander", self.line, timeout=timeout,
                            env={"AK_HOST_READINGS": READINGS})

    def verdict(self, n):
        """What the lander left member `n` (1-based) waiting on."""
        return json.loads((self.members[n - 1] / "run.json").read_text())["waiting_on"]

    def runs(self):
        """Every suite run, oldest first: ("piece", share, words) for a piece, or ("alone",
        words) for named tests alone, the words those after `suite.sh`."""
        try:
            lines = (self.rig.path / ".git" / "suite.log").read_text().splitlines()
        except FileNotFoundError:
            return []
        return [tuple(line.split(" ", 2 if line.startswith("piece") else 1)) for line in lines]

    def whole(self, words=""):
        """How many times the suite with `words`, the target's with none, ran whole: each whole
        run starts piece 1 once, and a red piece that names its failed tests runs just those
        again."""
        return sum(run[0] == "piece" and run[1].startswith("1/") and run[2] == words
                   for run in self.runs())
