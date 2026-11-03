package harness

import "testing"

// Python's Harness.failure: a fault only in a turn that never ran, and never beside an outage; a
// spent window before a refusal, and a refusal before an outage.
func TestAnEndingIsTheStrongestThingItSays(t *testing.T) {
	for _, each := range []struct {
		said string
		ran  bool
		want TurnEnding
		word string
	}{
		{"acme: unknown model big", false, Fault, "unknown model"},
		{"acme: unknown model big", true, Unsaid, ""},
		{"unknown model big; Service unavailable", false, Outage, "Service unavailable"},
		{"402 payment required; API Error: 529", true, Quota, "402"},
		{"API Error: 529 overloaded", true, Refused, "API Error"},
		{"overloaded", true, Outage, "overloaded"},
		{"wrote retry.txt", true, Unsaid, ""},
	} {
		if ending, word := Ending("acme", each.said, each.ran); ending != each.want || word != each.word {
			t.Errorf("%q ran=%v: %v %q", each.said, each.ran, ending, word)
		}
	}
}
