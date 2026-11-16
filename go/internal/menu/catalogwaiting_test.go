package menu

import (
	"slices"
	"strings"
	"testing"
	"time"

	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

func TestCatalogWaitKeepsItsFrameAndStaysStillWithoutColour(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	for _, width := range []string{"13", "18", "24", "60", "100"} {
		s := screenAt(t, width)
		clock, now := &motion.Clock{}, time.Unix(123, 0)
		clock.Draw(now)
		first := CatalogWaiting(s, "config", "12:34", "reading the models acme offers", nil, clock)
		clock.Draw(now.Add(time.Second))
		second := CatalogWaiting(s, "config", "12:34", "reading the models acme offers", nil, clock)
		if !slices.Equal(first, second) || first[len(first)-1] != "  esc back" || !strings.Contains(first[1], "━") {
			t.Fatalf("bad waiting frame at %s: %q", width, first)
		}
		if _, due := clock.Next(); due {
			t.Fatal("a terminal without colour keeps animating")
		}
		for _, line := range first {
			if terminal.Cells(line) > s.Width() || strings.HasSuffix(line, " ") {
				t.Fatalf("waiting row overflow at %s: %q", width, line)
			}
		}
	}
}

func TestAClickOnEscBackIsWhereItIsDrawn(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	lines := CatalogWaiting(screenAt(t, "60"), "config · machines", "12:34", "asking acme-box", nil, &motion.Clock{})
	row := len(lines)
	for column, want := range map[int]bool{1: false, 3: true, 7: true, 10: true, 11: false} {
		if got := WaitingBack(lines, terminal.Mouse{Column: column, Row: row}); got != want {
			t.Errorf("column %d of %q is on esc back: %v, want %v", column, lines[row-1], got, want)
		}
	}
	if WaitingBack(lines, terminal.Mouse{Column: 3, Row: row - 1}) {
		t.Error("a row above the key line is on esc back")
	}
}
