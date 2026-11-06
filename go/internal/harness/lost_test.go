package harness

import "testing"

// Python's Harness.lost, read before the rest: whatever else a harness says that cannot open the
// conversation is not of the turn.
func TestALostConversationOutranksTheRest(t *testing.T) {
	if ending, word := Ending("claude", "No conversation found with session ID: sid-1\nAPI Error: 500", true); ending != Lost || word != "No conversation found with session ID" {
		t.Errorf("%v %q", ending, word)
	}
}
