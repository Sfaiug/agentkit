//go:build linux && (amd64 || arm64)

package update

import (
	"os"
	"runtime"
	"syscall"
	"unsafe"
)

// renameat2 is that call's number here: Go's syscall package names it on arm64 alone.
var renameat2 = map[string]uintptr{"amd64": 316, "arm64": 276}[runtime.GOARCH]

// exchange swaps the directories at one and other in one renameat2(2), as Python's
// versions.exchange does.
var exchange = func(one, other string) error {
	from, err := syscall.BytePtrFromString(one)
	if err != nil {
		return err
	}
	to, err := syscall.BytePtrFromString(other)
	if err != nil {
		return err
	}
	const exchanged = 2 // RENAME_EXCHANGE
	cwd := -100         // AT_FDCWD
	_, _, errno := syscall.Syscall6(renameat2, uintptr(cwd), uintptr(unsafe.Pointer(from)),
		uintptr(cwd), uintptr(unsafe.Pointer(to)), exchanged, 0)
	if errno != 0 {
		return &os.LinkError{Op: "renameat2", Old: one, New: other, Err: errno}
	}
	return nil
}
