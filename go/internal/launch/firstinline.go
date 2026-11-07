package launch

import "agentkit/internal/run"

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
	saved, took, _, read := queued()
	poll, polled := slotPoll()
	if !read || !polled {
		return nil, false
	}
	if saved == nil {
		return nil, true
	}
	queue := saved.List("queue")
	at, _ := run.Num(saved.Get("at"))
	since, _ := optional(saved.Get("since"))
	if len(queue) == 0 || since == 0 || !(now-at < float64(len(queue))*poll+3*poll) {
		return nil, true
	}
	first := &First{Run: queue[0].(string), Since: since, Behind: len(queue) - 1}
	for _, wait := range took {
		seconds, _ := run.Num(wait)
		first.Took = append(first.Took, seconds)
	}
	return first, true
}
