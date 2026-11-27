package terminal

// RGB is a word's colour as a seat's bar draws it whichever process writes it: in the shades kept,
// as tmux shows the bar on a terminal ak never asks.
func RGB(word string) string { return RGBs(word)[0] }

// RGBs is each word's colour as RGB says it, the shades kept read once for them all.
func RGBs(words ...string) []string {
	shades, said := kept(), make([]string, len(words))
	for i, word := range words {
		said[i] = colourOf(word, shades)
	}
	return said
}

// Background is the environment variable Ctrl-b m hands its popup's menu the colour kept in, where
// the look reads on it (InLook), as Python's terminal.BACKGROUND_ENV: the menu draws in the look
// there (Keyboard.Sense), never reading the colour kept itself, so frame and menu are of one read.
const Background = "AGENTKIT_BACKGROUND"

// InLook is each word's colour in the look on the colour kept and that colour after them, where the
// look reads there (lookOn), else as RGBs says them, the file read once for them all, as Python's
// themes.py asked `look`: what Ctrl-b m frames its popup in and hands its menu (tmux.ColoursVerb).
func InLook(words ...string) []string {
	kept, colour := said(), ""
	if len(kept) > 1 {
		colour = kept[1]
	}
	screen := Screen{theme: fits(kept)}
	// only a colour the menu handed it takes in the theme kept (Sense), which its rounding to
	// rrggbb can tip at half way
	if in, ok := themeOfRGB(colour); ok && in == screen.theme {
		screen.own = lookOn(colour, in)
	}
	shown := make([]string, len(words))
	for i, word := range words {
		shown[i] = screen.colour(word)
	}
	if screen.own == (own{}) {
		return shown
	}
	return append(shown, colour)
}

// ASCII is whether this screen draws without UTF-8.
func (s Screen) ASCII() bool { return s.ascii }
