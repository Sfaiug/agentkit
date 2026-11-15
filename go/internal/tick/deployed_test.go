//go:build unix

package tick

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A deployed release whose health fails a third time, past its grace, is where a revert starts,
// which is Python's: the merge checks leave it there, its probes' readings kept as Python keeps
// them and no revert opened, a newer merge not yet deployed hiding none of it.  One whose diff
// changes a schema is named for its seat instead, and one the project rolled back itself is no
// live release: Go carries both.
func TestARevertDueIsLeftToPython(t *testing.T) {
	for name, each := range map[string]struct {
		deployed, file      string
		newer, left, schema bool
	}{
		"due":                    {deployed: "true", file: "api.txt", left: true},
		"schema":                 {deployed: "true", file: "db/schema.SQL", schema: true},
		"rolled back":            {deployed: "false", file: "api.txt"},
		"behind a waiting merge": {deployed: `test "$AK_MERGE_SHA" != new`, file: "api.txt", newer: true, left: true},
	} {
		t.Run(name, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			repo := t.TempDir()
			git := func(args ...string) string {
				t.Helper()
				out, err := exec.Command("git", append([]string{"-C", repo, "-c", "user.name=acme", "-c", "user.email=acme@example.com"}, args...)...).CombinedOutput()
				if err != nil {
					t.Fatalf("git %v: %s", args, out)
				}
				return strings.TrimSpace(string(out))
			}
			git("init", "-q", "-b", "main")
			git("commit", "-q", "--allow-empty", "-m", "before")
			put(t, filepath.Join(repo, each.file), "release\n")
			git("add", ".")
			git("commit", "-q", "-m", "release")
			now := time.Now().Unix()
			merge := func(name, sha string, ago int64, fields string) string {
				path := filepath.Join(ak, "runs", name, "run.json")
				put(t, path, fmt.Sprintf(`{"merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1", "merge_sha": %q, "repo": %q, `+
					`"health": {"command": "false"}, "deployed": %q, %s}`, now-ago, sha, repo, each.deployed, fields))
				return path
			}
			path := merge("old", git("rev-parse", "HEAD"), 600, fmt.Sprintf(`"deployed_passed": true, "deployed_at": %d, "health_failures": 2`, now-revertGrace-1))
			if each.newer {
				merge("new", "new", 599, `"deployed_passed": false, "health_failures": 0`)
			}
			if err := checking(t, io.Discard).mergeChecks(); errors.Is(err, errLeft) != each.left || !each.left && err != nil {
				t.Fatal(err)
			}
			record, _ := run.ReadJSON(path)
			served := each.deployed != "false"
			failures, want := record.Get("health_failures"), map[bool]string{true: "3", false: "0"}[served]
			if failures != run.Number(want) || record.Truthy("deployed_passed") != served || record.Truthy("live_at") {
				t.Fatalf("recorded %s", run.Line(record))
			}
			if runs, _ := os.ReadDir(filepath.Join(ak, "runs")); len(runs) != map[bool]int{false: 1, true: 2}[each.newer] {
				t.Errorf("%d runs", len(runs))
			}
			if kept, _ := os.ReadFile(filepath.Join(ak, "state", "watch.json")); strings.Contains(string(kept), revertSchema) != each.schema {
				t.Errorf("watch.json holds %s", kept)
			}
		})
	}
}
