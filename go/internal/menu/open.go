package menu

import "agentkit/internal/terminal"

// Open is the seat Enter or a released left button opens on the frame the owner saw; Enter opens
// nothing where the highlight was hidden (Highlight.Move).
func (f Frame) Open(key terminal.Key) string {
	if key.Name == "enter" && !f.hidden {
		return f.cursor
	}
	m := key.Mouse
	if key.Name == "pointer" && m.Released && m.Button&3 == 0 && m.Button&64 == 0 {
		return f.seatAt(m)
	}
	return ""
}
