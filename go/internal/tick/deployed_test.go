package tick

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A deployed release whose health fails a third time, past its grace, is where a revert starts,
// which is Python's: the merge checks leave it there, its probes' readings kept as Python keeps
// them and no revert opened.  One the project rolled back itself is no live release, and Go carries it.
func TestARevertDueIsLeftToPython(t *testing.T) {
	for deployed, left := range map[string]bool{"true": true, "false": false} {
		t.Run(deployed, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			path := filepath.Join(ak, "runs", "fix-api", "run.json")
			now := time.Now().Unix()
			put(t, path, fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1", "merge_sha": "abc", "repo": "/", `+
				`"health": {"command": "false"}, "deployed": %q, "deployed_passed": true, "deployed_at": %d, "health_failures": 2}`,
				now-600, deployed, now-revertGrace-1))
			if err := checking(t, io.Discard).mergeChecks(); errors.Is(err, errLeft) != left || !left && err != nil {
				t.Fatal(err)
			}
			record, _ := run.ReadJSON(path)
			failures, want := record.Get("health_failures"), map[bool]string{true: "3", false: "0"}[left]
			if failures != run.Number(want) || record.Truthy("deployed_passed") != left || record.Truthy("live_at") {
				t.Fatalf("recorded %s", run.Line(record))
			}
			if runs, _ := os.ReadDir(filepath.Join(ak, "runs")); len(runs) != 1 {
				t.Errorf("%d runs", len(runs))
			}
		})
	}
}
