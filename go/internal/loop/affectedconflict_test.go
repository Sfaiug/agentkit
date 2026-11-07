//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// A sibling reaching the target after the round met it, with a change conflicting with the round's,
// is landing's to bring in: the round's suite meets the target the run last integrated with, and
// where the change does not merge onto that either, the suite does not run and the round fails.
func TestTheRoundSuiteMeetsTheLastTargetWhereASiblingConflicts(t *testing.T) {
	for _, met := range []string{"base", "sibling"} {
		t.Run(met, func(t *testing.T) {
			l, r := repoRig(t)
			t.Setenv("AK_MAX_RUNS", "0") // no heavy-suite turn to wait for
			for name, text := range map[string]string{
				"AGENTS.md": "---\nhealth: none\nusers: none\ntests: sh suite.sh \"$AK_CHANGED\"\n---\n# acme\n",
				"suite.sh":  "cat \"$1\"\n",
			} {
				if err := os.WriteFile(filepath.Join(r.repo, name), []byte(text), 0o666); err != nil {
					t.Fatal(err)
				}
			}
			shell(t, r.repo, "git add -A && git commit -qm suite && git clone -q --bare . ../remote.git && git remote add origin ../remote.git && git fetch -q origin")
			r.baseSHA = strings.TrimSpace(shell(t, r.repo, "git rev-parse main"))
			shell(t, r.wt, "git reset -q --hard "+r.baseSHA+" && echo 'x = 2' > widget.txt && git commit -qam change")
			sibling := strings.TrimSpace(shell(t, r.repo, "echo 'x = 3' > widget.txt && git commit -qam sibling && git push -q origin main && git rev-parse HEAD"))
			last := map[string]string{"base": r.baseSHA, "sibling": sibling}[met]
			if err := run.Change(l.dir, func(record *run.Object) error {
				run.SetAll(record, "base_sha", r.baseSHA, "target_sha", last, "base", "main", "target", "main", "round_summaries", []any{})
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			ok, text, err := r.affectedSuite(l)
			if err != nil {
				t.Fatal(err)
			}
			log, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
			if !strings.Contains(string(log), "origin/main moved to "+sibling[:12]+" with a change conflicting with this one, which landing brings in; the round meets "+last[:12]) {
				t.Fatalf("the log does not say which target the round meets:\n%s", log)
			}
			onto := "merged onto origin/main at " + last[:12]
			if met == "base" && (!ok || !strings.Contains(text, onto+", AK_CHANGED listing its 1 paths")) {
				t.Fatalf("the suite did not pass on the last target:\n%s", text)
			}
			if met == "sibling" && (ok || !strings.Contains(text, "[not run: ") || !strings.Contains(text, onto+" does not merge cleanly]")) {
				t.Fatalf("a change that does not merge onto the last target ran its suite:\n%s", text)
			}
		})
	}
}
