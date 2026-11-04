package seat

import (
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestStopCardUsesStopsAdmissionWithoutWriting(t *testing.T) {
	for _, test := range []struct {
		name, file, data string
		count            int
		known            bool
	}{
		{"no runs", "", "", 0, true},
		{"one going", "runs/api/run.json", `{"state":"running","launched_session":"acme"}`, 1, true},
		{"finished", "runs/api/run.json", `{"state":"pass","launched_session":"acme"}`, 0, true},
		{"another seat", "runs/api/run.json", `{"state":"running","launched_session":"beta","pid":4242}`, 0, true},
		{"checkout", "runs/api/run.json", `{"state":"pass","launched_session":"acme","worktree":"/wt/api"}`, 0, false},
		{"process", "runs/api/run.json", `{"state":"running","launched_session":"acme","pid":4242}`, 0, false},
		{"tab", "state/browser-tabs.json", `{"T1":{"opener":{"session":"acme"}}}`, 0, false},
		{"unread", "state/notify-acme.json", `{"kind":"needs","text":"Which branch?"}`, 0, false},
		{"sent card", "state/card-acme.json", `{"sent":true}`, 0, false},
		{"record", "state/session-acme.json", `{"unknown":true}`, 0, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			home := sandbox(t)
			t.Setenv("AGENTKIT_SESSION", "acme")
			record(t, home, "acme", nil)
			if test.file != "" {
				write(t, filepath.Join(home, ".agentkit", test.file), test.data)
			}
			snapshot := func() map[string]string {
				files := map[string]string{}
				if err := filepath.WalkDir(home, func(path string, entry fs.DirEntry, err error) error {
					if err == nil && !entry.IsDir() {
						files[path] = contents(t, path)
					}
					return err
				}); err != nil {
					t.Fatal(err)
				}
				return files
			}
			before := snapshot()
			if count, known := StopCount("acme", moment); count != test.count || known != test.known {
				t.Fatalf("count=%d known=%v", count, known)
			}
			if !reflect.DeepEqual(before, snapshot()) {
				t.Fatal("offering the card changed HOME")
			}
			if _, known, err := Stop("acme", moment); known != test.known || err != nil {
				t.Fatalf("stop's admission differs: known=%v err=%v", known, err)
			}
		})
	}
}

func TestStopCardIsOnlyForItsOwnSeat(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	for _, caller := range []string{"", "beta"} {
		t.Setenv("AGENTKIT_SESSION", caller)
		if _, known := StopCount("acme", moment); known {
			t.Fatalf("offered to %q", caller)
		}
	}
	if _, err := os.Stat(filepath.Join(home, ".agentkit", "state", "seat-acme.json")); !os.IsNotExist(err) {
		t.Fatalf("wrote a stop mark: %v", err)
	}
}
