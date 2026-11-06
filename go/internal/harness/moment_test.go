package harness

import "testing"

// A time is Python's very float for it, as harness.moment gives it: a done check's fingerprint
// holds it.  Each of these a division of its nanoseconds misses.
func TestMomentIsPythonsFloat(t *testing.T) {
	for at, want := range map[string]float64{
		"2026-11-05T10:00:00.031676Z":      1793872800.031676,
		"2026-11-05T10:00:00.039595Z":      1793872800.039595,
		"2026-11-05T12:00:00.047514+02:00": 1793872800.047514,
		"2026-11-05T10:00:00.3Z":           1793872800.3,
		"not a time":                       0,
	} {
		if got := Moment(at); got != want {
			t.Errorf("%s: got %v, want %v", at, got, want)
		}
	}
}
