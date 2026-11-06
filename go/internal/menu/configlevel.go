package menu

import "agentkit/internal/terminal"

// Level is the level, from 0, that a click on an effort's cell takes, `word` the effort it ends in
// (menu.config_matrix): the cell of its bar under the pointer, past its last level on the gap before
// the word, which takes none. On the word, or an effort drawn without a bar, it is -1: a step, as Space.
func (f MatrixFrame) Level(mouse terminal.Mouse, word string) int {
	if mouse.Row > 0 && mouse.Row <= len(f.spots) {
		for _, cell := range f.spots[mouse.Row-1].cells {
			at := mouse.Column - cell.first
			if cell.column >= 3 && at >= 0 && mouse.Column <= cell.last && at < cell.last-cell.first+1-terminal.Cells(word) {
				return at
			}
		}
	}
	return -1
}
