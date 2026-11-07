package plan

// Readable is ErrUnread where a line the seat owes is one Go cannot weigh as Python does, nil
// where it weighs every one: then neither Owes nor Unserved leaves the seat's work unread.
func Readable(name string) error {
	for _, err := range owed(name) {
		if err != nil {
			return err
		}
	}
	return nil
}
