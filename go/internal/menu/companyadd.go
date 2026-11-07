package menu

import (
	"time"

	"agentkit/internal/matrix"
	"agentkit/internal/terminal"
)

// CompanyAddFrame is `<title> · add a company` (menu.company_add): a row for each of `others`,
// its name, how many listed models it has and the first, its strongest, laid out by TableRow with
// the first two columns as wide as their widest; the row `at` lit unless the pointer is `away`, and
// paged so it is shown.
func CompanyAddFrame(s terminal.Screen, title string, others []matrix.Company, at, top int, away bool) MatrixFrame {
	keys := "↑↓ company   ⏎ add   esc back"
	if s.ASCII() {
		keys = "up/down company   enter add   esc back"
	}
	counts, widths := make([]string, len(others)), make([]int, 3)
	for i, company := range others {
		counts[i] = counted(len(company.Models), "model", "models")
		widths[0], widths[1] = max(widths[0], terminal.Cells(company.Maker)), max(widths[1], terminal.Cells(counts[i]))
	}
	widths[2] = max(1, s.LayoutWidth()-6-widths[0]-widths[1])
	page := max(1, s.Height()-5-len(keyLine(s, keys, s.Width(), "")))
	top = max(0, min(max(top, at-page+1), at, len(others)-page))
	var lines []string
	spots := []matrixRow{{row: -1}, {row: -1}}
	for row := top; row < min(top+page, len(others)); row++ {
		line := "  " + s.TableRow([]string{others[row].Maker, counts[row], others[row].Models[0][1]}, widths, nil)
		if row == at && !away {
			line = s.Highlight(line, true)
		}
		lines, spots = append(lines, line), append(spots, matrixRow{line: line, row: row})
	}
	return MatrixFrame{Panel(s, title, time.Now().Format("15:04"), lines, keys), top, spots}
}
