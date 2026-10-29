package host

import (
	"strings"
	"testing"
)

// What a pane runs, as Python ak's `orch.program` reads the same command lines.
func TestProgramReadsAnInterpretersScript(t *testing.T) {
	for line, want := range map[string]string{
		"/usr/bin/claude --x": "claude", "bash -e /opt/bin/claude": "claude", "bash -c claude": "bash",
		"python3 -O /opt/bin/claude": "claude", "python3 -W ignore x/codex.py": "codex.py",
		"node --require a /n/bin/codex": "codex", "node --eval x": "node", "sh -- /x/grok": "grok",
		"sh -": "sh", "sh -o pipefail /x/agy": "agy", "sleep 600": "sleep",
	} {
		if got := Program(strings.Fields(line)); got != want {
			t.Errorf("Program(%q) = %q, want %q", line, got, want)
		}
	}
	if got := Program([]string{"sh", "", "/x/claude"}); got != "claude" {
		t.Errorf("an empty word is no script: %q", got)
	}
}

// Each answer is Python's fnmatch.fnmatchcase(name, pattern).
func TestPatternsMatchAsPythonsFnmatchDoes(t *testing.T) {
	for _, each := range []struct {
		pattern, name string
		matches       bool
	}{
		{"echo-[!0-9]*", "echo-seat", true}, {"echo-[!0-9]*", "echo-1", false}, {"claude*", "claude-code", true},
		{"c?dex", "codex", true}, {"[", "[", true}, {"a[", "a[", true}, {"[]]", "]", true}, {"[!]]", "a", true},
		{"[!]]", "]", false}, {"[a-c]x", "bx", true}, {"[c-a]x", "bx", false}, {"[z-a]", "z", false},
		{"[!z-a]", "q", true}, {"[a-]", "-", true}, {"[-a]", "-", true}, {"[a-c-e]", "d", false},
		{"[a-c-e]", "-", true}, {"x.y", "xzy", false}, {"[^a]", "^", true}, {`[\]`, `\`, true},
		{"a*b", "a\nb", true}, {"[!a-c]", "b", false}, {"[!a-c]", "d", true}, {"é?", "éa", true},
		{"[a--]", "-", false}, {"[a--]", "a", false}, {"[&&]", "&", true},
	} {
		if got := Match(each.pattern, each.name); got != each.matches {
			t.Errorf("Match(%q, %q) = %v", each.pattern, each.name, got)
		}
	}
}
