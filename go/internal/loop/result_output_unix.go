//go:build linux || darwin

package loop

import (
	"os"
	"syscall"
)

func diagnosticFile(path string) *os.File {
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil
	}
	if info, err := file.Stat(); err == nil && info.Mode().IsRegular() {
		if stat := info.Sys().(*syscall.Stat_t); stat.Uid == uint32(os.Geteuid()) && stat.Nlink == 1 {
			return file
		}
	}
	file.Close()
	return nil
}
