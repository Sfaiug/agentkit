//go:build unix

package tick

import (
	"io"
	"path/filepath"
	"testing"
	"time"
)

// A run parked on a login is nobody's news at the endings row, its login's page being that: one
// whose dead loop Python's reap has swept already goes by, its record byte for byte, and one it
// has still to sweep is Python's (handback.reap, notify_recovery).
func TestEndingsPassARunParkedOnALoginOnceItsLoopIsSwept(t *testing.T) {
	const parked = `{"state":"waiting_login","waiting_for":"claude","launched_session":"acme","finished_at":1,"pid":999999,"process_identity":"x"`
	for record, carries := range map[string]bool{
		parked + `,"tree_stopped":[999999,"x"]}`: true,
		parked + `}`:                             false,
	} {
		ak, _ := idleHome(t, answers)
		path := filepath.Join(ak, "runs", "fix-api", "run.json")
		tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
		if tick.through([]pass{
			{"before", false, nil, func() error { put(t, path, record); return nil }},
			{"endings", false, tick.endingsIdle, tick.endings},
		}) != carries || read(t, path) != record {
			t.Errorf("%s: carried %v, the record %s", record, !carries, read(t, path))
		}
	}
}
