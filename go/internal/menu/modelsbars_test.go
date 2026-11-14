package menu

import (
	"slices"
	"testing"
)

func TestABarsNameWrapsOntoThreeLinesItsWordsCut(t *testing.T) {
	for _, case_ := range []struct {
		name string
		room int
		want []string
	}{
		{"Acme Long Name 1", 6, []string{"Acme", "Long", "Name 1"}},
		{"Acme Superintelligence 1", 6, []string{"Acme", "Super…", "1"}},
		// a third line with more to follow ends after its last whole word
		{"Acme Long Preview With Reasoning Support 1", 12, []string{"Acme Long", "Preview With", "Reasoning…"}},
	} {
		if got := barLines(case_.name, case_.room); !slices.Equal(got, case_.want) {
			t.Errorf("%q on %d cells: %q, want %q", case_.name, case_.room, got, case_.want)
		}
	}
}
