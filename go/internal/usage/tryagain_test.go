package usage

import (
	"testing"
	"time"
)

func TestARefusalNamesWhenToComeBackOnlyWithADate(t *testing.T) {
	named := time.Date(2026, time.October, 12, 23, 39, 0, 0, time.Local)
	for said, want := range map[string]float64{
		"Try again at Oct 12th, 2026 11:39 PM":   float64(named.Unix()),
		"try again at October 12 2026 at 23:39":  float64(named.Unix()),
		"try again at 2026-10-12T21:39:00Z":      float64(time.Date(2026, time.October, 12, 21, 39, 0, 0, time.UTC).Unix()),
		"try again on 2026-10-12 21:39:00+02:00": float64(time.Date(2026, time.October, 12, 19, 39, 0, 0, time.UTC).Unix()),
		"try again at 11:39 PM":                  0,
		"try again at Foo 12, 2026 11:39":        0,
		"try again at Feb 31, 2026 11:39":        0,
	} {
		if at := TryAgainAt(said); at != want {
			t.Errorf("%q: %v, want %v", said, at, want)
		}
	}
}
