package history

import "os"

// Owed is whether a write of a run's row is Python's (leftToPython): its tokens wait for Python's
// one-time repair, which the write makes first, or SQLite cannot say.  Where none stands, none is.
func Owed() bool {
	path := Path()
	if info, err := os.Stat(path); err != nil || !info.Mode().IsRegular() {
		return false
	}
	_, err := leftToPython(path)
	return err != nil
}
