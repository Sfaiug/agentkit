package menu

import "agentkit/internal/terminal"

// seatAt is the seat whose row the pointer is on where that row is drawn (terminal.Under): "" off
// every row, and on the blank past a row's text.
func (f Frame) seatAt(mouse terminal.Mouse) string {
	if mouse.Row <= 0 || mouse.Row > min(len(f.spots), len(f.Lines)) {
		return ""
	}
	if _, on := terminal.Under(f.Lines[mouse.Row-1], mouse.Column); !on {
		return ""
	}
	return f.spots[mouse.Row-1]
}
