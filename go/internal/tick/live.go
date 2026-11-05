package tick

import (
	"errors"

	"agentkit/internal/config"
	"agentkit/internal/update"
)

func liveUpdateIdle() bool { return update.LiveReady(config.Repo()) }

func (t *ticking) liveUpdate() error {
	err := update.GoLive(config.Repo(), t.log.line)
	if errors.Is(err, update.ErrPython) {
		return errLeft
	}
	return err
}
