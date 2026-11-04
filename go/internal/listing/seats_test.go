package listing

import (
	"bytes"
	"strings"
	"testing"
	"time"

	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func TestNarrowSeatsKeepAProjectWithNoVisibleName(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("COLUMNS", "40")
	t.Setenv("NO_COLOR", "1")
	rows := []seat.Seat{{Name: "acme", Project: " \t", Word: "idle", Tally: "no runs yet", Orchestrator: "opus", Workers: "opus"}}
	for _, why := range []bool{false, true} {
		lines := Seats(terminal.For(&bytes.Buffer{}), rows, time.Unix(0, 0), why)
		if lines[1] != "acme" || !strings.Contains(lines[2], "idle") {
			t.Fatalf("seat lost its row: %v", lines)
		}
		if why && !strings.Contains(strings.Join(lines, "\n"), "the process is gone") {
			t.Fatalf("seat lost its explanation: %v", lines)
		}
	}
}
