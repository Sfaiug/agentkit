package waitfact

import (
	"errors"
	"path/filepath"

	"agentkit/internal/job"
	"agentkit/internal/run"
)

// Job is wait_fact for a job: over, with the line saying how, once its receipt says it finished,
// or once it is gone.
func Job(on string) (bool, string, error) {
	receipt, err := job.Read(filepath.Join(job.Jobs(), on))
	switch {
	case errors.Is(err, run.ErrLoneSurrogate), errors.Is(err, run.ErrLimit):
		return false, "", ErrPython
	case receipt == nil || len(receipt.Keys()) == 0: // Python's `not job`
		return true, "job " + on + " is gone", nil
	case receipt.Truthy("finished_at"):
		return true, "job " + on + " finished", nil
	}
	return false, "", nil
}
