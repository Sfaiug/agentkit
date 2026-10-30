package commandhelp

import "testing"

// Each want is what Python's shlex.join writes.
func TestShellJoin(t *testing.T) {
	for want, words := range map[string][]string{
		"a": {"a"}, "''": {""}, `'it'"'"'s'`: {"it's"}, "'a b' --x=1 @%+=:,./-_Z9": {"a b", "--x=1", "@%+=:,./-_Z9"},
		"'é'": {"é"}, "'$HOME' '*'": {"$HOME", "*"},
	} {
		if got := ShellJoin(words); got != want {
			t.Errorf("ShellJoin(%q) = %s, want %s", words, got, want)
		}
	}
}
