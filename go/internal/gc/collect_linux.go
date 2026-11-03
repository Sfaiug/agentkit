//go:build linux

package gc

import (
	"io/fs"
	"syscall"
)

// diskBytes is what an entry takes on disk, its blocks counted as `du` counts them.
func diskBytes(info fs.FileInfo) int64 {
	if sys, ok := info.Sys().(*syscall.Stat_t); ok {
		return sys.Blocks * 512
	}
	return 0
}

// shut is a folder this user may not read, write or enter: no retry empties it.
func shut(path string) bool {
	return syscall.Access(path, 0o7) != nil
}
