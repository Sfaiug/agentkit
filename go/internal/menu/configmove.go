package menu

import "agentkit/internal/terminal"

// ConfigMoveFrame puts the shared confirmation after the matrix's visible rows,
// keeping the marked model on screen when the card makes the page shorter.
func ConfigMoveFrame(s terminal.Screen, view ConfigView, name string) Frame {
	matrix := ConfigFrame(s, view)
	frame := Frame{Lines: matrix.Lines, width: s.Width(), height: s.Height(), spots: make([]string, len(matrix.spots))}
	for i, row := range matrix.spots {
		if row.row == view.Row || i == len(matrix.spots)-1 {
			frame.spots[i] = name
		}
	}
	return frame
}
