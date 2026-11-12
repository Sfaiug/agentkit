package history

import (
	"os"
	"strconv"
	"unicode/utf8"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/run"
)

// Reader is history.db as Python's history.get reads it, through a connection that cannot write,
// its tables as they stand: nil where none stands.  An error where Python's read would write
// first, or Go cannot read the database as Python does (leftToPython), decided under Python's
// writers' lock as Python's recount decides.
func Reader() (*DB, error) {
	path := Path()
	if _, err := os.Stat(path); err != nil {
		return nil, nil
	}
	held, err := writers(path)
	if err != nil {
		return nil, err
	}
	defer held.Close()
	if _, err := leftToPython(path); err != nil {
		return nil, err
	}
	return connect(path, sqlite3.OPEN_READONLY)
}

// Row is the row runs holds for the id, bound as Python binds it, its columns in the table's
// order, Python's history.get: empty where there is none or it cannot be read.
func (db *DB) Row(id any) *run.Object {
	const query = "SELECT * FROM runs WHERE run_id=?"
	row := run.NewObject()
	found, read := db.read(query, id)
	if !read || len(found) == 0 {
		return row
	}
	// a Row keeps no order: the statement names its columns in the table's
	stmt, _, err := db.conn.Prepare(query)
	if err != nil {
		return row
	}
	defer stmt.Close()
	for col := range stmt.ColumnCount() {
		name := stmt.ColumnName(col)
		switch value := found[0][name].(type) {
		case int64:
			row.Set(name, run.Number(strconv.FormatInt(value, 10)))
		case string:
			// Python's sqlite3 reads text as UTF-8 or not at all
			if !utf8.ValidString(value) {
				return run.NewObject()
			}
			row.Set(name, value)
		default:
			row.Set(name, value)
		}
	}
	return row
}
