package pick

import (
	"io"
	"slices"
)

// Beside is the reviewers with room in pick order, by the worst place in the owner's order each
// takes beside the writers, Python's reviewer_order: a model tends to miss the mistakes it makes, so
// its own review is the last choice, but only a choice.  told, unless nil, hears what Order says.
func (r *Rules) Beside(room Room, writers []string, told io.Writer) []string {
	worst := func(name string) int {
		place := 0
		for _, writer := range writers {
			place = max(place, r.tier(writer, name))
		}
		return place
	}
	order := r.Order(room, true, told)
	slices.SortStableFunc(order, func(a, b string) int { return worst(a) - worst(b) })
	return order
}

// Wrote is whether the model is one of the writers.
func (r *Rules) Wrote(name string, writers []string) bool {
	return slices.ContainsFunc(writers, func(writer string) bool { return r.Same(writer, name) })
}
