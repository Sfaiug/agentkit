package tick

import (
	"errors"

	"agentkit/internal/config"
	"agentkit/internal/update"
)

func liveUpdateIdle() bool { return update.LiveReady(config.Repo()) }

func (t *ticking) liveUpdate() error { return left(update.GoLive(config.Repo(), t.log.line)) }

func (t *ticking) harnessUpgrade() error {
	return left(update.KeepCurrent(config.Repo(), t.log.line, t.tellGate))
}

// left is an update's error as a row's: one Go leaves to Python ends the tick there.
func left(err error) error {
	if errors.Is(err, update.ErrPython) {
		return errLeft
	}
	return err
}
