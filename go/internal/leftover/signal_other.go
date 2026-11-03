//go:build !linux || mips || mipsle || mips64 || mips64le

package leftover

import "syscall"

// signal sends nothing where ak holds no pidfd: a pid alone may name another process by the
// time the signal goes. Without /proc a look finds nothing to send it to anyway.
func signal(int, int64, syscall.Signal) bool { return false }
