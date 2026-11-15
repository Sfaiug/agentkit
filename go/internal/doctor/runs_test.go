//go:build unix

package doctor

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A death on the record is the loop's only where it ended the loop the record names now: a resume
// leaves an earlier loop's there, of another pid or noted before this loop started.
func TestOnlyTheCurrentLoopsDeathCounts(t *testing.T) {
	for name, each := range map[string]struct {
		state         string
		samePID, park bool
		lost          bool
	}{
		"a loop resumed after a park died":                  {"running", false, true, true},
		"a loop resumed after a park died, its pid reused":  {"running", true, true, true},
		"an interruption after an older loop's death":       {"interrupted", false, false, false},
		"an interruption after an older loop's, pid reused": {"interrupted", true, false, false},
	} {
		t.Run(name, func(t *testing.T) {
			root, _ := home(t, models)
			ended := exec.Command("true")
			if err := ended.Run(); err != nil {
				t.Fatal(err)
			}
			earlier := ended.Process.Pid + 1
			if each.samePID {
				earlier = ended.Process.Pid
			}
			now := float64(time.Now().UnixNano()) / 1e9
			record := run.Fields("run_id", "fix-api", "state", each.state, "started_at", now-10000, "pid", ended.Process.Pid,
				"process_identity", run.Fields("boot", "acme-boot", "ticks", 0, "started_at", now-300),
				"deaths", []any{run.Fields("at", now-900, "pid", earlier, "parked", each.park)})
			dir := filepath.Join(root, ".agentkit", "runs", "fix-api")
			if err := os.MkdirAll(dir, 0o700); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(dir, "run.json")
			written := time.Now().Add(-240 * time.Second)
			if err := os.WriteFile(path, []byte(run.Line(record)), 0o600); err != nil || os.Chtimes(path, written, written) != nil {
				t.Fatal(err)
			}
			if line, lost, read := census(180); !read || lost != each.lost {
				t.Fatalf("lost=%v read=%v: %s", lost, read, line)
			}
		})
	}
}
