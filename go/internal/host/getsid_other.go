//go:build unix && !linux

package host

import "syscall"

func getsid(pid int) (int, error) {
	return syscall.Getsid(pid)
}
