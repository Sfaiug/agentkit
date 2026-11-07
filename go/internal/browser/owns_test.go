package browser

import (
	"os"
	"path/filepath"
	"testing"
)

// The tab records say nothing of any seat until a tab names who opened it: those tabs are the
// seat's or the run's to close with it.
func TestTabRecordsAreTheBrowsersUntilATabNamesItsOpener(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	state := filepath.Join(home, ".agentkit", "state")
	if err := os.MkdirAll(state, 0o700); err != nil {
		t.Fatal(err)
	}
	for _, each := range []struct {
		records string
		owns    bool
	}{
		{`{}`, true},
		{`{"T1": {"url": "https://acme.test", "title": "Acme", "first_seen": 1, "last_change": 1}}`, true},
		{`{"T1": {"url": "https://acme.test"}, "T2": {"opener": {"session": "acme"}}}`, false},
		{`{"T1": {"opener": {"run": "fix-api"}}}`, false},
		{`{"T1": "unreadable"}`, false},
		{`[]`, false},
		{`{`, false},
	} {
		if err := os.WriteFile(filepath.Join(state, "browser-tabs.json"), []byte(each.records), 0o600); err != nil {
			t.Fatal(err)
		}
		if Owns("browser-tabs.json") != each.owns {
			t.Errorf("%s: owned %v", each.records, !each.owns)
		}
	}
	if !Owns("browser-tabs.tmp") || Owns("session-acme.json") {
		t.Error("the write the records go through is the browser's, a seat's record is not")
	}
}
