package cli

import "testing"

// The loss is the first measure in the vision's order that reads worse than the week before, else
// the first read this week at all, as Python's scoreboard.loss names it.
func TestTheLossIsTheFirstMeasureInTheVisionsOrderThatGotWorse(t *testing.T) {
	for name, each := range map[string]struct {
		now, before readings
		want        string
	}{
		"none": {readings{}, readings{}, "no loss to name, since no run ended in two weeks"},
		"new history": {readings{"size.code lines": 12000}, readings{},
			"the largest loss is ak's code lines, 12,000 against not recorded the week before"},
		"first known": {readings{"size.code lines": 12}, readings{"size.code lines": 13},
			"the largest loss is ak's code lines, 12 against 13 the week before"},
		"faster but less often in round 1": {
			readings{"products.first_round": 0.6, "products.hours": 1, "size.code lines": 20},
			readings{"products.first_round": 0.8, "products.hours": 4, "size.code lines": 10},
			"the largest loss is product runs merged in round 1, 60% against 80% the week before"},
		"slower, as often in round 1": {readings{"products.first_round": 0.8, "products.hours": 4.25},
			readings{"products.first_round": 0.8, "products.hours": 1},
			"the largest loss is hours to merge a product run, 4.2 hours against 1.0 hours the week before"},
	} {
		t.Run(name, func(t *testing.T) {
			b := board{read: [2]readings{each.now, each.before}}
			if got := b.loss(); got != each.want {
				t.Fatal(got)
			}
		})
	}
}
