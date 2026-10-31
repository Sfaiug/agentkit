//go:build !linux

package box

import (
	"errors"
	"os"
)

// Supported is false: bubblewrap's box runs on Linux alone.
const Supported = false

// Run refuses, as there is no box to run argv in.
func Run(argv []string, env map[string]string, workspace, out string, state, logins, hidden []string, stderr *os.File) (int, error) {
	return 0, errors.ErrUnsupported
}

// First is false: nothing starts this program as a box's first process here.
func First() (int, bool) { return 0, false }

// Check is nil: no box starts here, a turn being Python's, which checks its own.
func Check() error { return nil }
