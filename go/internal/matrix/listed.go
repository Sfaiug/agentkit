package matrix

import (
	"time"

	"agentkit/internal/boards"
)

// Listed is what the login of provider, account "" its usual one, spent over the last seven days
// at the cached boards' listed prices, as `ak usage --json` gives it (Python's usage.main over
// spend.listed): nil where none of its rows from then can be priced.  history.db is only looked
// at, never made or migrated.
func Listed(provider, account string) any {
	s := spending(boards.Cached())
	defer s.db.Close()
	now := float64(time.Now().UnixNano()) / 1e9
	if dollars, priced := s.listed(provider, account, now-spentOver, now); priced {
		return dollars
	}
	return nil
}
