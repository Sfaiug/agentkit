package harness

// Counts are what one model of a turn spent, by kind.
type Counts struct {
	Model any      // nil where the turn named none
	Spent [4]int64 // input, cache write, cache read and output
}

// TurnCounts is what the turn in out reported it spent, by model, Python's plugin `turn_usage`: the
// session its counts total, nil where they count this turn alone; false where it reported none, as
// a harness does by default.
func TurnCounts(name, out string) (session any, counts []Counts, reported bool) {
	if hook := plugins[name].turnCounts; hook != nil {
		return hook(out)
	}
	return nil, nil, false
}
