package cli

import (
	"slices"

	"agentkit/internal/history"
)

// boardHistory is history.db opened for the scoreboard (history.Open), nil where none stands, and
// the seats whose tokens its board counts none of, as Python's seat_tokens.read names them: their
// sources kept there first, to be read from their start (history.Sources).  errLeft where what
// they spent is Python's to count, the seats read before anything is written (history.SeatSources),
// or the sources' write is Python's to say; Open's error where it leaves history.db to Python, one
// keeping seats' sources among them.
func boardHistory() (*history.DB, []string, error) {
	sources, seats, uncounted, read := history.SeatSources()
	if !read {
		return nil, nil, errLeft
	}
	db, err := history.Open()
	if err != nil || seats == 0 {
		return db, nil, err
	}
	named, kept := history.Sources(sources)
	if !kept {
		db.Close()
		return nil, nil, errLeft
	}
	uncounted = append(uncounted, named...)
	slices.Sort(uncounted)
	return db, slices.Compact(uncounted), nil
}
