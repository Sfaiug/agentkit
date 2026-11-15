//go:build unix

package tick

import (
	"path/filepath"
	"testing"
)

// Python's seat health stalls the seat whose going run a login keeps refusing and pages it, so a
// tick, dry or wet, leaves itself to Python at that row; a run that has ended owes no login.
func TestARefusedRunLeavesSeatHealthToPython(t *testing.T) {
	ak, _ := idleHome(t, answers)
	put(t, filepath.Join(ak, "state", "login-refusals.json"), `{"claude": ["fix-api", "fix-api"]}`)
	for state, idle := range map[string]bool{"stopped": true, "running": false} {
		put(t, filepath.Join(ak, "runs", "fix-api", "run.json"), `{"state":"`+state+`"}`)
		if noRunHealthWork() != idle {
			t.Errorf("a %s run refused twice leaves seat health idle: %v", state, !idle)
		}
	}
}
