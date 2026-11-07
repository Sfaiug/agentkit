package history

const readingsKeptFor = 35 * 86400 // seconds a meter reading is kept: five weeks (READINGS_KEPT_FOR)

// KeepReadings is Python's history.keep_readings: meter_readings rows added, each its values in
// the columns' order (provider, account, meter, used, resets_at, window_secs, at, source, plan),
// one kept already adding nothing, and the rows past five weeks dropped once one went in.  What
// goes wrong is said in history.log, as Python's.
func KeepReadings(rows [][]any) {
	if len(rows) == 0 {
		return
	}
	apply(nil, func(db *DB) error {
		added := false
		for _, row := range rows {
			err := db.exec("INSERT OR IGNORE INTO meter_readings (provider, account, meter, used, resets_at, "+
				"window_secs, at, source, plan) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row...)
			if err != nil {
				return err
			}
			added = added || db.conn.Changes() > 0
		}
		if !added {
			return nil
		}
		return db.exec("DELETE FROM meter_readings WHERE at < ?", now()-readingsKeptFor)
	})
}
