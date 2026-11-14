package terminal

import (
	"slices"

	"agentkit/internal/config"
)

// A theme is the owner's white or black (12 Nov 2026): every colour ak draws is a role of one.
// The one in force is the one config.toml names (inForce), else white where the terminal's
// background is light (Keyboard.Sense), black everywhere else, the zero Screen's.
type theme int

const (
	black theme = iota
	white
)

// Themes is each theme's name, as config.toml and `c` say it (Python's themes.NAMES), in its place.
var Themes = []string{black: "black", white: "white"}

// inForce is the theme a screen draws in as it draws: the one config.toml names (config.Theme),
// else `fits`, the one its terminal fits.
func inForce(fits theme) theme {
	if named := slices.Index(Themes, config.Theme()); named >= 0 {
		return theme(named)
	}
	return fits
}

// Theme is the name of the theme the screen draws in.
func (s Screen) Theme() string { return Themes[s.theme] }

// roles is each role's colour in each theme, as agentkit/themes.py's ROLES.  A screen asks for a
// role (styles), and tests/test_boundaries.py counts an RGB written anywhere but here, so the next
// theme is a column of this table.
var roles = map[string][2]string{
	"background": {white: "ffffff", black: "000000"},
	"surface":    {white: "f4f6fa", black: "111519"},
	"selection":  {white: "dcecff", black: "08305d"},
	"border":     {white: "b1b8c0", black: "3a3f46"},
	"text":       {white: "181c22", black: "e2e8ef"},
	"muted":      {white: "535962", black: "acb4bd"},
	"dim":        {white: "6f757e", black: "868d97"},
	"accent":     {white: "0067c6", black: "4da3ff"},
	"success":    {white: "007935", black: "33b65f"},
	"warning":    {white: "8e5e00", black: "d79200"},
	"error":      {white: "c52a2f", black: "fe756f"},
	"info":       {white: "00747d", black: "00b0bf"},
	"special":    {white: "a23baa", black: "da7de0"},
	"on-accent":  {white: "ffffff", black: "000000"},
}
