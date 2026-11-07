package history

import "github.com/ncruces/go-sqlite3"

// Writable is whether Go's writes reach history.db as it stands: not where SQLite cannot read it,
// nor while its tokens wait for Python's one-time repair, which Python's first write makes.
func Writable() bool {
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		return false
	}
	defer db.Close()
	_, err = db.recounted()
	return err == nil
}
