package handback

import (
	"context"
	"path/filepath"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// MarkDelivery is Python's mark_delivery from outside the run's delivery lock: the marks written
// under it onto the record as it stands, nil taking one off, only while it is the attempt record
// is of; false where it moved on or could not be written.
func MarkDelivery(dir string, record *run.Object, pairs ...any) bool {
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return false
	}
	defer held.Close()
	return mark(dir, record, pairs...)
}
