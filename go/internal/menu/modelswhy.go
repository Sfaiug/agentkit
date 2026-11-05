package menu

import (
	"fmt"
	"strings"

	"agentkit/internal/quality"
	"agentkit/internal/terminal"
)

// ModelsWhy lays out the rating's explanation, folding each measure's how under it
// when the table would be too wide. Only a model's name is cut.
func ModelsWhy(s terminal.Screen, found *quality.Said, role string, row *quality.Rating) []string {
	why := quality.Explain(found, role, row)
	room := s.LayoutWidth() - 2
	named := func(row *quality.Rating, room int) string {
		effort := ""
		if row.Effort != "" {
			effort = " " + row.Effort
		}
		return terminal.Cut(row.Name, room-terminal.Cells(effort)) + effort
	}
	pack := func(parts []string, gap string) []string {
		var lines []string
		for _, part := range parts {
			if len(lines) > 0 && terminal.Cells(lines[len(lines)-1]+gap+part) <= room {
				lines[len(lines)-1] += gap + part
			} else {
				lines = append(lines, part)
			}
		}
		return lines
	}
	lines := []string{"why " + named(row, room-terminal.Cells("why  "+why.Does)) + " " + why.Does}
	lines = append(lines, pack([]string{why.Quality, why.Cost}, "   ")...)
	behind := []string{why.Behind}
	if why.Best != nil {
		behind = append(behind, named(why.Best, room))
	}
	lines = append(lines, pack(behind, " ")...)
	width, howWidth := 0, 0
	for _, one := range why.Measures {
		width = max(width, terminal.Cells(one.Name))
		howWidth = max(howWidth, terminal.Cells(one.How))
	}
	points := terminal.Cells(quality.Behind)
	wide := width+2+points+2+howWidth <= room
	lines = append(lines, "", s.TableRow([]string{"", quality.Behind}, []int{width, points}, []string{"", "dim"}))
	for _, one := range why.Measures {
		line := terminal.Pad(one.Name, width) + "  " + fmt.Sprintf("%*s", points, one.Points)
		if wide {
			line += "  " + one.How
		}
		lines = append(lines, strings.TrimRight(line, " "))
		if !wide {
			lines = append(lines, "  "+one.How)
		}
	}
	for i, line := range lines {
		if line != "" {
			lines[i] = "  " + line
		}
	}
	return lines
}
