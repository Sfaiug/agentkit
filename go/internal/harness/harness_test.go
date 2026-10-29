package harness

import (
	"reflect"
	"testing"

	"agentkit/internal/run"
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

// Whether Python's records() writes to the record, as found against Python ak.
func TestARecordIsRewrittenWhereItsHarnessReconcileChangesIt(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	for _, each := range []struct {
		harness, record string
		rewrites        bool
	}{
		{"claude", `{}`, false}, {"claude", `{"conversation": "abc"}`, true},
		{"claude", `{"conversation": "abc", "id_source": "claude-hook"}`, false},
		{"echo", `{"conversation": "abc", "id_source": "claude-hook"}`, true},
		{"echo", `{"conversation": "abc", "id_source": "launcher"}`, false}, {"echo", `{"conversation": ""}`, false},
		{"codex", `{}`, true}, {"codex", `{"resumable": false}`, false}, {"codex", `{"resumable": 0}`, false},
		{"codex", `{"resumable": true}`, true},
	} {
		value, err := run.Decode([]byte(each.record))
		if err != nil {
			t.Fatal(err)
		}
		if got := Rewrites(each.harness, value.(*run.Object)); got != each.rewrites {
			t.Errorf("Rewrites(%s, %s) = %v", each.harness, each.record, got)
		}
	}
}
