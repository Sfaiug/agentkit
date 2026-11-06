//go:build unix

package tick

import (
	"bytes"
	"io"
	"path/filepath"
	"testing"
	"time"
)

func TestSettledRunsLeaveEveryRowIdleAndTheirBytesAlone(t *testing.T) {
	ak, _ := idleHome(t, answers)
	for _, state := range []string{"pass", "fail", "stopped", "not_needed", "blocked", "error"} {
		put(t, filepath.Join(ak, "runs", state, "run.json"), `{"state":"`+state+`", "handed_back":true, "reported":true, "tree_stopped":[null,null]}`)
		put(t, filepath.Join(ak, "runs", state, "result.md"), "the result\n")
	}
	// a park an older ak left reads as a stopped run that is over, its holder ended or not (#2480)
	put(t, filepath.Join(ak, "runs", "parked", "run.json"), `{"state":"stopped","lease_wait":{"on":"pass"}, "handed_back":true, "reported":true, "tree_stopped":[null,null]}`)
	put(t, filepath.Join(ak, "runs", "parked", "result.md"), "the result\n")
	before := files(t, filepath.Join(ak, "runs"))
	for range 2 {
		var out bytes.Buffer
		if !carries(&out, io.Discard) {
			t.Fatalf("left settled runs to Python: %s", &out)
		}
		for path, want := range before {
			if want != "" && read(t, path) != want {
				t.Fatalf("idle tick rewrote %s", path)
			}
		}
	}
}

// A record changes after the preceding row: each row must read it at its own turn, leave
// that record byte for byte, and stop before the following row when its work is Python's.
func TestRunWorkHandsOverAtItsOwnRow(t *testing.T) {
	for row, due := range map[string]string{
		"login resume":     `{"state":"waiting_login"}`,
		"seat health":      `{"state":"waiting_login"}`,
		"dead loops":       `{"state":"running","scope":"acme.scope"}`,
		"stall recovery":   `{"state":"stalled"}`,
		"exhausted resume": `{"state":"exhausted","error":"reviewer: API/transport errors"}`,
		"error retry":      `{"state":"error","error_retry_at":1,"title":"\ud800"}`,
		"waiting resume":   `{"state":"fail","waiting_on":{"line":"older"}}`,
		"endings":          `{"state":"pass","launched_session":"acme","merged":true}`,
	} {
		t.Run(row, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			path := filepath.Join(ak, "runs", "fix-api", "run.json")
			put(t, path, `{"state":"stopped"}`)
			tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
			var chosen pass
			for _, each := range table(tick) {
				if each.name == row {
					chosen = each
				}
			}
			if chosen.idle == nil || !chosen.idle() {
				t.Fatal("stopped run was not idle")
			}
			after := false
			if tick.through([]pass{
				{"before", false, nil, func() error { put(t, path, due); return nil }}, chosen,
				{"after", false, nil, func() error { after = true; return nil }},
			}) || after || read(t, path) != due {
				t.Fatal("did not hand over at this row without writing")
			}
		})
	}
}

func TestHousekeepingReadsRunWritersAndRepositories(t *testing.T) {
	ak, _ := idleHome(t, answers)
	path := filepath.Join(ak, "runs", "fix-api", "run.json")
	put(t, path, `{"repo":"/acme/api","worktree":"/acme/work","pid":"unreadable"}`)
	var repos, busy []string
	if !runRepositories(&repos) || !runBusyPaths(&busy) || len(repos) != 1 || len(busy) != 2 {
		t.Fatalf("repos=%v, busy=%v", repos, busy)
	}
	put(t, path, `{"waiting_on":{"line":"older"}}`)
	if runBusyPaths(&busy) {
		t.Fatal("a lander's separate writer was not left to Python")
	}
}
