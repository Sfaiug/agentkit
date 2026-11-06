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
		{[]string{"agentkit", "› acme", "  fix-api"}, "\x1b[Hagentkit\x1b[K\n› acme\x1b[K\n  fix-api\x1b[K\n\x1b[J"},
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
	if painter.Write([]string{"agentkit"}, screen); out.String() != hold("\x1b[Hagentkit\x1b[K\n\x1b[J") {
		t.Fatalf("a Tick on wrote %q", out.String())
	}
}

// hold is a frame as one synchronized update, nothing where it is empty.
func hold(frame string) string {
	if frame == "" {
		return ""
	}
	return "\x1b[?2026h" + frame + "\x1b[?2026l"
}
