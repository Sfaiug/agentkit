package seat

// A look can find the harness dead after listing it live. Its empty capture must
// not replace its last screen with rule=none: revival would invent a cut-off turn.
// Only the error it can no longer be retrying is cleared (watch.live_state).
func (seat Seat) keepExited(state string, found sight) (sight, error) {
	found.stall, found.login = nil, nil
	return found, writeSeat(state, seat.Name, []field{{"stall", nil}, {"login", nil}})
}
