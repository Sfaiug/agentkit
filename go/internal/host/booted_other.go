//go:build !linux

package host

// booted is nothing here: no /proc holds a start to count from it.
func booted() float64 { return 0 }
