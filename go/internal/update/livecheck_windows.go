package update

// LiveCheck checks nothing on Windows, whose tick leaves each check to Python (LiveReady).
func LiveCheck(string) int { return 1 }
