//go:build unix

package tick

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A week whose board is Python ak's to read is left to Python before any of it is written.
func TestAnAuditLeavesAWeekWhoseBoardIsPythonsUnwritten(t *testing.T) {
	ak, _ := idleHome(t, answers)
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=true\n")
	tick := &ticking{clock: func() time.Time { return time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC) }, log: newLog(io.Discard, io.Discard)}
	tick.report = func(time.Time) ([]string, string, bool) { return nil, "", false }
	if err := tick.audit(); !errors.Is(err, errLeft) {
		t.Fatal(err)
	}
	for _, name := range []string{"audit.json", "audit"} {
		if _, err := os.Stat(filepath.Join(ak, "state", name)); !os.IsNotExist(err) {
			t.Fatal(name, err)
		}
	}
}

func TestAnAuditKeepsItsWeeksReportWhenItsLaunchIsNotCarried(t *testing.T) {
	ak, _ := idleHome(t, answers)
	// a harness Go opens no seat of yet
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=true\norchestrator='mimo'\n")
	tick := &ticking{clock: func() time.Time { return time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC) }, log: newLog(io.Discard, io.Discard)}
	tick.report = func(time.Time) ([]string, string, bool) { return []string{"fixture report"}, "fixture loss", true }
	for i := range 2 {
		if err := tick.audit(); !errors.Is(err, errLeft) {
			t.Fatal(err)
		}
		state, err := run.ReadJSON(filepath.Join(ak, "state", "audit.json"))
		if err != nil || state.Str("week") != "2026-W45" || state.Truthy("delivered") {
			t.Fatal(state, err)
		}
		text := read(t, state.Str("report"))
		if !strings.HasPrefix(text, "# ak's week 2026-W45\n") || i == 1 && !strings.HasSuffix(text, "kept\n") {
			t.Fatal(text)
		}
		if i == 0 {
			put(t, state.Str("report"), text+"kept\n")
		}
	}
}
