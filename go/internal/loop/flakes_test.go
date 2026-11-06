package loop

import (
	"os"
	"path/filepath"
	"testing"
)

// Sightings and holds Python kept by test count with those kept by file, and those past the window
// are gone; a ledger Go cannot keep leaves the line to Python.
func TestFlakesKeptByTestCountAndALedgerGoCannotKeepIsPythons(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".merge-acme.flakes")
	write := func(text string) {
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	write(`{"seen": [{"test": "t/b.sh::y", "tree": "old", "at": 1}],
		"tests": {"t/a.sh::x": {"seen": [{"tree": "T", "at": 1e9}], "repair": {"run": "fix-a", "at": 1e9, "sha": "abc"}}}}`)
	seen, repairs, reds, carried := readFlakes(path, 1e9)
	if !carried || len(seen) != 1 || seen[0].Str("test") != "t/a.sh::x" || seen[0].Str("tree") != "T" ||
		len(repairs) != 1 || repairs[0].Str("file") != "t/a.sh" || repairs[0].Str("run") != "fix-a" || reds != nil {
		t.Fatalf("seen %v, repairs %v, reds %v, carried %v", seen, repairs, reds, carried)
	}
	write(`{"seen": [{"test": "t/a.sh::\udcff", "tree": "T", "at": 1e9}]}`)
	if _, _, _, carried := readFlakes(path, 1e9); carried {
		t.Fatal("a ledger Go cannot keep was carried, to be written over")
	}
	write("not json")
	if seen, _, _, carried := readFlakes(path, 1e9); !carried || seen != nil {
		t.Fatal("a ledger holding no JSON keeps nothing, as to Python")
	}
}
