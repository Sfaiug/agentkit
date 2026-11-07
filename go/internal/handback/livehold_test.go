package handback

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// A merge no seat launched owes no seat its going live (seat_owes_nothing): its ending's line
// never says it, so the live check records it at once.
func TestASeatlessMergeGoneLiveIsRecordedAtOnce(t *testing.T) {
	home := seated(t)
	dir := filepath.Join(home, ".agentkit", "runs", "fix-api")
	record := run.Fields("run_id", "fix-api", "state", "pass", "verdict", "PASS", "merged", true,
		"finished_at", now(), "pr", "https://github.com/acme/api/pull/7")
	if err := os.MkdirAll(dir, 0o700); err != nil || run.Create(dir, record) != nil {
		t.Fatal(err)
	}
	var said []string
	if err := Live(dir, record, seconds(), func(line string) { said = append(said, line) }, false); err != nil {
		t.Fatal(err)
	}
	after, _ := run.Read(dir)
	if len(said) != 1 || !strings.HasSuffix(said[0], "Recorded, not typed") || !after.Truthy("live_notified") {
		t.Fatal(said, run.Line(after))
	}
}
