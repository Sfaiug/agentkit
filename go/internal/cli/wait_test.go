package cli

import (
	"path/filepath"
	"testing"
)

// A wait whose answer hangs on what Go does not read yet is Python's: exit 3, nothing written.
func TestAWaitGoCannotDecideIsPythons(t *testing.T) {
	deferred := "- [ ] later · check: `true` · ~/code/acme · deferred · written 2026-10-01 10:00\n"
	for name, files := range map[string]map[string]string{
		"an exhausted run":                 {"runs/r/run.json": `{"state": "exhausted"}`},
		"an ending owed to the seat":       {"runs/r/run.json": `{"state": "fail", "launched_session": "acme", "handback_pending": true}`},
		"a done plan beside its own runs":  {"runs/r/run.json": `{"state": "running", "launched_session": "acme"}`, "state/plan-acme.md": "- [x] Fix the api\n"},
		"a done plan with a deferred line": {"runs/r/run.json": `{"state": "running"}`, "state/plan-acme.md": deferred + "- [x] Fix the api\n"},
		"a restart that loops":             {"runs/r/run.json": `{"lease_restarted": "s"}`, "runs/s/run.json": `{"lease_restarted": "r"}`},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			t.Setenv("AGENTKIT_SESSION", "acme")
			for path, content := range files {
				write(t, filepath.Join(home, ".agentkit", path), content)
			}
			assertCall(t, []string{"wait", "r"}, 3, "", "ak wait: not implemented in Go yet\n")
		})
	}
}
