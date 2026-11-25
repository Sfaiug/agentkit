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

// A span that leaves a row no line is on leaves it blank, as the rows under the lines are.
func TestARowPastTheLinesASpanLeftIsCleared(t *testing.T) {
	var out strings.Builder
	painter, screen := NewPainter(&out), Screen{width: 8, height: 4}
	painter.Write([]string{"agentkit"}, screen, Span{3, 1, "old"}, Span{4, 1, "old"})
	out.Reset()
	painter.Write([]string{"agentkit"}, screen, Span{4, 1, "old"})
	if want := hold("\x1b[2;1H\x1b[J\x1b[4;1Hold"); out.String() != want {
		t.Fatalf("a span gone past the lines wrote %q, want %q", out.String(), want)
	}
}

// A frame as tall as the screen goes out row by row and nothing after its last: a newline there
// would scroll its header away, and a clear would erase that row.
func TestAFrameFillingTheScreenKeepsItsHeader(t *testing.T) {
	var out strings.Builder
	painter, screen := NewPainter(&out), Screen{width: 8, height: 2}
	painter.Write([]string{"agentkit", "esc"}, screen)
	if want := hold("\x1b[1;1Hagentkit\x1b[2;1Hesc\x1b[K"); out.String() != want {
		t.Fatalf("a full frame wrote %q, want %q", out.String(), want)
	}
	out.Reset()
	painter.Write([]string{"agentkit", "q"}, screen)
	if want := hold("\x1b[2;1Hq\x1b[K"); out.String() != want {
		t.Fatalf("a changed full frame wrote %q, want %q", out.String(), want)
	}
}

// A frame taller than the screen goes out whole on every write, each row ended by a newline, so the
// screen scrolls and keeps its last rows; the frame after it goes out whole, as nothing it left up is
// where it was laid out.
func TestAFrameTallerThanTheScreenScrollsWholeEachTime(t *testing.T) {
	var out strings.Builder
	painter, screen := NewPainter(&out), Screen{width: 8, height: 2}
	tall := hold("\x1b[Hagentkit\nacme\x1b[K\nesc\x1b[K\n\x1b[J")
	for range 2 {
		if painter.Write([]string{"agentkit", "acme", "esc"}, screen); out.String() != tall {
			t.Fatalf("a tall frame wrote %q, want %q", out.String(), tall)
		}
		out.Reset()
	}
	if painter.Up() != nil {
		t.Fatal("a frame scrolled off its rows was handed on")
	}
	if painter.Write([]string{"agentkit"}, screen); out.String() != hold("\x1b[1;1Hagentkit\x1b[2;1H\x1b[J") {
		t.Fatalf("the frame after a tall one wrote %q", out.String())
	}
}

// A padded screen places every row and span inside its margin, paints the top, left, right and
// bottom padding, and still clears the tail of a line filling its inset width.
func TestAPaddedScreenInsetsRowsSpansAndClearsThePadding(t *testing.T) {
	var out strings.Builder
	painter, screen := NewPainter(&out), Screen{width: 8, height: 2, pad: 1}
	painter.Write([]string{"agentkit", "esc"}, screen, Span{2, 3, "c"})
	want := hold("\x1b[2;2H\x1b[1Jagentkit\x1b[K\x1b[3;2H\x1b[1Kesc\x1b[K\x1b[4;2H\x1b[1K\x1b[J\x1b[3;4Hc")
	if out.String() != want {
		t.Fatalf("a padded frame wrote %q, want %q", out.String(), want)
	}
	out.Reset()
	painter.Write([]string{"agentkit", "acme", "esc"}, screen)
	tall := hold("\x1b[2;2H\x1b[1Jagentkit\x1b[K\n\x1b[2G\x1b[1Kacme\x1b[K\n\x1b[2G\x1b[1Kesc\x1b[K\n\x1b[2G\x1b[1K\x1b[J")
	if out.String() != tall {
		t.Fatalf("a tall padded frame wrote %q, want %q", out.String(), tall)
	}
}
