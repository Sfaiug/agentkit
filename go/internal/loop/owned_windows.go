package loop

import "os"

// owned is true on Windows, where no account's folder under the run's own is another's.
func owned(os.FileInfo) bool { return true }
