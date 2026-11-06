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
	for printed, want := range map[string]string{"a€": "a€", "x€€": "€", "a\xffb\xffc": "b�c", "a\xff\xffz": "�z"} {
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

// Bytes reach a model as Python's errors="replace" decodes them: one replacement character for each
// bad byte and each character cut short, never one for a run of them.
func TestBytesDecodeAsPythonReplacesThem(t *testing.T) {
	for raw, want := range map[string]string{"\xfc\xf6\xe4.txt": "���.txt", "\xe2\x82A": "�A", "\xed\xa0\x80": "���", "a€": "a€"} {
		if got := decoded([]byte(raw)); got != want {
			t.Errorf("%q was decoded as %q, Python's as %q", raw, got, want)
		}
	}
}
