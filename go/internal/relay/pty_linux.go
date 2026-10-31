package relay

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

// a terminal's modes, read and set at once
const get, set = syscall.TCGETS, syscall.TCSETS

// unlock opens the program's end of a new pty, and answers its path.
func unlock(master *os.File) (string, error) {
	var locked int32
	var number uint32
	if err := ioctl(master, syscall.TIOCSPTLCK, unsafe.Pointer(&locked)); err != nil {
		return "", err
	}
	if err := ioctl(master, syscall.TIOCGPTN, unsafe.Pointer(&number)); err != nil {
		return "", err
	}
	return fmt.Sprintf("/dev/pts/%d", number), nil
}

// wait is select(2) on what can be read.
func wait(n int, readable *syscall.FdSet) error {
	_, err := syscall.Select(n, readable, nil, nil, nil)
	return err
}
