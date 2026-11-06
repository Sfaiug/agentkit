package commandhelp

import (
	"slices"
	"testing"
)

// Each want is what Python's shlex.split reads, nil where it refuses the line.
func TestShellSplit(t *testing.T) {
	for line, want := range map[string][]string{
		"a  b\tc\n": {"a", "b", "c"}, `"a\"b\\c\$d"`: {`a"b\c\$d`}, `\x\ y`: {"x y"}, `'' ""`: {"", ""},
		`a"b c"d`: {"ab cd"}, `'it'"'"'s'`: {"it's"}, "it's": nil, `x\`: nil, "": {},
	} {
		if got, ok := ShellSplit(line); ok != (want != nil) || ok && !slices.Equal(got, want) {
			t.Errorf("ShellSplit(%q) = %q, %v, want %q", line, got, ok, want)
		}
	}
}

// Each want is the word Python's shlex reads first and where its stream then stands, its error
// as false.
func TestShellWord(t *testing.T) {
	type read struct {
		word string
		took int
		ok   bool
	}
	for text, want := range map[string]read{
		`'/a b'\''s c' don't`: {"/a b's c", 14, true}, `/a\ b"c d"e  f`: {"/a bc de", 12, true},
		"/a\tb": {"/a", 3, true}, "/a": {"/a", 2, true}, " \t": {"", 0, true}, `'/a b`: {"/a b", 5, false},
	} {
		if word, took, ok := ShellWord(text); (read{word, took, ok}) != want {
			t.Errorf("ShellWord(%q) = %q, %d, %v, want %v", text, word, took, ok, want)
		}
	}
}
