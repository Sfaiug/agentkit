package terminal

import (
	"strings"
	"testing"
)

// A move writes only the rows that differ, what is below cleared after them, and a Tick later every
// row goes out again.
func TestOnlyTheRowsThatDifferGoOutAndEveryRowOnceATick(t *testing.T) {
	var out strings.Builder
	painter, screen := NewPainter(&out), Screen{width: 20, height: 5}
	moved := []string{"agentkit", "  acme", "› fix-api"}
	for _, each := range []struct {
		lines []string
		want  string
	}{
		{[]string{"agentkit", "› acme", "  fix-api"}, "\x1b[1;1Hagentkit\x1b[K\x1b[2;1H› acme\x1b[K\x1b[3;1H  fix-api\x1b[K\x1b[4;1H\x1b[J"},
		{moved, "\x1b[2;1H  acme\x1b[K\x1b[3;1H› fix-api\x1b[K\x1b[4;1H\x1b[J"},
		{moved, ""},
		{[]string{"agentkit"}, "\x1b[2;1H\x1b[J"},
	} {
		out.Reset()
		if painter.Write(each.lines, screen); out.String() != hold(each.want) {
			t.Fatalf("%q wrote %q, want %q", each.lines, out.String(), hold(each.want))
		}
	}
	out.Reset()
	painter.whole = painter.whole.Add(-Tick)
	if painter.Write([]string{"agentkit"}, screen); out.String() != hold("\x1b[1;1Hagentkit\x1b[K\x1b[2;1H\x1b[J") {
		t.Fatalf("a Tick on wrote %q", out.String())
	}
}

// A span that moves writes only the rows it left and came to again, then itself over them; a span
// that stays where it was, as it was, is left alone.
func TestSpansThatMoveWriteOnlyTheirRows(t *testing.T) {
	var out strings.Builder
	painter, screen := NewPainter(&out), Screen{width: 20, height: 5}
	lines := []string{"agentkit", "  acme", "  fix-api"}
	painter.Write(lines, screen, Span{1, 1, "agentkit"}, Span{2, 3, "acme"})
	out.Reset()
	painter.Write(lines, screen, Span{1, 1, "agentkit"}, Span{3, 3, "fix-api"})
	if want := hold("\x1b[2;1H  acme\x1b[K\x1b[3;1H  fix-api\x1b[K\x1b[4;1H\x1b[J\x1b[3;3Hfix-api"); out.String() != want {
		t.Fatalf("a moved span wrote %q, want %q", out.String(), want)
	}
}

// hold is a frame as one synchronized update, nothing where it is empty.
func hold(frame string) string {
	if frame == "" {
		return ""
	}
	return "\x1b[?2026h" + frame + "\x1b[?2026l"
}
