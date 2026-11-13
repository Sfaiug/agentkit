//go:build linux

package loop

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

const sproutSuite = `: "$AK_SHARD"; sh suite.sh`

// sproutRig is a repository whose suite runs in two pieces, the first timing the anchor, at 1000s
// where the suite is run `generous`, and, where it is not run with `anchor`, an added sprout at
// 120s: over the 60s target alone.
func sproutRig(t *testing.T, anchored bool) (*loop, *repoPlace) {
	t.Helper()
	l, r := repoRig(t)
	t.Setenv("AK_MAX_RUNS", "")
	t.Setenv("AK_HOST_READINGS", `{"cpus":4,"load":0,"free_mb":400,"mem_total_mb":65536}`)
	suite := sproutSuite
	if anchored {
		suite += " anchor"
	}
	for name, text := range map[string]string{
		"AGENTS.md":            "---\nhealth: none\ntests: " + suite + "\n---\n# Acme\n",
		"tests/test_anchor.py": "anchor\n",
		"suite.sh": "if [ \"${AK_SHARD%/*}\" = 1 ]; then\n  seconds=0; [ \"${1:-}\" = generous ] && seconds=1000\n" +
			"  printf 'PASS  tests/test_anchor.py (%ss)\\n' \"$seconds\"\n" +
			"  if [ \"${1:-}\" != anchor ] && [ -f tests/test_sprout.py ]; then printf 'PASS  tests/test_sprout.py (120s)\\n'; fi\nfi\n",
	} {
		path := filepath.Join(r.repo, name)
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	shell(t, r.repo, "git add -A && git commit -qm suite")
	r.baseSHA = strings.TrimSpace(shell(t, r.repo, "git rev-parse HEAD"))
	shell(t, r.wt, "git checkout -q --detach "+r.baseSHA)
	return l, r
}

// addSprout commits the slow sprout on the worktree, with the suite run without `anchor`.
func addSprout(t *testing.T, r *repoPlace) {
	t.Helper()
	shell(t, r.wt, "mkdir -p tests && echo slow >tests/test_sprout.py && printf -- '---\\nhealth: none\\ntests: %s\\n---\\n# Acme\\n' '"+
		sproutSuite+"' >AGENTS.md && git add -A && git commit -qm sprout")
}

func TestTheFinalCheckRefusesAnAddedFileOverTheSuiteItRewrites(t *testing.T) {
	for _, anchored := range []bool{false, true} {
		t.Run(fmt.Sprint("anchored=", anchored), func(t *testing.T) {
			l, r := sproutRig(t, anchored)
			addSprout(t, r)
			if err := os.WriteFile(filepath.Join(l.dir, "task.md"), []byte("# Add sprout\n\n## Done when\n```bash\ntrue\n```\n"), 0o600); err != nil {
				t.Fatal(err)
			}
			ok, err := r.finalCheck(l)
			log, _ := os.ReadFile(filepath.Join(l.dir, "final-check.log"))
			if ok || !strings.Contains(string(log), "$ "+sproutSuite+"\n[test file over piece target]\nFAIL  tests/test_sprout.py: 120s exceeds the piece target 60s") {
				t.Fatalf("ok=%v err=%v\n%s", ok, err, log)
			}
		})
	}
}

func TestARefusalOnARewrittenSuiteBlamesTheMemberThatAddedTheFile(t *testing.T) {
	_, r := sproutRig(t, true)
	line := sproutLine{t: t, r: r}
	for n := 1; n <= 3; n++ {
		shell(t, r.wt, "git checkout -q --detach "+r.baseSHA)
		if n == 1 {
			addSprout(t, r)
		} else {
			shell(t, r.wt, fmt.Sprintf("echo x >innocent-%d.txt && git add -A && git commit -qm innocent", n))
		}
		line.join()
	}
	for n, record := range line.narrow() {
		fix := record.Dict("waiting_on").Dict("fix")
		if (n == 0) != (fix != nil) || n == 0 && fix.Str("command") != sproutSuite {
			t.Errorf("member %d: %s", n+1, run.Line(record))
		}
	}
}

func TestEachSuiteABatchRewritesIsJudgedOnItsOwnPass(t *testing.T) {
	_, r := sproutRig(t, true)
	line := sproutLine{t: t, r: r}
	addSprout(t, r)
	line.join()
	// the next member, built on the first, rewrites the suite to one whose target is 560s
	shell(t, r.wt, "sed -i 's/sh suite.sh$/sh suite.sh generous/' AGENTS.md && git commit -qam generous")
	line.join()
	first := line.narrow()[0]
	if fix := first.Dict("waiting_on").Dict("fix"); fix == nil || fix.Str("command") != sproutSuite {
		t.Fatalf("the first member landed past its own suite's 60s target: %s", run.Line(first))
	}
}

// A sproutLine is a landing line of members joined from the worktree's commits, in order.
type sproutLine struct {
	t       *testing.T
	r       *repoPlace
	members []member
}

// join adds a member for the worktree's commit, reviewed and waiting on the line.
func (line *sproutLine) join() {
	t := line.t
	t.Helper()
	head, tree, err := line.r.identity()
	if err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(run.Runs(), fmt.Sprintf("sprout-%d", len(line.members)+1))
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	record := run.Fields("state", "waiting", "repo", line.r.repo, "worktree", line.r.wt, "base_sha", line.r.baseSHA, "merge_method", "squash",
		"review", run.Fields("verdict", "PASS", "head_sha", head, "tree_sha", tree),
		"waiting_on", run.Fields("line", ".merge-acme.lock", "joined", len(line.members)+1))
	if err := run.Create(dir, record); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "task.md"), []byte("# Add sprout\n\n## Done when\n```bash\ntrue\n```\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	saved, _ := run.Read(dir)
	line.members = append(line.members, member{dir, saved})
}

// narrow checks the line on the target's tip, and is its members' records after.
func (line *sproutLine) narrow() []*run.Object {
	t := line.t
	t.Helper()
	tree := strings.TrimSpace(shell(t, line.r.repo, "git rev-parse main^{tree}"))
	target := &lineTarget{upstream: "main", tip: line.r.baseSHA, tree: tree, green: map[string]bool{}}
	if err := narrowLine(filepath.Join(run.Runs(), ".merge-acme.lock"), "", line.r.repo, target, line.members, io.Discard); err != nil {
		t.Fatal(err)
	}
	var records []*run.Object
	for _, m := range line.members {
		record, err := run.Read(m.dir)
		if err != nil {
			t.Fatal(err)
		}
		records = append(records, record)
	}
	return records
}
