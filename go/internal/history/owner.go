package history

// OwnerTime is Python's history.owner_time: a moment of the owner's time, a question a seat
// `asked` them, or one `answered`, `waited` seconds after it was asked, nil for an asked one,
// naming the seat's conversation as `<harness>:<id>`, nil where its harness says it holds none.
// It is a commit of its own, as history._write makes it: what goes wrong is said in history.log,
// and never stops its caller.
func OwnerTime(kind string, at float64, waited, conversation any) {
	apply(nil, func(db *DB) error {
		return db.exec("INSERT INTO owner (at, kind, waited, conversation) VALUES (?, ?, ?, ?)", at, kind, waited, conversation)
	})
}
