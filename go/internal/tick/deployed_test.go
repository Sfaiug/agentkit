//go:build unix

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
// them and no revert opened, a newer merge not yet deployed hiding none of it.  One the project
// rolled back itself is no live release, and Go carries it.
func TestARevertDueIsLeftToPython(t *testing.T) {
	for name, each := range map[string]struct {
		deployed    string
		newer, left bool
	}{
		"due":                    {deployed: "true", left: true},
		"rolled back":            {deployed: "false"},
		"behind a waiting merge": {deployed: `test "$AK_MERGE_SHA" = old`, newer: true, left: true},
	} {
		t.Run(name, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			now := time.Now().Unix()
			merge := func(sha string, ago int64, fields string) string {
				path := filepath.Join(ak, "runs", sha, "run.json")
				put(t, path, fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1", "merge_sha": %q, "repo": "/", `+
					`"health": {"command": "false"}, "deployed": %q, %s}`, now-ago, sha, each.deployed, fields))
				return path
			}
			path := merge("old", 600, fmt.Sprintf(`"deployed_passed": true, "deployed_at": %d, "health_failures": 2`, now-revertGrace-1))
			if each.newer {
				merge("new", 599, `"deployed_passed": false, "health_failures": 0`)
			}
			if err := checking(t, io.Discard).mergeChecks(); errors.Is(err, errLeft) != each.left || !each.left && err != nil {
				t.Fatal(err)
			}
			record, _ := run.ReadJSON(path)
			failures, want := record.Get("health_failures"), map[bool]string{true: "3", false: "0"}[each.left]
			if failures != run.Number(want) || record.Truthy("deployed_passed") != each.left || record.Truthy("live_at") {
				t.Fatalf("recorded %s", run.Line(record))
			}
			if runs, _ := os.ReadDir(filepath.Join(ak, "runs")); len(runs) != map[bool]int{false: 1, true: 2}[each.newer] {
				t.Errorf("%d runs", len(runs))
			}
		})
	}
}
