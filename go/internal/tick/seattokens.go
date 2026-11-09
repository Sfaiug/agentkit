package tick

import "agentkit/internal/history"

// seatTokens is Python's seat_tokens.read where no seat has spent anything it could count yet:
// history.db keeps each seat's sources, to be read from their start, where a seat or a source
// kept stands.  errLeft, having written nothing, where a seat's harness keeps its tokens where Go
// does not look, or a source holds lines, which Python counts.  None where the tick keeps no
// history.
func seatTokens() error {
	if keeps, err := keepsHistory(false); !keeps { // a row a dry tick does not run
		return err
	}
	sources, seats, _, read := history.SeatSources()
	if !read {
		return errLeft
	}
	if seats == 0 && !history.KeepsSeats() {
		return nil // renames' pointers alone: Python reads no seat, and makes no table for none
	}
	if _, kept := history.Sources(sources); !kept {
		return errLeft
	}
	return nil
}
