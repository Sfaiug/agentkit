package terminal

import (
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
)

// A theme is the shades of ak's one look a terminal's background fits, a column of roles: white's
// for a light one, black's for any other, the zero Screen's.  The owner (20 Nov 2026): "the
// background of the terminal ... should be used, and ak just sits on top of that", so nothing
// chooses one.  A menu whose terminal says its background draws in the shades it fits and keeps
// them (Keyboard.Sense); whatever cannot ask, and a menu whose terminal does not answer, draws in
// the ones kept (kept).
type theme int

const (
	black theme = iota
	white
)

// keptAt is where a menu keeps the shades its terminal's background fits, as Python's
// config.STATE / themes.KEPT: `light`, else `dark`.
func keptAt() string { return filepath.Join(config.Home(), "state", "background") }

// kept is the shades the answer a menu kept last fits, as its file is now (Python's themes.fits):
// white's where it says `light`, else black's, as on a machine no menu has asked yet.  Every draw
// asks, so nothing that draws for hours, a seat's bar among them, keeps an answer kept before.
func kept() theme {
	if said, err := os.ReadFile(keptAt()); err == nil && strings.TrimSpace(string(said)) == "light" {
		return white
	}
	return black
}

// keep keeps the shades a terminal's answer fits for what cannot ask (kept): moved in whole from
// a file of its own, so menus keeping theirs at once each leave a whole one.  Where it cannot,
// what cannot ask stays in the shades kept before.
func keep(fits theme) {
	at := keptAt()
	os.MkdirAll(filepath.Dir(at), 0o700) // owner-only, as Python's config.ensure_dirs makes them
	part, err := os.CreateTemp(filepath.Dir(at), ".background-")
	if err != nil {
		return
	}
	_, err = part.WriteString([]string{black: "dark\n", white: "light\n"}[fits])
	if closed := part.Close(); err != nil || closed != nil || os.Rename(part.Name(), at) != nil {
		os.Remove(part.Name())
	}
}

// roles is each role's colour in each theme, as agentkit/themes.py's ROLES: a screen asks for a
// role (styles), and tests/test_boundaries.py counts an RGB written anywhere but here.
var roles = map[string][2]string{
	"background": {white: "ffffff", black: "000000"},
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
