//go:build unix

package loop

import (
	"os"
	"syscall"
)

// owned is whether this account owns the file.
func owned(info os.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && int(stat.Uid) == os.Getuid()
}
