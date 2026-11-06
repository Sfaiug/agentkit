package tick

import "agentkit/internal/plan"

// stopUnowed is whether watch.stop_nudge leaves alone a seat whose stops its harness's own hook
// judges: its plan owes no line, nor holds finished work a done check could owe, so nothing sends
// it back and a reply of the owner's waits for the typed answers row.
func stopUnowed(name string) bool {
	owes, err := plan.Owes(name)
	finished, unread := plan.Finished(name)
	return err == nil && unread == nil && !owes && !finished
}
