package update

// liveHeld is whether the check of tests/live.sh a move to origin/main waits for is held, as
// Python's live_tick holds it once no check runs or passed: a login it lends lapses within its
// margin, said once, and nothing moves.  Where they last, the check is Python's to start.
func liveHeld(say func(string)) bool {
	return heldForLogin("live", "tests/live.sh", margin("live", liveCap), now(), say)
}
