package loop

// redRank orders a suite's red pieces for the one it hands on, Python's land.red_part: one whose
// tests failed again alone before one that confirmed none, as a repeat failure is the red its
// siblings' unconfirmed ones may only follow from, and one out of memory, the host's red, last.
func redRank(r ran) int {
	rank := 0
	if r.starved {
		rank = 2
	}
	if len(r.confirmed) == 0 {
		rank++
	}
	return rank
}
