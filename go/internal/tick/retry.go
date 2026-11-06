package tick

import (
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

func (t *ticking) retryNotifications() error {
	carried, err := notify.RetryPending(seat.Published, t.dry, t.log.line, t.log.errOut)
	if !carried && err == nil {
		return errLeft
	}
	return err
}
