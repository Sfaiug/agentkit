package history

// BlameMerge is Python's history.blame_merge: the run that merged sha marked broken after its merge
// by source, once, as a measure already there is kept; its id, "" where no row merged it or the
// write failed, said on log.
func BlameMerge(sha, source string, log func(string)) string {
	var name string
	if !apply(log, func(db *DB) error {
		rows, err := db.rows("SELECT run_id FROM runs WHERE merge_sha=?", sha)
		if err != nil || len(rows) == 0 {
			return err
		}
		name = rows[0].Text("run_id")
		return db.exec("UPDATE runs SET broke_after_merge=? WHERE run_id=? AND COALESCE(broke_after_merge,'')=''", source, name)
	}) {
		return ""
	}
	return name
}
