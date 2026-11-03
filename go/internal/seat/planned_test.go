package seat

import (
	"fmt"
	"slices"
	"testing"
	"time"
)

// A seat at rest is the owner's while its plan owes a line, unless they stopped its turn, and done
// once every line is proven; a turn running keeps it working whatever its plan says.
func TestItsPlanDecidesASeatAtRest(t *testing.T) {
	stopped := fmt.Sprintf(`{"type": "user", "timestamp": %q, "message": {"role": "user", "content": "[Request interrupted by user]"}}`+"\n",
		time.Now().Add(time.Minute).UTC().Format(time.RFC3339))
	for name, each := range map[string]struct{ plan, entries, screen, word, reason string }{
		"owing a line":               {doneLine + openLine, "", prompting, "needs you", "stopped with work open: Ship it"},
		"every line proven":          {doneLine, "", prompting, "done", "Ship it"},
		"a turn the owner stopped":   {openLine, stopped, prompting, "idle", "-"},
		"a turn running":             {openLine, "", spinning, "working", "-"},
		"a line ticked past a proof": {"- [x] Ship it · check: `true` · acme · written 2026-10-23 09:00\n", "", prompting, "needs you", "stopped with work open: Ship it"},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			transcript(t, home, "acme", each.entries)
			drawn(t, home, "acme", each.screen)
			if each.entries != "" {
				hookWrote(t, home, "UserPromptSubmit", "")
			}
			write(t, stateFile(home, "plan-acme.md"), each.plan)
			lines := explained(t, "acme")
			if want := []string{"acme  " + each.word, "  reason:    " + each.reason}; !slices.Equal(lines[:2], want) {
				t.Fatal(lines)
			}
		})
	}
}
