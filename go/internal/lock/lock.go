// Package lock takes the file locks Go ak shares with Python ak, which takes each one with
// fcntl.flock: on a file opened to append to, or to read and write, or on a directory opened to
// read. It hides how
// each platform does it. Unix takes flock itself. Windows, where no Python ak runs beside Go,
// opens a file shared with nobody, which keeps Go's own processes apart, and locks no
// directory.
package lock

import (
	"context"
	"errors"
	"os"
	"time"
)

// ErrHeld is Try's answer while another holder has the lock.
var ErrHeld = errors.New("held by another process")

// poll is how often Wait asks again while its context may end, which a blocking lock ignores.
const poll = 20 * time.Millisecond

// Try takes path's lock if nobody holds it now, else answers ErrHeld. A missing file is made,
// and the lock lasts until the file closes.
func Try(path string) (*os.File, error) {
	return acquire(path, false)
}

// Edit opens path's file, which it never makes, to read and write once its lock is free; the
// lock lasts until the file closes.
func Edit(path string) (*os.File, error) {
	return edit(path)
}

// Wait takes path's lock once it is free, or gives up with ctx's error once ctx ends. A
// missing file is made, and the lock lasts until the file closes.
func Wait(ctx context.Context, path string) (*os.File, error) {
	if ctx.Done() == nil {
		return acquire(path, true)
	}
	for {
		file, err := acquire(path, false)
		if !errors.Is(err, ErrHeld) {
			return file, err
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(poll):
		}
	}
}
