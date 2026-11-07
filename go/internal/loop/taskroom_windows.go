package loop

// taskRoom is nil on Windows, which keeps no account's count of tasks for a start to fail on.
func taskRoom(int) error { return nil }
