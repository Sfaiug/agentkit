package terminal

import (
	"os"
	"syscall"
	"unsafe"
)

func isTerminal(file *os.File) bool {
	var mode uint32
	return syscall.GetConsoleMode(syscall.Handle(file.Fd()), &mode) == nil
}

var screenBufferInfo = syscall.NewLazyDLL("kernel32.dll").NewProc("GetConsoleScreenBufferInfo")

func columns(file *os.File) int {
	// CONSOLE_SCREEN_BUFFER_INFO: size, cursor, attributes, then the window's corners
	var info struct {
		size, cursor             [2]int16
		attributes               uint16
		left, top, right, bottom int16
		maximum                  [2]int16
	}
	if ok, _, _ := screenBufferInfo.Call(file.Fd(), uintptr(unsafe.Pointer(&info))); ok == 0 {
		return 0
	}
	return int(info.right-info.left) + 1
}
