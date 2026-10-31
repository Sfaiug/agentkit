package terminal

// Bold is text in bold, as a subscription heads its meters on a phone; plain where nothing is
// coloured.
func (s Screen) Bold(text string) string {
	if s.depth == 0 || text == "" {
		return text
	}
	return "\x1b[1m" + text + "\x1b[0m"
}
