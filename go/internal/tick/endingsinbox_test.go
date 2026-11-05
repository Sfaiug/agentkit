//go:build unix

package tick

import (
	"errors"
	"io"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestEndingsTellARunFromNoSeatNothingAndLeaveAQuestionGoCannotReadToPython(t *testing.T) {
	ak, _ := idleHome(t, answers)
	path := filepath.Join(ak, "runs", "review", "run.json")
	ended := run.Fields("state", "pass", "review_pr", "https://github.com/acme/widgets/pull/1", "finished_at", epoch(time.Now()))
	put(t, path, run.Line(ended))
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	if err := tick.endings(); err != nil || read(t, path) != run.Line(ended) {
		t.Fatalf("a run from no seat was not carried as it stands: %v", err)
	}
	ended.Set("pending_inbox", []any{"Merge?"})
	put(t, path, run.Line(ended))
	if err := tick.endings(); !errors.Is(err, errLeft) || read(t, path) != run.Line(ended) {
		t.Fatalf("a merge question Go cannot read was not left to Python as it stands: %v", err)
	}
}
