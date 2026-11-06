package menu

import (
	"slices"
	"time"

	"agentkit/internal/terminal"
)

// ModelsBody is the same answer without the interactive frame, for ak models.
func ModelsBody(s terminal.Screen, said []Role, compared map[string]bool, total int, fetched float64) []string {
	var lines []string
	for _, row := range modelsBody(s, said, compared, total, fetched, ModelLight{}) {
		lines = append(lines, row.line)
	}
	return lines
}

// ModelsFrame keeps the legend below the paged frontier and the pointer on its row,
// including a folded row's mark, numbers and notes.
func ModelsFrame(s terminal.Screen, title string, said []Role, compared map[string]bool, total int, fetched float64, at, top int, note string, light ModelLight) MatrixFrame {
	keys := "↑↓ move   ⏎ why   p models   r take   esc back"
	if s.ASCII() {
		keys = "up/down move   enter why   p models   r take   esc back"
	}
	body := modelsBody(s, said, compared, total, fetched, light)
	fold := slices.IndexFunc(body, func(row matrixRow) bool { return row.row == -2 })
	var under []string
	for _, row := range body[fold:] {
		under = append(under, row.line)
	}
	for _, part := range terminal.Wrap(note, s.LayoutWidth()-2) {
		under = append(under, "  "+s.Styled(part, "dim"))
	}
	body = body[:fold]
	room := max(1, s.Height()-3-len(keyLine(s, keys, s.Width(), ""))-len(under))
	first, last := -1, -1
	for i, row := range body {
		if row.row == at && at >= 0 {
			if first < 0 {
				first = i
			}
			last = i
			body[i].line = s.Highlight(row.line, i == first)
		}
	}
	top = max(0, min(max(top, min(last, first+room-1)-room+1), max(0, first), max(0, len(body)-room)))
	var lines []string
	spots := []matrixRow{{row: -1}, {row: -1}}
	for _, row := range body[top:min(top+room, len(body))] {
		lines = append(lines, row.line)
		spots = append(spots, row)
	}
	lines = append(lines, under...)
	return MatrixFrame{Panel(s, title, time.Now().Format("15:04"), lines, keys), top, spots}
}
