package tick

import "os"

// dup is never reached on Windows, where Overlap leaves every tick to Python.
func dup(from, stream *os.File) {}
