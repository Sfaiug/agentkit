package launch

import (
	"path/filepath"

	"agentkit/internal/run"
)

// Takes is whether Go's resume takes the run up once its loop is gone, the record as order leaves
// it: the tick's stall ladder asks before it ends a loop whose resume would be Python's.
func Takes(id string, record *run.Object, order func(*run.Object)) bool {
	dir := filepath.Join(run.Runs(), id)
	ordered := record.Copy()
	order(ordered)
	return reached(dir, record) && goesOn(dir, record, ordered)
}
