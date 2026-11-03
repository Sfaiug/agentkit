//go:build linux

package gc

import (
	"io/fs"
	"os"
	"syscall"
)

// ported: the plan's reads of /proc, of what a file is and whose, and of locks are Linux's.
const ported = true

// open reads without moving an access time or following a link (retention.reading).
func open(path string, directory bool) (*os.File, error) {
	flags := os.O_RDONLY | syscall.O_NOFOLLOW | syscall.O_NOATIME
	if directory {
		flags |= syscall.O_DIRECTORY
	}
	return os.OpenFile(path, flags, 0)
}

func statOf(info fs.FileInfo) (stat, bool) {
	sys, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return stat{}, false
	}
	return stat{dev: uint64(sys.Dev), ino: sys.Ino, mode: uint32(sys.Mode), uid: sys.Uid, nlink: uint64(sys.Nlink),
		size: sys.Size, mtime: sys.Mtim.Nano(), ctime: sys.Ctim.Nano()}, true
}

// unlocked is whether nobody holds the file's lock: taken without waiting, and let go at once.
func unlocked(file *os.File) bool {
	return syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB) == nil
}

func diskUse(path string) (used, total uint64, ok bool) {
	var fs syscall.Statfs_t
	if syscall.Statfs(path, &fs) != nil {
		return 0, 0, false
	}
	size := uint64(fs.Frsize)
	return (fs.Blocks - fs.Bfree) * size, fs.Blocks * size, true
}
