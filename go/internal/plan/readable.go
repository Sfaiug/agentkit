package plan

// Readable is ErrUnread where a line the seat owes, or the done check its finished plan owes, is
// one Go cannot weigh as Python does, nil where it weighs every one: then neither Owes nor
// Unserved leaves the seat's work unread.
func Readable(name string) error {
	for _, err := range (Look{}).owed(name, true) {
		if err != nil {
			return err
		}
	}
	return nil
}
