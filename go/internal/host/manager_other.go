//go:build !linux

package host

// userManager is false: only Linux runs a user systemd manager.
func userManager() bool { return false }
