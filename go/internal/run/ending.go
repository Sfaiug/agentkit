package run

import "time"

// HandedBack is whether this ending, and not an earlier attempt's, was handed back.
// An undated mark is taken at its word.
func HandedBack(record *Object) bool {
	said, dated := Num(record.Get("handed_back"))
	if !dated {
		return record.Truthy("handed_back")
	}
	ended := record.Get("finished_at")
	if !record.Truthy("finished_at") {
		ended = record.Get("interrupted_at")
	}
	if at, ok := Num(ended); ok {
		return said >= at
	}
	return true
}

// OwesEnding is Python's owes_ending: a deliberate stop, an ending already told or
// reported, and an error the tick will retry owe no ending.
func OwesEnding(record *Object, now time.Time) bool {
	return record.Str("state") != "stopped" && !(record.Str("state") == "error" && Going(record, now)) &&
		Ended(record) && !HandedBack(record) && !record.Truthy("reported")
}
