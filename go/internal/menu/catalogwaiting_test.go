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
		first := CatalogWaiting(s, "config", "12:34", nil, clock)
		clock.Draw(now.Add(time.Second))
		second := CatalogWaiting(s, "config", "12:34", nil, clock)
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
