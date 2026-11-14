package quality

import (
	"cmp"
	"math"
	"slices"
	"strconv"
)

// The models screen's choices, the owner, 5 Nov 2026: none further below the best than window
// points, each apart above the one before, Places of them at most.
const window, apart, Places = 10, 1, 5

// An Other is the best row of a release with no choice and Why: "not set up", By nil, where it
// would be one were it run; else "beaten" By a row as good and no dearer, "far below" the best,
// "close" By the nearest choice, or "no room"; By nil for the two.
type Other struct {
	*Rating
	Why string
	By  *Rating
}

// above is the quality points row is above other, to a millionth as Python's round(x, 6), for the
// window and apart lines only: a rating's roundoff never moves a row across one, as 90 is 10
// under 100, never 10.00000000000001, while a row a millionth better still ranks above.
func above(row, other *Rating) float64 {
	rounded, _ := strconv.ParseFloat(strconv.FormatFloat(row.Quality-other.Quality, 'f', 6, 64), 64)
	return rounded
}

// choices is Python's matrix._choices over priced, cheapest first and an equal cost better first,
// runs saying whether a configured model runs a row: the choices are those rows' (chosen), so a
// better row nobody runs moves none.  The others: of each release with no choice its best row, a
// cheaper one on a tie, best first and then cheapest, each with its why (why); one nobody runs
// has the why it would have were it run, the same rule over the rows run and it.
func choices(priced []*Rating, runs func(*Rating) bool) ([]*Rating, []Other) {
	over := func(row *Rating) ([]*Rating, []*Rating) { // the rule over the rows run and row
		return chosen(slices.DeleteFunc(slices.Clone(priced), func(one *Rating) bool { return !runs(one) && one != row }))
	}
	picked, front := over(nil)
	var others []Other
	at := map[string]int{} // a release's place in others
	for _, row := range priced {
		if slices.ContainsFunc(picked, func(one *Rating) bool { return one.Release == row.Release }) {
			continue
		}
		if n, seen := at[row.Release]; !seen {
			at[row.Release] = len(others)
			others = append(others, Other{Rating: row})
		} else if row.Quality > others[n].Quality {
			others[n].Rating = row
		}
	}
	slices.SortStableFunc(others, func(a, b Other) int {
		return cmp.Or(cmp.Compare(b.Quality, a.Quality), cmp.Compare(*a.Cost, *b.Cost))
	})
	for n := range others {
		row, beside, along := &others[n], picked, front
		if !runs(row.Rating) {
			beside, along = over(row.Rating)
		}
		row.Why, row.By = why(row.Rating, beside, along)
	}
	return picked, others
}

// chosen is Python's matrix._chosen over priced, cheapest first: the choices and the front.  Its
// front holds each row better than every cheaper one, the best last.  Its choices: the front's
// rows within window of the best, cheapest first, each kept when apart above the last kept, the
// best taking the place of one less than that below it; the costliest Places of them.
func chosen(priced []*Rating) ([]*Rating, []*Rating) {
	var front []*Rating
	for _, row := range priced {
		if len(front) == 0 || row.Quality > front[len(front)-1].Quality {
			front = append(front, row)
		}
	}
	var kept []*Rating
	for _, row := range front {
		best := front[len(front)-1]
		switch {
		case above(best, row) > window:
		case len(kept) > 0 && above(row, kept[len(kept)-1]) < apart:
			if row == best {
				kept[len(kept)-1] = row
			}
		default:
			kept = append(kept, row)
		}
	}
	return kept[max(0, len(kept)-Places):], front
}

// why is Python's matrix._why: the why and by of row beside choices and front (chosen).  "not
// set up" among the choices, as a row nobody runs is where it would be one (choices); off the
// front, "beaten" by the cheapest choice, else row of the front, as good and no dearer; on it,
// "far below", more than window under the best; else "close" to the nearest choice, less than
// apart from it; else "no room": apart or more under every choice, as the costliest Places leave
// it.  By is nil but for "beaten" and "close".
func why(row *Rating, choices, front []*Rating) (string, *Rating) {
	switch {
	case slices.Contains(choices, row):
		return "not set up", nil
	case !slices.Contains(front, row):
		for _, one := range slices.Concat(choices, front) {
			if one.Quality >= row.Quality && *one.Cost <= *row.Cost {
				return "beaten", one
			}
		}
	case above(front[len(front)-1], row) > window:
		return "far below", nil
	}
	near := choices[0]
	for _, one := range choices[1:] {
		if math.Abs(above(one, row)) < math.Abs(above(near, row)) {
			near = one
		}
	}
	if math.Abs(above(near, row)) < apart {
		return "close", near
	}
	return "no room", nil
}
