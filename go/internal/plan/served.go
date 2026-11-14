package plan

import "slices"

// Unserved is whether the seat owes a line no run's `plan_line` in served names, `<what> · written
// <when>` (handback._unserved_line): a plan nothing can read, or a line in no other form, serves
// nothing.  ErrUnread where only lines Go cannot weigh could be unserved.
func Unserved(name string, served []string) (bool, error) {
	var unread error
	for line, err := range (Look{}).owed(name, false) {
		if err != nil {
			unread = err
		} else if line.When == "" || !slices.Contains(served, line.What+" · written "+line.When) {
			return true, nil
		}
	}
	return false, unread
}
