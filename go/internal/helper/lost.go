package helper

// Lost is whether a piece's exit says the machine lost it, Python's GONE, which goes back to the
// head of the suite's line but never again to the suite there that lost it: ssh's own failure, the
// kernel killing it for memory, the machine off its charger, or a container that could not run.
// One the machine had no room to start (full) goes back for any place.
func Lost(code int) bool {
	return code == lost || code == short || code == battery || code == broken
}
