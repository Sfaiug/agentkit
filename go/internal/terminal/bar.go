package terminal

// RGB is a word's colour as a seat's bar draws it whichever process writes it: in the theme
// config.toml names, else black, as tmux shows the bar on a terminal ak never asks.
func RGB(word string) string { return colourOf(word, inForce(black)) }

// ASCII is whether this screen draws without UTF-8.
func (s Screen) ASCII() bool { return s.ascii }
