//go:build unix

package tick

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A gate's line goes only to a seat whose merged run's pull request is on agentkit's repository,
// and one Python's editor put in past a draft, its mark naming the pane, is Python's to finish.
func TestAGateLineGoesToASeatOnItsRepositoryAndAPaneMarkIsPythons(t *testing.T) {
	ak, home := forkSeat(t)
	tick := &ticking{log: newLog(io.Discard, io.Discard)}
	origin, line := "git@github.com:acme/agentkit.git", "Fix the harness install."
	receipt := func(*run.Object) error { return nil }
	keys := func() string {
		data, _ := os.ReadFile(filepath.Join(home, "keys"))
		return string(data)
	}
	merged := filepath.Join(ak, "runs", "merged-run", "run.json")
	put(t, merged, `{"merged": true, "launched_session": "lead"}`)
	if told, err := tick.tellGate("", line, nil, receipt); told != "" || err != nil || keys() != "" {
		t.Fatalf("with no pull request: told %q, gave %v, typed %q", told, err, keys())
	}
	put(t, merged, `{"merged": true, "pr": "https://github.com/acme/agentkit/pull/1", "launched_session": "lead"}`)
	pane := run.Fields("seat", 1000, "line", line, "pane", "%1")
	if told, err := tick.tellGate(origin, line, pane, receipt); told != "" || !errors.Is(err, errLeft) || keys() != "" {
		t.Fatalf("with a pane's mark: told %q, gave %v, typed %q", told, err, keys())
	}
	if told, err := tick.tellGate(origin, line, nil, receipt); told != "lead" || err != nil || keys() != line+"\nEnter\n" {
		t.Fatalf("on agentkit's repository: told %q, gave %v, typed %q", told, err, keys())
	}
}
