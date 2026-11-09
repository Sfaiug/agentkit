package cli

import "agentkit/internal/history"

// boardHistory is history.db opened for the scoreboard (history.Open), nil where none stands, read
// once the seats' tokens are, as Python's board reads them (history.SeatTokens), with the seats it
// counts none of; errLeft, having written nothing, where what they spent is Python's to read, and
// Open's error where it leaves history.db to Python.
func boardHistory() (*history.DB, []string, error) {
	uncounted, read := history.SeatTokens()
	if !read {
		return nil, nil, errLeft
	}
	db, err := history.Open()
	return db, uncounted, err
}
