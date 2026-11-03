//go:build linux || darwin

package seat

import (
	"syscall"
	"unsafe"
)

// ttyUnread is whether the terminal at path holds input nobody has read, asked of the kernel
// without taking it; one that cannot be asked holds none, as Python's pane_unread has it.
func ttyUnread(path string) bool {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NONBLOCK|syscall.O_NOCTTY, 0)
	if err != nil {
		return false
	}
	defer syscall.Close(fd)
	var count int32
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), fionread, uintptr(unsafe.Pointer(&count)))
	return errno == 0 && count > 0
}
