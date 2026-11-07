//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// The file AK_CHANGED names holds each path the merge edits as git names it, a first one starting
// with a space included.
func TestTheRoundSuiteSeesAPathStartingWithASpace(t *testing.T) {
	l, r := repoRig(t)
	t.Setenv("AK_MAX_RUNS", "0") // no heavy-suite turn to wait for
	for name, text := range map[string]string{
		"AGENTS.md": "---\nhealth: none\nusers: none\ntests: sh suite.sh \"$AK_CHANGED\"\n---\n# acme\n",
		"suite.sh":  "git diff --name-only --no-renames HEAD^1 HEAD > expected\ncmp \"$1\" expected\n",
	} {
		if err := os.WriteFile(filepath.Join(r.repo, name), []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	shell(t, r.repo, "git add -A && git commit -qm suite && git clone -q --bare . ../remote.git && git remote add origin ../remote.git && git fetch -q origin")
	r.baseSHA = strings.TrimSpace(shell(t, r.repo, "git rev-parse main"))
	shell(t, r.wt, "git reset -q --hard "+r.baseSHA+" && echo added > ' widget.txt' && git add -A && git commit -qm change")
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "base_sha", r.baseSHA, "base", "main", "target", "main", "round_summaries", []any{})
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	ok, text, err := r.verify(l, filepath.Join(l.roundDir(), "donewhen.log"))
	if err != nil || !ok || !strings.Contains(text, "AK_CHANGED listing its 1 paths") {
		t.Fatalf("the suite did not see the path as git names it: %v\n%s", err, text)
	}
}
