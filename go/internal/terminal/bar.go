package terminal

// RGB is a state word's colour on a dark background, as a seat's bar draws it whichever process
// writes it.
func RGB(word string) string { return styles[word].rgb }

// ASCII is whether this screen draws without UTF-8.
func (s Screen) ASCII() bool { return s.ascii }
