package run

import (
	"path/filepath"

	"agentkit/internal/lock"
)

// DeliverNow is Deliver for a caller that never waits, as a prompt never does: lock.ErrHeld, with
// nothing written, while another holds the run directory's lock.
func DeliverNow(dir string, change func(*Object) error) error {
	return deliver(dir, func(dir, name string) (func(), error) {
		file, err := lock.Try(filepath.Join(dir, name))
		if err != nil {
			return nil, err
		}
		return func() { file.Close() }, nil
	}, change)
}
