package run

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestASeatsParkedRunsAreItsOwnUndecidedOnes(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	for _, each := range []struct {
		name, run, also string
		parked, unread  bool
	}{
		{name: "no run"},
		{name: "running", run: `"state": "running"`},
		{name: "passed", run: `"state": "pass"`},
		{name: "blocked", run: `"state": "blocked", "recovery_pending": true`},
		{name: "another seat's", run: `"state": "interrupted", "launched_session": "beta"`},
		{name: "interrupted", run: `"state": "interrupted"`, parked: true},
		{name: "stalled, though it goes", run: `"state": "stalled"`, parked: true},
		{name: "looked at", run: `"state": "interrupted", "recovery_acknowledged_at": 5`},
		{name: "a failed resume", run: `"state": "fail", "recovery_pending": true`, parked: true},
		{name: "a retry the tick will make", run: `"state": "error", "recovery_pending": true, "error_retry_at": 5, "finished_at": 1799999990`},
		{name: "a line member", run: `"state": "waiting", "recovery_pending": true, "waiting_on": {"line": "acme"}`},
		{name: "replaced by a later merge of its title", run: `"state": "interrupted", "title": "fix", "finished_at": 5`,
			also: `{"state": "pass", "merged": true, "title": "fix", "finished_at": 6, "run_id": "b"}`},
		{name: "a relaunch still going replaces nothing", run: `"state": "interrupted", "branch": "ak/fix", "finished_at": 5`,
			also: `{"state": "running", "from": "ak/fix", "started_at": 6, "run_id": "b"}`, parked: true},
		{name: "exhausted, whose wait is Python's", run: `"state": "exhausted"`, unread: true},
		{name: "exhausted and looked at", run: `"state": "exhausted", "recovery_acknowledged_at": 5`},
		{name: "a record only Python reads", also: `{"title": "\ud800"}`, unread: true},
	} {
		t.Run(each.name, func(t *testing.T) {
			t.Setenv("HOME", t.TempDir())
			t.Setenv("USERPROFILE", os.Getenv("HOME"))
			// a seat that still exists, which is what lets the tick take an ending up
			state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
			if err := os.MkdirAll(state, 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(state, "session-acme.json"), []byte(`{}`), 0o600); err != nil {
				t.Fatal(err)
			}
			records := map[string]string{"b": each.also}
			if each.run != "" {
				records["a"] = `{"launched_session": "acme", "run_id": "a", ` + each.run + `}`
			}
			for id, text := range records {
				if text != "" {
					if err := os.MkdirAll(filepath.Join(Runs(), id), 0o700); err != nil {
						t.Fatal(err)
					}
					if err := os.WriteFile(filepath.Join(Runs(), id, "run.json"), []byte(text), 0o600); err != nil {
						t.Fatal(err)
					}
				}
			}
			census, err := Records()
			parked := false
			if err == nil {
				parked, err = Parked("acme", census, now)
			}
			if parked != each.parked || (err != nil) != each.unread {
				t.Fatalf("parked %v, error %v", parked, err)
			}
		})
	}
}
