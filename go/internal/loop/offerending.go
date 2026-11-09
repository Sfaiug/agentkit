package loop

import (
	"time"

	"agentkit/internal/handback"
	"agentkit/internal/run"
)

// OfferEnding is the tick's offer through the driver's hand-back and checkout cleanup, from census
// as handback.Give reads it.  An interruption gets its own result before the line points its seat
// there.
func OfferEnding(dir string, census []*run.Object, say func(string)) error {
	release, err := run.Hold(dir)
	if err != nil {
		return err
	}
	defer release()
	record, _ := run.Read(dir)
	if record == nil || !handback.Awaiting(record, time.Now()) {
		return nil
	}
	if record.Str("state") == "interrupted" {
		if err := WriteResult(dir, record); err != nil {
			return err
		}
	}
	if handback.Announce(dir, census, say) {
		dropTold(dir, stampedLog{dir})
	}
	return nil
}
