package terminal

// Lit is the act the keys are on among others on a line: reversed, or bracketed where no colour
// can reverse it.
func (s Screen) Lit(text string) string {
	if s.depth == 0 {
		return "[" + text + "]"
	}
	return s.Reverse(text)
}
