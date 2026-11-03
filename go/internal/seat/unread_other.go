//go:build !linux && !darwin

package seat

// ttyUnread holds no input where Go cannot ask the kernel, as a terminal that cannot be asked
// holds none in Python's pane_unread.
func ttyUnread(string) bool { return false }
