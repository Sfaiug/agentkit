package menu

import (
	"strings"

	"agentkit/internal/terminal"
)

// ModelLight lights every row of one maker once navigation points at it.
type ModelLight struct{ Maker, Colour string }

func modelPaint(s terminal.Screen, row Line, name string, light ModelLight) (string, string) {
	if light.Maker != "" && light.Colour != "" && row.Maker == light.Maker {
		word := strings.TrimRight(name, " ")
		return s.Tinted(word, light.Colour, -0.25) + name[len(word):], light.Colour
	}
	return name, "quiet"
}
