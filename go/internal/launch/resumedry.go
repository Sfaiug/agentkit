package launch

import (
	"errors"
	"io"

	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// parkDry keeps waiting a run whose window has not refilled, Python's resume_run on a QuotaDry: no
// slot and no turn, and the exit status of a run that ended exhausted.
func parkDry(dir string, read *run.Object, order func(*run.Object), why string, out io.Writer) (int, string, error) {
	slots, err := holdSlots()
	if err != nil {
		return 0, "", err
	}
	defer slots.Close()
	if err := loop.ParkDry(dir, read, order, why, out); errors.Is(err, loop.ErrChanged) {
		return 2, err.Error(), nil
	} else if err != nil {
		return 0, "", err
	}
	return 1, "", nil
}
