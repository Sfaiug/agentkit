package harness

import "testing"

// Python's Harness.failure tells a spent window from one only limited for now: limited where each
// word of its manifest's and every harness's it says is one Limited reads.
func TestARefusalSpendsTheWindowUnlessAllItSaysIsALimit(t *testing.T) {
	for _, each := range []struct {
		said             string
		refused, limited bool
	}{
		{"Error: provider.free-limit 429 Free usage limit reached. try again at 2026-10-31T01:22:00.000+00:00", true, false},
		{"Error: 429 Too Many Requests", true, true},
		{"402 payment required", true, false},
		{"Error: provider.unknown", false, true},
	} {
		if refused, limited := Refusal("opencode", each.said); refused != each.refused || refused && limited != each.limited {
			t.Errorf("%q: refused %v, limited %v", each.said, refused, limited)
		}
	}
}
