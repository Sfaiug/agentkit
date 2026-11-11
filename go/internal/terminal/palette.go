package terminal

// A colour is one of the owner's palette (10 Nov 2026), with the text that reads on it.
type colour struct{ rgb, ink string }

// palette is every colour ak draws, the eight and the grey kept from before, as
// agentkit/palette.py's PALETTE; text of no colour is the terminal's own.  A role names a
// colour of it (styles), and tests/test_boundaries.py counts an RGB written anywhere but
// here, so the next palette is this table.
var palette = map[string]colour{
	"blue":   {"0067c6", "ffffff"},
	"red":    {"be222a", "ffffff"},
	"orange": {"de6800", "2e1500"},
	"yellow": {"f6c400", "3d2e00"},
	"green":  {"007e46", "ffffff"},
	"teal":   {"007974", "ffffff"},
	"purple": {"7c44c3", "ffffff"},
	"pink":   {"ad326e", "ffffff"},
	"grey":   {"6c7086", "ffffff"},
}
