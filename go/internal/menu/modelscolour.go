package menu

import "agentkit/internal/terminal"

// ModelLight lights every row of one maker once navigation points at it.
type ModelLight struct{ Maker, Colour string }

func modelPaint(s terminal.Screen, row Line, name string, light ModelLight) (string, string) {
	if light.Maker != "" && light.Colour != "" && row.Maker == light.Maker {
		return s.Tinted(name, light.Colour, -0.25), light.Colour
	}
	return name, "quiet"
}
