package launch

// A First is the run first in line for a slot, as Python's gate.first_in_line answers.
type First struct {
	Run    string    // its id
	Since  float64   // since when it has waited there
	Behind int       // how many wait behind it
	Took   []float64 // the waits there of the last firsts let in
}

// FirstInLine is Python's gate.first_in_line at now, for the tick's stall scan: the run first in
// line while a poll rewrote the queue within three polls of the last in line counting it again
// (waiter.stale_after), nil for none; after a gap, a new wait.  False where Go reads the queue or
// the poll otherwise than Python.
func FirstInLine(now float64) (*First, bool) {
	saved, read := queued()
	poll, polled := slotPoll()
	if !read || !polled {
		return nil, false
	}
	id, since, waits := saved.firstInLine(now, poll)
	if !waits {
		return nil, true
	}
	return &First{Run: id, Since: since, Behind: len(saved.queue) - 1, Took: saved.took}, true
}
