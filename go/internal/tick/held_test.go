package tick

import (
	"testing"

	"agentkit/internal/seat"
)

func TestHeldLinesReadOnlyAkOwnLineInTheComposer(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	for _, c := range []struct {
		live seat.Live
		idle bool
	}{
		{seat.Live{Own: "claude"}, true},
		{seat.Live{Own: "claude", Draft: "continue"}, false},
		{seat.Live{Own: "claude", Draft: "pleasecontinuewiththetests"}, true},
		{seat.Live{Own: "claude", Draft: "fixittoocontinue", Typed: []string{"fixittoo", "continue"}}, false},
	} {
		if got := holdsNoLine(c.live); got != c.idle {
			t.Fatalf("holdsNoLine(%q, %q) = %v", c.live.Draft, c.live.Typed, got)
		}
	}
}
