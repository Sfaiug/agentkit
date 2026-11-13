//go:build unix

package tick

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A seat up at its prompt owing work, whose run merged and had its ending read at its look, with
// no other run of it going, waits on that merge going live: a tick finding the pass types its line
// alone once and marks the run told, and a second tick types nothing.
func TestALiveNoticeItsSeatWaitsOnIsTypedAloneOnce(t *testing.T) {
	ak, home := forkSeat(t)
	put(t, filepath.Join(ak, "state", "plan-lead.md"), "- [ ] The work is done · check: `false` · lead · written 2026-10-23 09:00\n")
	path := filepath.Join(ak, "runs", "fix-api", "run.json")
	put(t, path, fmt.Sprintf(`{"run_id": "fix-api", "state": "pass", "merged": true, "finished_at": %d, "pr": "https://github.com/acme/api/pull/1",
		"merge_sha": "abc", "repo": "/", "health": {"command": "true"}, "deployed": null, "launched_session": "lead",
		"handed_back": %[1]d, "reported": true, "handback_note": "read by its seat's own ak run status or ak wait: printed there, not typed"}`,
		time.Now().Unix()))
	line := "run fix-api is live: https://github.com/acme/api/pull/1."
	for tick := range 2 {
		var said bytes.Buffer
		if err := checking(t, &said).mergeChecks(); err != nil {
			t.Fatalf("tick %d: %v", tick, err)
		}
		typed, _ := os.ReadFile(filepath.Join(home, "keys"))
		record, _ := run.ReadJSON(path)
		if string(typed) != line+"\nEnter\n" || !record.Truthy("live_at") || !record.Truthy("live_notified") || record.Has("live_typed") {
			t.Fatalf("tick %d typed %q, recording %s", tick, typed, run.Line(record))
		}
		if told := strings.Contains(said.String(), "told the lead seat: "+line+"\n"); told != (tick == 0) {
			t.Fatalf("tick %d said %q", tick, said.String())
		}
	}
}
