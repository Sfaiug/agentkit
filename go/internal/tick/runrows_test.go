//go:build unix

package tick

import (
	"bytes"
	"fmt"
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
		if !Carry(&out, io.Discard) {
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
		"exhausted resume": `{"state":"exhausted","quota_dry":true}`,
		"error retry":      `{"state":"error","error_retry_at":1,"title":"\ud800"}`,
		"waiting resume":   `{"state":"fail","waiting_on":{"line":"older"}}`,
		"endings":          `{"state":"pass","launched_session":"acme","merged":true}`,
		"seat sweep":       `{"state":"running"}`,
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

// An ending nobody heard for over an hour is marked as history, in one line, and replayed to
// nobody; one waiting for its seat, and one under the hour, are left to be told.
func TestOldEndingsAreMarkedNotReplayed(t *testing.T) {
	ak, _ := idleHome(t, answers)
	old := time.Now().Unix() - 7200
	for name, record := range map[string]string{
		"old":     fmt.Sprintf(`{"state":"pass","finished_at":%d}`, old),
		"waiting": fmt.Sprintf(`{"state":"fail","finished_at":%d,"handback_pending":true}`, old),
		"fresh":   fmt.Sprintf(`{"state":"fail","finished_at":%d}`, time.Now().Unix()-60),
	} {
		put(t, filepath.Join(ak, "runs", name, "run.json"), record)
	}
	before := files(t, filepath.Join(ak, "runs"))
	var said bytes.Buffer
	tick := &ticking{log: newLog(&said, io.Discard), clock: time.Now}
	for _, each := range table(tick) {
		if each.name == "old endings" && (each.idle != nil || each.step() != nil) {
			t.Fatal("the row did not carry its sweep")
		}
	}
	if said.String() != "marked 1 pre-existing endings as handed back without replaying (pre-existing ending; not replayed): old\n" {
		t.Errorf("said %q", said.String())
	}
	marked, _ := run.Read(filepath.Join(ak, "runs", "old"))
	if !marked.Truthy("handed_back") || marked.Str("handback_note") != "pre-existing ending; not replayed" {
		t.Errorf("old reads %s", run.Line(marked))
	}
	for _, name := range []string{"waiting", "fresh"} {
		path := filepath.Join(ak, "runs", name, "run.json")
		if read(t, path) != before[path] {
			t.Errorf("%s was rewritten", name)
		}
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
