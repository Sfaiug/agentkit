package terminal

// Moves is whether colour can move on this screen: nothing moves off a terminal, under NO_COLOR or
// at eight colours, which hold no tone between two (motion.Clock.start).
func (s Screen) Moves() bool { return s.depth > 8 }

// Tinted is text in word's colour amount (0 to 1) of the way to the background, or with a negative
// one that far toward the foreground: the colour alone, none of the word's emphasis.  On the
// highlighted row, lit, on the terminal's own background (lookOn) it goes to the highlight, as
// Python's motion.tinted.
func (s Screen) Tinted(text, word string, amount float64, lit bool) string {
	ground := "background"
	if lit && s.own != (own{}) {
		ground = "selection"
	}
	return s.Styled(text, s.faded(word, amount, ground))
}
