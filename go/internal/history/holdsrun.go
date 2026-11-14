package history

import (
	"errors"
	"io/fs"
	"os"
)

// HoldsRun is whether history.db may hold a run but own's, the run whose pick asks ("" for none): false
// only where none stands, and none is made, or where it reads as holding no other row of runs.
// Nothing refreshes its answer, so a pick decides by it before usage is read.
func HoldsRun(own string) bool {
	if _, err := os.Stat(Path()); errors.Is(err, fs.ErrNotExist) {
		return false
	}
	db := Look()
	defer db.Close()
	rows, read := db.read("SELECT 1 FROM runs WHERE run_id IS NOT ? LIMIT 1", own)
	return !read || len(rows) > 0
}
