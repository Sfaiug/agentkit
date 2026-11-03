package loop

import (
	"testing"

	"agentkit/internal/run"
)

func TestAFailureIsItsCommandAndTheLastThingItSaid(t *testing.T) {
	text := "Commit: abc\nTree: def\n\n$ good\n[exit 0]\nfine\n\n$ bad\n[exit 1]\nrun 7 at /tmp/x\n\nretry.txt is missing\n\nflaky: other failed, then passed on its re-run\n\n$ hung\n[killed at the limit]\n\ndone-when: stopped after 20 min of silence: hung (last output: (no output))\n\nCheckout changed during done-when; these commands do not verify the pinned commit."
	got := failingChecks(text)
	want := []any{[]any{"bad", "retry.txt is missing"}, []any{"hung", ""}}
	if !run.Equal(any(got), any(want)) {
		t.Fatalf("got %v", got)
	}
	if line := checkLine(got[0]); line != "`bad` — retry.txt is missing" {
		t.Fatalf("got %q", line)
	}
	if line := checkLine(got[1]); line != "`hung`" {
		t.Fatalf("got %q", line)
	}
}

func TestOnlyARecordCountsAndRecordsThatDisagreeFail(t *testing.T) {
	for _, each := range []struct {
		text          string
		cmds          []string
		passed, total int
	}{
		{"$ a\n[exit 0]\n\n$ b\n[exit 1]", []string{"a", "b"}, 1, 2},
		{"$ a\n[exit 0]\nsaid\n\n$ a\n[exit 1]", []string{"a"}, 0, 1},
		{"$ a\n[exit 0]\n\n$ a\n[exit 0]", []string{"a"}, 1, 1},
		{"$ a\n[not run: the done-when limit was already spent]", []string{"a", "b"}, 0, 1},
		{"$ a\n[exit 0]", []string{"a", "a"}, 1, 1},
	} {
		if passed, total := doneWhenCounts(each.text, each.cmds); passed != each.passed || total != each.total {
			t.Errorf("%q: %d of %d", each.text, passed, total)
		}
	}
}

// Each ratio is what Python's difflib.SequenceMatcher(None, a, b).ratio() says.
func TestLinesAreAsAlikeAsDifflibSays(t *testing.T) {
	long := ""
	for len(long) < 300 {
		long += "abcabd "
	}
	for _, each := range []struct {
		a, b string
		want float64
	}{
		{"", "", 1.0},
		{"abc", "", 0.0},
		{"abcd", "bcde", 0.75},
		{"return None", "return value", 0.6956521739130435},
		{"    if x > 1:", "    if x >= 2:", 0.8888888888888888},
		{"héllo wörld", "hello world", 0.8181818181818182},
		{"abab", "baba", 0.75},
		{"qabxcd", "abycdf", 0.6666666666666666},
		{long, long[1:] + "x", 0.0},
		{"abc" + long, long, 0.01652892561983471},
	} {
		if got := similarity(each.a, each.b); got != each.want {
			t.Errorf("%q, %q: %v, want %v", each.a, each.b, got, each.want)
		}
	}
}
