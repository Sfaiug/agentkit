package launch

import (
	"errors"
	"io"

	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// ResumeEnding is the tick's stall ladder resuming a run whose loop may still run, decided once:
// only once Go's resume takes the run up does end end that loop and write the order, under the
// run's lock as Python's ladder does, returning the record as kept, which the resume then adopts.
// A resume left to Python leaves the loop running and nothing written.
func ResumeEnding(id string, expected *run.Object, order func(*run.Object), end func() (*run.Object, error)) (int, string, error) {
	took, code, why, err := take(id, expected, order, true)
	if took == nil {
		return code, why, err
	}
	kept, err := end()
	switch {
	case errors.Is(err, loop.ErrChanged):
		return 2, err.Error(), nil
	case err != nil:
		return 0, "", err
	}
	return taken{took.dir, kept, kept}.carry(nil, nil, true, io.Discard, io.Discard)
}
