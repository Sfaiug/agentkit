package terminal

// RGB is a word's colour as a seat's bar draws it whichever process writes it: in the shades kept,
// as tmux shows the bar on a terminal ak never asks.
func RGB(word string) string { return RGBs(word)[0] }

// RGBs is each word's colour as RGB says it, the shades kept read once for them all.
func RGBs(words ...string) []string {
	shades, said := kept(), make([]string, len(words))
	for i, word := range words {
		said[i] = roles[roleOf(word)][shades]
	}
	return said
}

// ASCII is whether this screen draws without UTF-8.
func (s Screen) ASCII() bool { return s.ascii }
