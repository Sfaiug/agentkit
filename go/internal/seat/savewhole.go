package seat

import (
	"context"
	"errors"
	"os"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// SaveWhole is `save`, one of config's whole-file writers, every seat's record first holding the
// efforts it runs at, as Python's save keeps them, so none moves with it.  The records change
// all or none, their locks held from before they are read until config.toml lands, so a record
// written meanwhile waits.  False, with nothing written, leaves the change to Python: a config Go
// binds otherwise, or a record holding what Go cannot write back.
func SaveWhole(save func(keep func() error) error) (bool, error) {
	bound, err := config.Bind()
	if err != nil {
		return false, nil
	}
	models, err := config.Models()
	if err != nil {
		return true, err
	}
	offered, err := config.Offered()
	if err != nil {
		return true, err
	}
	err = savingEfforts(bound.Models, models, offered, waitLocks, save)
	if errors.Is(err, run.ErrLoneSurrogate) {
		return false, nil
	}
	return true, err
}

// waitLocks takes every lock, as Python's save waits for each record's: on a busy one it lets
// all go and waits for that one alone, then takes them all again (tryLocks).
func waitLocks(paths []string) ([]*os.File, error) {
	for {
		held, err := tryLocks(paths)
		if !errors.Is(err, lock.ErrHeld) {
			return held, err
		}
		for _, file := range held {
			file.Close()
		}
		busy, err := lock.Wait(context.Background(), paths[len(held)])
		if err != nil {
			return nil, err
		}
		busy.Close()
	}
}
