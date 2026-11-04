package loop

import "os"

// Windows does not run boxed checks; a kept Unix output reference remains readable as a reference.
func diagnosticFile(string) *os.File { return nil }
