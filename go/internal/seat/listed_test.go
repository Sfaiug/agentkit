package seat

import (
	"reflect"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestListingExplanationKeepsThePublishedObservation(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	show := drawn(t, home, "acme", asked)
	write(t, stateFile(home, "seat-acme.json"), `{"word":"needs you","word_since":123}`)
	now := time.Now()
	found, known := Looking(now)
	if !known {
		t.Fatal("listing did not read the seat")
	}
	if err := found.Announce(now); err != nil {
		t.Fatal(err)
	}
	show(prompting)
	lines := found.Seats[0].Explanation(now)
	want := []string{"acme  needs you", "  reason:    Enter to select · ↑/↓ to navigate · Esc to cancel",
		"  authority: screen  rule: asking.question",
		"  evidence:  Enter to select · ↑/↓ to navigate · Esc to cancel",
		"  since:     " + sinceLine(run.Number("123"), now)}
	if !reflect.DeepEqual(lines, want) {
		t.Fatalf("explanation changed after the row was published: %v", lines)
	}
	if next := explained(t, "acme"); next[0] != "acme  idle" {
		t.Fatalf("next listing did not read the new screen: %v", next)
	}
}
