package terminal

// RGB is a state word's colour on a dark background, as a seat's bar draws it whichever process
// writes it.
func RGB(word string) string { return colourOf(word, false).rgb }

// Ink is the text that reads on a state word's colour, as a seat's bar draws its chip.
func Ink(word string) string { return colourOf(word, false).ink }

// ASCII is whether this screen draws without UTF-8.
func (s Screen) ASCII() bool { return s.ascii }
