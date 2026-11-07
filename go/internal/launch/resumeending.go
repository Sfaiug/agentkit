package launch

import (
	"io"

	"agentkit/internal/run"
)

// ResumeEnding is ResumeExpected of a run whose loop may still run, as the tick's stall ladder
// resumes one: end ends that loop only once Go's resume has taken the run up, so a resume left to
// Python leaves the loop running and nothing written.
func ResumeEnding(id string, expected *run.Object, end func(), order func(*run.Object), noted func()) (int, string, error) {
	return resume(id, true, expected, end, order, noted, io.Discard, io.Discard)
}
