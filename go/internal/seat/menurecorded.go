package seat

import (
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Recorded gives each seat whose panes run on its word as its seat file records it, what the last
// look at it wrote down, and one with none recorded yet its word decided on what that file kept
// of its screen (menu.seat_row_state without a look): nothing is captured and nothing written.
// ErrUnread where the ak screen would draw one out of usage, which is Python's to draw.
func (home Home) Recorded(now time.Time) error {
	state := filepath.Join(config.Home(), "state")
	for at := range home.Seats {
		seat := &home.Seats[at]
		if !seat.live {
			continue
		}
		file := seat.file(state)
		if file == nil {
			file = run.NewObject()
		}
		if word := file.Str("word"); word != "" {
			seat.Word, seat.reason, seat.unsent, seat.since = word, file.Str("reason"), file.Str("unsent"), file.Get("word_since")
		} else if err := seat.decided(state, keptSight(file), seconds(now), false); err != nil {
			return err
		}
		if seat.Word == "out of usage" {
			return ErrUnread
		}
	}
	return nil
}
