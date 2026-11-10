//go:build linux

package launch

import (
	"errors"
	"io"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// Python's run.main dispatches merge before any seat check and cmd_merge reads no seat, so a
// seat delivering its own run gets the merge anyone typing it would: Go's, here its refusal of a
// run no review passed.
func TestASeatsOwnMergeIsGos(t *testing.T) {
	home := queuedHome(t)
	// ungated: the gate decides no merge
	t.Setenv("AK_MAX_RUNS", "0")
	t.Setenv("AGENTKIT_SESSION", "acme")
	write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"), `{"created": 1}`)
	if seat, _, err := Seat(); seat != "acme" || err != nil {
		t.Fatalf("seat %q, %v", seat, err)
	}
	dir := filepath.Join(run.Runs(), "fix-api")
	write(t, filepath.Join(dir, "task.md"), "# Fix the API\n\n## Done when\n```bash\ntrue\n```\n")
	if err := run.Create(dir, run.Fields("run_id", "fix-api", "state", "pass", "repo", t.TempDir(), "worktree", t.TempDir())); err != nil {
		t.Fatal(err)
	}
	code, why, err := Merge("fix-api", io.Discard, io.Discard)
	if errors.Is(err, ErrPython) || code != 2 || why != "fix-api: merge requires a successful reviewer allowed by the model policy; run ak run resume fix-api to obtain review" {
		t.Fatalf("%d, %q, %v", code, why, err)
	}
}
