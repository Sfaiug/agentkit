//go:build unix

package tick

import (
	"errors"
	"io"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestAnAuditKeepsItsWeeksReportWhenItsLaunchIsNotCarried(t *testing.T) {
	ak, _ := idleHome(t, answers)
	// a harness Go opens no seat of yet
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=true\norchestrator='gemini'\n")
	tick := &ticking{clock: func() time.Time { return time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC) }, log: newLog(io.Discard, io.Discard)}
	tick.report = func(time.Time) ([]string, string) { return []string{"fixture report"}, "fixture loss" }
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

func TestAnAuditLeavesAnEarlierPartialDeliveryAlone(t *testing.T) {
	ak, _ := idleHome(t, answers)
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=true\n")
	path := filepath.Join(ak, "state", "audit.json")
	before := `{"week":"2026-W44","typed":{"line":"earlier work"},"delivered":null}`
	put(t, path, before)
	tick := &ticking{clock: time.Now, log: newLog(io.Discard, io.Discard)}
	if err := tick.audit(); !errors.Is(err, errLeft) || read(t, path) != before {
		t.Fatal(err)
	}
}
