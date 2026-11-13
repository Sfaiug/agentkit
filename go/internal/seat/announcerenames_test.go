//go:build unix

package seat

import (
	"context"
	"os"
	"testing"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// A frame's live seats decide their words under their announce locks from the rename pointers as
// they stand then: a rename away and back while the frame waits adds an alias whose newer plan
// is the seat's.
func TestALiveSeatsWordFollowsTheRenamesMadeWhileItsFrameWaited(t *testing.T) {
	home := sandbox(t)
	filed(t, home, "acme")
	drawn(t, home, "acme", prompting)
	write(t, stateFile(home, "plan-acme.md"), "# Plan\n")
	held, err := lock.Wait(context.Background(), stateFile(home, "seat-acme.announce"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { held.Close() })
	found, known := MenuRead(time.Now())
	if !known || len(found.Seats) != 1 {
		t.Fatalf("the frame: %v %+v", known, found.Seats)
	}
	if _, known, err := Rename("acme", "beta", false, time.Now()); !known || err != nil {
		t.Fatalf("away: %v %v", known, err)
	}
	// the harness still writes under the name it was launched with, and its newer plan is under beta
	write(t, stateFile(home, "plan-acme.md"), "# Plan\n")
	write(t, stateFile(home, "plan-beta.md"), "- [ ] New work\n")
	for name, stamp := range map[string]int64{"acme": 1000, "beta": 2000} {
		if err := os.Chtimes(stateFile(home, "plan-"+name+".md"), time.Unix(stamp, 0), time.Unix(stamp, 0)); err != nil {
			t.Fatal(err)
		}
	}
	if _, known, err := Rename("beta", "acme", false, time.Now()); !known || err != nil {
		t.Fatalf("back: %v %v", known, err)
	}
	held.Close()
	if err := found.Announce(time.Now()); err != nil {
		t.Fatal(err)
	}
	saved, err := run.ReadJSON(stateFile(home, "seat-acme.json"))
	if err != nil || saved.Str("word") != "needs you" || saved.Str("reason") != "stopped with work open: New work" {
		t.Fatalf("%s (%v)", run.Line(saved), err)
	}
}
