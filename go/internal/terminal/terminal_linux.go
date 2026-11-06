package terminal

import (
	"os"
	"syscall"
	"unsafe"
)

func isTerminal(file *os.File) bool {
	var state syscall.Termios
	_, _, err := syscall.Syscall(syscall.SYS_IOCTL, file.Fd(), syscall.TCGETS, uintptr(unsafe.Pointer(&state)))
	return err == 0
}

func size(file *os.File) (columns, rows int) {
	var size struct{ rows, columns, x, y uint16 }
	if _, _, err := syscall.Syscall(syscall.SYS_IOCTL, file.Fd(), syscall.TIOCGWINSZ, uintptr(unsafe.Pointer(&size))); err != 0 {
		return 0, 0
	}
	return int(size.columns), int(size.rows)
}
