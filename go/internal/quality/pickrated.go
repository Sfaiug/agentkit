package quality

import (
	"cmp"
	"slices"
)

// Pick is the role's pick among any rated rows, as Python's quality.pick takes them: those with a
// cost, cheapest first and the better on an equal cost; nil where none has one.
func Pick(rated []*Rating, role string) *Rating {
	var priced []*Rating
	for _, row := range rated {
		if row.Cost != nil {
			priced = append(priced, row)
		}
	}
	slices.SortStableFunc(priced, cheaper)
	return pick(priced, role)
}

// cheaper orders priced rows cheapest first, the better on an equal cost.
func cheaper(a, b *Rating) int {
	return cmp.Or(cmp.Compare(*a.Cost, *b.Cost), cmp.Compare(b.Quality, a.Quality))
}
