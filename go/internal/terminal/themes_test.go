package terminal

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

// What cannot ask is in the shades the last answer kept fits, as Python's themes.fits reads the
// same file: white's only where its first word is `light`, black's for any other word or none.
// Ctrl-b m asks the look on the colour kept after the word, where the look reads there.
func TestWhatCannotAskTakesTheShadesTheLastAnswerFits(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if kept() != black || RGB("accent") != roles["accent"][black] {
		t.Fatal("nothing kept is not black's")
	}
	keep(white, "ffffff") // a Home with no state yet: keep makes it
	if said, _ := os.ReadFile(keptAt()); string(said) != "light ffffff\n" || kept() != white || RGB("accent") != roles["accent"][white] ||
		RGBs("accent", "dim")[1] != roles["dim"][white] {
		t.Fatalf("a light answer kept %q", said)
	}
	keep(black, "203040")
	if said, _ := os.ReadFile(keptAt()); string(said) != "dark 203040\n" || kept() != black ||
		strings.Join(InLook("border", "dim"), " ") != "5a6f86 "+roles["dim"][black]+" 203040" {
		t.Fatalf("a dark answer kept %q: %v", said, InLook("border", "dim"))
	}
	for said, want := range map[string]theme{" light \n": white, "Light\n": black, "white\n": black, "light 808080\n": white} {
		if err := os.WriteFile(keptAt(), []byte(said), 0o644); err != nil {
			t.Fatal(err)
		}
		if kept() != want {
			t.Errorf("%q fits %v", said, kept())
		}
		if looked, asked := InLook("border", "dim"), RGBs("border", "dim"); !slices.Equal(looked, asked) {
			t.Errorf("%q: the look on no colour it reads on says %v, not %v", said, looked, asked)
		}
	}
	if left, _ := filepath.Glob(filepath.Join(home, ".agentkit", "state", ".background-*")); len(left) != 0 {
		t.Errorf("a keep left %v", left)
	}
}
