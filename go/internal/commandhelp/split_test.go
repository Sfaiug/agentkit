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
