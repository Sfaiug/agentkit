package helper

// Lost is whether a piece's exit says the machine lost it, Python's GONE, which goes back to the
// head of the suite's line: ssh's own failure, the machine off its charger, or a container that
// could not run.  One out of memory there (short) stays Python's, which gives the machine's next
// VMs more memory.
func Lost(code int) bool {
	return code == lost || code == battery || code == broken
}

// Dropped is whether the machine dropped the piece, ssh's own failure, Python's LOST.
func Dropped(code int) bool {
	return code == lost
}
