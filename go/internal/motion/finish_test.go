package motion

import (
	"testing"
	"time"
)

func TestAKeyFinishesWhatIsMovingAndLaterChangesMoveAfresh(t *testing.T) {
	clock, now := &Clock{}, time.Unix(100, 0)
	clock.Draw(now)
	clock.Moved("plan", 0, Glide)
	clock.Draw(now.Add(time.Millisecond))
	clock.Moved("plan", 1, Glide)
	clock.Finish()
	clock.Draw(now.Add(2 * time.Millisecond))
	if grown := clock.Grown(10); grown != 1 {
		t.Fatalf("opening line still growing: %v", grown)
	}
	if _, moved := clock.Moved("plan", 1, Glide); moved != 1 {
		t.Fatalf("interrupted change still moving: %v", moved)
	}
	if _, due := clock.Next(); due {
		t.Fatal("a settled frame is still scheduled")
	}
	if _, moved := clock.Moved("plan", 2, Glide); moved != 0 {
		t.Fatalf("a later change did not start moving: %v", moved)
	}
}
