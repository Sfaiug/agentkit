package tick

import "agentkit/internal/history"

// seatTokens is Python's seat_tokens.read, the history.db it writes made where none stands, as
// Python's is; errLeft, having written nothing, where Python's is to read them (history.SeatTokens).
func seatTokens() error {
	if _, read := history.SeatTokens(); !read {
		return errLeft
	}
	return nil
}
