package terminal

import (
	"strings"
	"testing"
)

// What moves between draws goes out alone at its cells while the lines under it hold still, and
// the whole frame again once they change.
func TestOnlyTheSpansThatMovedGoOut(t *testing.T) {
	var out strings.Builder
	painter, screen := NewPainter(&out), Screen{width: 20, height: 5}
	painter.Write([]string{"agentkit", "  Claude I"}, screen, Span{2, 3, "Claude I"})
	out.Reset()
	painter.Write([]string{"agentkit", "  Claude I"}, screen, Span{2, 3, "Claude I"})
	if out.Len() != 0 {
		t.Fatalf("a still frame wrote %q", out.String())
	}
	painter.Write([]string{"agentkit", "  Claude I"}, screen, Span{2, 3, "\x1b[1mClaude I\x1b[0m"})
	if got := out.String(); got != "\x1b[?2026h\x1b[2;3H\x1b[1mClaude I\x1b[0m\x1b[?2026l" {
		t.Fatalf("a moved span wrote %q", got)
	}
	out.Reset()
	painter.Write([]string{"agentkit", "› Claude I"}, screen, Span{2, 3, "\x1b[1mClaude I\x1b[0m"})
	if got := out.String(); !strings.Contains(got, "› Claude I") || !strings.HasSuffix(got, "\x1b[2;3H\x1b[1mClaude I\x1b[0m\x1b[?2026l") {
		t.Fatalf("changed lines wrote %q", got)
	}
}
