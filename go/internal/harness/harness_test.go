package harness

import (
	"reflect"
	"testing"
)

// The words and quoting Python's shlex gives, as Python ak reads and prints a seat's command.
func TestCommandLinesReadAndPrintAsPythonDoes(t *testing.T) {
	for line, words := range map[string][]string{
		`a b`: {"a", "b"}, `"a\"b\$c" 'x y'`: {`a"b\$c`, "x y"}, `a\ b ""`: {"a b", ""},
		`env X=1 '{"k":1}'`: {"env", "X=1", `{"k":1}`},
	} {
		if got, err := split(line); err != nil || !reflect.DeepEqual(got, words) {
			t.Errorf("split(%q) = %q, %v", line, got, err)
		}
	}
	for _, line := range []string{`'open`, `trailing\`} {
		if _, err := split(line); err == nil {
			t.Errorf("split(%q) read a line a shell cannot", line)
		}
	}
	if got := Join([]string{"", "a/b-c.d", "it's", `{"k":1}`, "é"}); got != `'' a/b-c.d 'it'"'"'s' '{"k":1}' 'é'` {
		t.Errorf("Join = %s", got)
	}
}
