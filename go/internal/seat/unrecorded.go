package seat

import (
	"errors"
	"fmt"
	"io"
	"os"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Stderr is where a seat file write that fails says so, as watch.seat_write prints to stderr: the
// tick points it at its log's, which dates each line.
var Stderr io.Writer = os.Stderr

// unrecorded is a seat file write's error as watch.seat_write takes one: a WARN, and what was
// under way goes on without it.  A file Go cannot write back as it was stays its caller's error.
func unrecorded(name string, err error) error {
	if err == nil || errors.Is(err, run.ErrLoneSurrogate) {
		return err
	}
	fmt.Fprintf(Stderr, "WARN could not record what %s is doing: %s\n", name, config.PyError(err))
	return nil
}
