package history

// A Moment is one of the owner's time, Python's history.owner_time: a question a seat `asked`
// them, or one `answered`, Waited seconds after it was asked, nil for an asked one.
type Moment struct {
	Kind   string
	At     float64
	Waited any
}

// Owner writes those moments, in that order and in one commit, each naming the seat's
// conversation as `<harness>:<id>`, nil where its harness says it holds none.
func Owner(conversation any, moments []Moment, log func(string)) {
	if len(moments) == 0 {
		return
	}
	apply(log, func(db *DB) error {
		for _, moment := range moments {
			if err := db.exec("INSERT INTO owner (at, kind, waited, conversation) VALUES (?, ?, ?, ?)",
				moment.At, moment.Kind, moment.Waited, conversation); err != nil {
				return err
			}
		}
		return nil
	})
}
