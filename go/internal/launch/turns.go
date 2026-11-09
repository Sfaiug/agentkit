package launch

import (
	"cmp"
	"slices"

	"agentkit/internal/run"
)

// A turn is one seat's batch of waiters as Python's gate.slot_counts keeps it in runs/.slots.queue:
// how many of them went in while more of it waited, and those still waiting.
type turn struct {
	seat    seatKey
	count   int
	pending []string
}

// A seatKey is Python's gate._slot_seat: a waiter's head in line (order) and its seat, a run of no
// seat its own, so it shares no turn with a seat named after that run.
type seatKey struct {
	head      [3]bool
	seat, own string
}

func keyOf(record *run.Object) seatKey {
	seat, own := record.Str("launched_session"), ""
	if seat == "" {
		own = record.Str("run_id")
	}
	return seatKey{order(record), seat, own}
}

// inTurns is the waiters, the one polled first and the rest as runs/ lists them, in line as
// Python's gate.slot_counts puts them: by head, then by each seat's turn, then as they entered;
// and each seat's turns, those the saved line already held first.  A seat's new batch joins level
// with the seat of its head served most, so it goes ahead of no seat still waiting down an older one.
func inTurns(waiting []*run.Object, saved map[seatKey]turn) ([]*run.Object, []turn) {
	var turns []turn
	for _, other := range waiting {
		key := keyOf(other)
		at := slices.IndexFunc(turns, func(each turn) bool { return each.seat == key })
		if at < 0 {
			at, turns = len(turns), append(turns, turn{seat: key})
		}
		turns[at].pending = append(turns[at].pending, other.Str("run_id"))
	}
	kept := func(each turn) bool {
		return slices.ContainsFunc(each.pending, func(id string) bool { return slices.Contains(saved[each.seat].pending, id) })
	}
	floor := map[[3]bool]int{}
	for _, each := range turns {
		if kept(each) {
			floor[each.seat.head] = max(floor[each.seat.head], saved[each.seat].count)
		}
	}
	served := map[seatKey]int{}
	for i, each := range turns {
		turns[i].count = floor[each.seat.head]
		if kept(each) {
			turns[i].count = saved[each.seat].count
		}
		served[each.seat] = turns[i].count
	}
	slices.SortStableFunc(turns, func(a, b turn) int { return cmp.Compare(behind(!kept(a)), behind(!kept(b))) })
	line := slices.SortedStableFunc(slices.Values(waiting), inLine)
	rank := map[*run.Object]int{}
	for _, other := range line {
		rank[other] = served[keyOf(other)]
		served[keyOf(other)]++
	}
	slices.SortStableFunc(line, func(a, b *run.Object) int {
		return cmp.Or(heads(a, b), cmp.Compare(rank[a], rank[b]), inLine(a, b))
	})
	return line, turns
}
