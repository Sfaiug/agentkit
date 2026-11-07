package turn

// Waited is whether a piece of the hold's suite waited for a turn, Python's _GateHold.waited: Grow
// began with fewer turns than Places, so its pieces did not all run at once.
func (h *Hold) Waited() bool { return h != nil && h.waited }
