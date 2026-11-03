package launch

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestARunNotEndedOnThePullHoldsItWhateverItsSpelling(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	const url = "https://github.com/acme/api/pull/12"
	for _, each := range []struct{ id, key, on, state string }{
		{"ended-review", "review_pr", url, "fail"},
		{"other-pull", "review_pr", "https://github.com/acme/api/pull/13", "running"},
		{"going-task", "pr", "https://github.com/ACME/Api/pull/12/", "waiting"},
	} {
		dir := filepath.Join(run.Runs(), each.id)
		if err := os.MkdirAll(dir, 0o777); err != nil {
			t.Fatal(err)
		}
		if err := run.Create(dir, run.Fields("run_id", each.id, each.key, each.on, "state", each.state)); err != nil {
			t.Fatal(err)
		}
	}
	if taken := runOn(url); taken != "going-task" {
		t.Fatalf("taken = %q", taken)
	}
	if taken := runOn("https://github.com/acme/api/pull/14"); taken != "" {
		t.Fatalf("taken = %q", taken)
	}
}
