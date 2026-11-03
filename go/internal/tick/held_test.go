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

func TestTmuxWordQuotesAsTmuxReads(t *testing.T) {
	for text, want := range map[string]string{
		"ak orch front":        "'ak orch front'",
		`it's "#1" for $HOME\`: `"it's \"\#1\" for \$HOME\\"`,
	} {
		if got := tmuxWord(text); got != want {
			t.Fatalf("tmuxWord(%q) = %s, want %s", text, got, want)
		}
	}
}
