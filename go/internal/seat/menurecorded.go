package seat

import (
	"path/filepath"

	"agentkit/internal/config"
)

// Recorded gives each seat whose panes run on its word as its seat file records it, what the last
// look at it wrote down (menu.seat_row_state without a look): nothing is captured and nothing
// written.  ErrUnread where one has no word recorded, which only a look decides, or where the ak
// screen would draw one out of usage, which is Python's to draw.
func (home Home) Recorded() error {
	state := filepath.Join(config.Home(), "state")
	for at := range home.Seats {
		seat := &home.Seats[at]
		if !seat.live {
			continue
		}
		file := seat.file(state)
		if file == nil || file.Str("word") == "" || file.Str("word") == "out of usage" {
			return ErrUnread
		}
		seat.Word, seat.reason, seat.unsent, seat.since = file.Str("word"), file.Str("reason"), file.Str("unsent"), file.Get("word_since")
	}
	return nil
}
