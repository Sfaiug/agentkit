//go:build !linux && !darwin

package harness

import "os"

// fileStamp is false here: Python's stat says st_dev and st_ino of no file Go can read the same.
func fileStamp(os.FileInfo) ([]any, bool) { return nil, false }
