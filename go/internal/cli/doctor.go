package cli

import (
	"io"

	"agentkit/internal/doctor"
)

func init() { commands["doctor"] = doctorAnswer }

// doctorAnswer answers `ak doctor` as Python's watch.doctor does, or leaves all of it to Python
// where it reads what Go cannot.
func doctorAnswer(_ []string, out, errOut io.Writer) int {
	code, read := doctor.Report(out, errOut)
	if !read {
		return notImplemented(errOut, "doctor")
	}
	return code
}
