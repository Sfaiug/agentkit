package adapters

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

// Leading `env` words set and unset what runs, as env(1) does; the first other word runs.
func TestEnvWordsAreAppliedBeforeTheProgram(t *testing.T) {
	words, env := environ([]string{"env", "-u", "GONE", "A=2", "env", "B=", "acme", "C=3"},
		[]string{"A=1", "GONE=x", "KEPT=y"})
	if !slices.Equal(words, []string{"acme", "C=3"}) || !slices.Equal(env, []string{"KEPT=y", "A=2", "B="}) {
		t.Fatalf("%q %q", words, env)
	}
}

// final.md and session_id are what the Python adapters' jq leaves: the last result's text and
// the last session id named, "" for null or false, a value that is no string as jq prints JSON,
// and both files empty where jq fails.
func TestSummarizeReadsTheEventsAsJqDoes(t *testing.T) {
	for _, each := range []struct{ events, final, session string }{
		{`{"session_id":"a"} null {"type":"result","result":"one"}` + "\n" +
			`{"type":"result","result":"two\nlines","session_id":"b"}`, "two\nlines\n", "b\n"},
		{`{"type":"result","result":false,"session_id":false}`, "\n", "\n"},
		{`{"type":"result","result":{"a":"<b>"}}`, "{\n  \"a\": \"<b>\"\n}\n", "\n"},
		{"", "\n", "\n"},
		{`{"type":"result","result":"x"} {"cut`, "", ""},
		{`{"type":"result","result":"x"} 7`, "", ""},
	} {
		out := t.TempDir()
		os.WriteFile(filepath.Join(out, "events.jsonl"), []byte(each.events), 0o600)
		summarize(out)
		final, _ := os.ReadFile(filepath.Join(out, "final.md"))
		session, _ := os.ReadFile(filepath.Join(out, "session_id"))
		if string(final) != each.final || string(session) != each.session {
			t.Errorf("%q: final %q, session %q", each.events, final, session)
		}
	}
}

// A login's settings already the usual file, through whatever links, are left as they are;
// any other gives way to a link to the usual file.
func TestLinkKeepsSettingsThatAreTheUsualFile(t *testing.T) {
	dir := t.TempDir()
	usual, own, other := filepath.Join(dir, "usual"), filepath.Join(dir, "own"), filepath.Join(dir, "other")
	os.Symlink(own, usual) // the usual file leads to own's, not there yet
	if err := link(usual, own, false); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(own); err == nil {
		t.Fatal("own was made")
	}
	os.Remove(usual)
	os.WriteFile(other, []byte("mine"), 0o600)
	if err := link(usual, other, false); err != nil {
		t.Fatal(err)
	}
	if target, err := os.Readlink(other); err != nil || target != usual {
		t.Fatalf("other leads to %q, %v", target, err)
	}
}
