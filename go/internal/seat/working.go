package seat

import (
	"slices"
	"time"
)

// Working is the seats whose word is `working` now, in the order orch.listing numbers them, as
// Python's update.working_sessions finds them: every seat the listing holds, a legacy one's
// included, worded as its card takes it, from what its last look kept, nothing captured or
// written.  False where Go does not word one of them.
func Working(now time.Time) ([]string, bool) {
	home, known := seated(now)
	if !known {
		return nil, false
	}
	// that listing is the reading one, which infers no project for a record naming none
	seats := slices.Clone(home.Seats)
	for i := range seats {
		if seats[i].infer {
			seats[i].home = homeKey("", nil)
		}
	}
	order(seats)
	var working []string
	for _, each := range seats {
		switch word, _, _, _ := home.cardAnswer(each.Name, now); word {
		case "":
			return nil, false
		case "working":
			working = append(working, each.Name)
		}
	}
	return working, true
}
