package motion

import (
	"testing"
	"time"
)

func near(got, want float64) bool { return got-want < 1e-9 && want-got < 1e-9 }

func TestEachLineEasesOutToItsLengthAfterTheOneAboveIt(t *testing.T) {
	opened := time.Now()
	for _, each := range []struct {
		up   time.Duration
		nth  int
		want float64
	}{{0, 0, 0}, {Grow / 2, 0, 0.5}, {Grow, 0, 1}, {time.Hour, 3, 1}, {Grow, 1, Eased(float64(Grow-Stagger) / float64(Grow))}, {Stagger, 1, 0}} {
		clock := &Clock{}
		clock.Draw(opened)
		clock.Draw(opened.Add(each.up))
		if got := clock.Grown(each.nth); !near(got, each.want) {
			t.Errorf("Grown at %v, line %d = %v, want %v", each.up, each.nth, got, each.want)
		}
		if _, due := clock.Next(); due != (each.up < Grow+time.Duration(each.nth)*Stagger) {
			t.Errorf("at %v, line %d: a frame due %v", each.up, each.nth, due)
		}
	}
}

func TestAValueMovesOnlyOnceItChangesWhileTheScreenIsUp(t *testing.T) {
	opened, clock := time.Now(), &Clock{}
	at := func(after time.Duration, value int) (any, float64, bool) {
		clock.Draw(opened.Add(after))
		before, moved := clock.Moved("plan", value, Glide)
		_, due := clock.Next()
		return before, moved, due
	}
	if before, moved, due := at(0, 2); before != nil || moved != 1 || due {
		t.Fatalf("as first drawn: %v %v %v", before, moved, due)
	}
	if before, moved, due := at(time.Second, 5); before != 2 || moved != 0 || !due {
		t.Fatalf("as it changes: %v %v %v", before, moved, due)
	}
	if before, moved, due := at(time.Second+Glide/2, 5); before != 2 || !near(moved, 0.5) || !due {
		t.Fatalf("half way: %v %v %v", before, moved, due)
	}
	if _, moved, due := at(time.Second+Glide, 5); moved != 1 || due {
		t.Fatalf("there: %v %v", moved, due)
	}
}

func TestANilClockHoldsEverythingWhereItEnds(t *testing.T) {
	var clock *Clock
	if before, moved := clock.Moved("plan", 3, Glide); clock.Grown(4) != 1 || before != nil || moved != 1 {
		t.Fatal("a nil clock moves")
	}
}
