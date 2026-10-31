//go:build !linux

package box

import (
	"context"
	"errors"
	"os"
)

// Supported is false: bubblewrap's box runs on Linux alone.
const Supported = false

// Run refuses, as there is no box to run argv in.
func Run(ctx context.Context, argv []string, env map[string]string, workspace, out string, state, logins, hidden []string, stderr *os.File) (int, map[int]string, error) {
	return 0, nil, errors.ErrUnsupported
}

// First is false: nothing starts this program as a box's first process here.
func First() (int, bool) { return 0, false }

// Check is nil: there is no box here to start, a turn being Python's.
func Check() error { return nil }
