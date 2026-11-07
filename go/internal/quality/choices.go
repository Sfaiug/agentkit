package quality

import (
	"cmp"
	"math"
	"slices"
	"strconv"
)

// The models screen's choices, the owner, 5 Nov 2026: none further below the best than window
// points, each apart above the one before, places of them at most.
const window, apart, places = 10, 1, 5

// An Other is the best row of a release with no choice and Why: "beaten" By a row as good and no
// dearer, "far below" the best, "close" By the nearest choice, or "no room"; By nil for the two.
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

// choices is Python's matrix._choices over priced, cheapest first and an equal cost better first.
// Its front holds each row better than every cheaper one, the best last.  The choices: the
// front's rows within window of the best, cheapest first, each kept when apart above the last
// kept, the best taking the place of one less than that below it; the costliest places of them.
// The others: of each release with no choice its best row, a cheaper one on a tie, best first
// and then cheapest.
func choices(priced []*Rating) ([]*Rating, []Other) {
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
	chosen := kept[max(0, len(kept)-places):]
	var others []Other
	at := map[string]int{} // a release's place in others
	for _, row := range priced {
		if slices.ContainsFunc(chosen, func(one *Rating) bool { return one.Release == row.Release }) {
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
		row := &others[n]
		switch {
		case !slices.Contains(front, row.Rating):
			row.Why = "beaten"
			for _, one := range slices.Concat(chosen, front) {
				if one.Quality >= row.Quality && *one.Cost <= *row.Cost {
					row.By = one
					break
				}
			}
		case above(front[len(front)-1], row.Rating) > window:
			row.Why = "far below"
		default:
			near := chosen[0]
			for _, one := range chosen[1:] {
				if math.Abs(above(one, row.Rating)) < math.Abs(above(near, row.Rating)) {
					near = one
				}
			}
			row.Why = "no room"
			if math.Abs(above(near, row.Rating)) < apart {
				row.Why, row.By = "close", near
			}
		}
	}
	return chosen, others
}
