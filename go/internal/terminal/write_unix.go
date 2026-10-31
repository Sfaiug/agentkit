//go:build linux || darwin

package terminal

import (
	"syscall"
	"unsafe"
)

// Write puts data on the terminal at path as Python's terminal_notice does, and whether it all
// went: opened without becoming its controlling terminal, never following a link or waiting on a
// full one, and written only to a character device that is a terminal.
func Write(path string, data []byte) bool {
	fd, err := syscall.Open(path, syscall.O_WRONLY|syscall.O_NOCTTY|syscall.O_NONBLOCK|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err != nil {
		return false
	}
	defer syscall.Close(fd)
	var info syscall.Stat_t
	var size struct{ rows, columns, x, y uint16 }
	if syscall.Fstat(fd, &info) != nil || info.Mode&syscall.S_IFMT != syscall.S_IFCHR {
		return false
	}
	// a window size, which only a terminal has, asked by the one ioctl both systems name alike
	if _, _, errno := syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), syscall.TIOCGWINSZ, uintptr(unsafe.Pointer(&size))); errno != 0 {
		return false
	}
	written, err := syscall.Write(fd, data)
	return err == nil && written == len(data)
}
