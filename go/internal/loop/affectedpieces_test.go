//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// A round's suite in pieces is the target's red only where each red piece named tests that fail
// there too, as Python's affected_suite judges it: a red piece naming none keeps the red the
// change's, though the one test another piece named fails on the target alone.
func TestARedPieceNamingNoTestKeepsTheRoundSuiteRed(t *testing.T) {
	l, r := repoRig(t)
	t.Setenv("AK_MAX_RUNS", "0") // no heavy-suite turn to wait for
	t.Setenv("AK_HOST_READINGS", `{"cpus":8,"free_mb":16400,"mem_total_mb":65536}`)
	for name, text := range map[string]string{
		"AGENTS.md": "---\nhealth: none\nusers: none\ntests: : \"$AK_SHARD\"; sh suite.sh \"$AK_CHANGED\"\n---\n# acme\n",
		// the first piece, and t/a.sh alone, name t/a.sh; every other piece names nothing
		"suite.sh": "[ -z \"$AK_ONLY\" ] || cp \"$AK_ONLY\" \"$AK_RAN\"\ncase $AK_SHARD in 1/*) echo t/a.sh >\"$AK_FAILED\";; esac\nexit 1\n",
	} {
		if err := os.WriteFile(filepath.Join(r.repo, name), []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	shell(t, r.repo, "git add -A && git commit -qm suite && git clone -q --bare . ../remote.git && git remote add origin ../remote.git && git fetch -q origin")
	r.baseSHA = strings.TrimSpace(shell(t, r.repo, "git rev-parse main"))
	shell(t, r.wt, "git reset -q --hard "+r.baseSHA+" && echo v2 > widget.txt && git commit -qam change")
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "base_sha", r.baseSHA, "base", "main", "target", "main", "round_summaries", []any{})
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	ok, text, err := r.affectedSuite(l)
	if err != nil || ok || !strings.Contains(text, "--- AK_SHARD=2/") || strings.Contains(text, "the target's own") {
		t.Fatalf("ok=%v err=%v:\n%s", ok, err, text)
	}
}
