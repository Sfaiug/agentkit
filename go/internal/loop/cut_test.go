package loop

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// What a model is handed of output is at most the bound in bytes and starts at a whole character,
// as Python's turns.cut_file hands it: output that fits only before replacement characters grow it
// is named whole in a file too.
func TestOutputIsCutWithinTheBoundAtAWholeCharacter(t *testing.T) {
	for printed, want := range map[string]string{"a€": "a€", "x€€": "€", "a\xffb\xffc": "b�c"} {
		dir := t.TempDir()
		path := filepath.Join(dir, "donewhen.log")
		if err := os.WriteFile(path, []byte(printed), 0o666); err != nil {
			t.Fatal(err)
		}
		file, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		said, err := cutFrom(file, 0, dir, "donewhen", 5)
		file.Close()
		if err != nil {
			t.Fatal(err)
		}
		line, shown, _ := strings.Cut(said, "\n")
		kept, _ := os.ReadFile(strings.TrimSuffix(strings.TrimPrefix(line, "[only part of this output is shown; all of it is in "), "]"))
		if want == printed && said != printed || want != printed && (shown != want || string(kept) != printed) {
			t.Errorf("%q was handed on as %q", printed, said)
		}
	}
}
