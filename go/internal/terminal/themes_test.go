package terminal

import (
	"os"
	"path/filepath"
	"testing"
)

// What cannot ask is in the shades the last answer kept fits, as Python's themes.fits reads the
// same file: white's only where it says `light`, black's for any other word or none.
func TestWhatCannotAskTakesTheShadesTheLastAnswerFits(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if kept() != black || RGB("accent") != roles["accent"][black] {
		t.Fatal("nothing kept is not black's")
	}
	keep(white) // a Home with no state yet: keep makes it
	if said, _ := os.ReadFile(keptAt()); string(said) != "light\n" || kept() != white || RGBs("accent", "dim")[1] != roles["dim"][white] {
		t.Fatalf("a light answer kept %q", said)
	}
	keep(black)
	if said, _ := os.ReadFile(keptAt()); string(said) != "dark\n" || kept() != black {
		t.Fatalf("a dark answer kept %q", said)
	}
	for said, want := range map[string]theme{" light \n": white, "Light\n": black, "white\n": black} {
		if err := os.WriteFile(keptAt(), []byte(said), 0o644); err != nil {
			t.Fatal(err)
		}
		if kept() != want {
			t.Errorf("%q fits %v", said, kept())
		}
	}
	if left, _ := filepath.Glob(filepath.Join(home, ".agentkit", "state", ".background-*")); len(left) != 0 {
		t.Errorf("a keep left %v", left)
	}
}
