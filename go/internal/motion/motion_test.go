package motion

import (
	"testing"
	"time"
)

func TestEachLineEasesOutToItsLengthAfterTheOneAboveIt(t *testing.T) {
	for _, each := range []struct {
		up   time.Duration
		nth  int
		want float64
	}{{0, 0, 0}, {Grow / 2, 0, 0.5}, {Grow, 0, 1}, {time.Hour, 3, 1}, {Grow, 1, Eased(float64(Grow-Stagger) / float64(Grow))}, {Stagger, 1, 0}} {
		if got := Grown(each.up, each.nth); got-each.want > 1e-9 || each.want-got > 1e-9 {
			t.Errorf("Grown(%v, %d) = %v, want %v", each.up, each.nth, got, each.want)
		}
	}
	if !Growing(Grow+Stagger-1, 2) || Growing(Grow+Stagger, 2) || Growing(0, 0) {
		t.Error("a screen grows until its last line has")
	}
}
