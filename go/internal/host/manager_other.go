//go:build !linux

package host

// UserManager is false: only Linux runs a user systemd manager.
func UserManager() bool { return false }
