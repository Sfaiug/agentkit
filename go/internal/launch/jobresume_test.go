package launch

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
)

// A job that would start or adopt a run, wait, or hand its line to a seat that is not there, is
// Python's to resume, its receipt untouched.
func TestOnlyAJobThatEndsAtOnceIsResumedHere(t *testing.T) {
	legacy := `{"name": "fix-api.md", "state": "queued", "after": ["fix-db.md"]`
	for name, receipt := range map[string]string{
		"a task to start":       `{"job_id": "j", "tasks": [{"name": "fix-api.md", "state": "queued"}]}`,
		"a task running":        `{"job_id": "j", "tasks": [{"name": "fix-api.md", "state": "running", "after": ["fix-db.md"]}]}`,
		"a run kept":            `{"job_id": "j", "tasks": [` + legacy + `, "run_id": "20261028-1200-fix-api"}]}`,
		"a wait to sit out":     `{"job_id": "j", "tasks": [` + legacy + `, "retry_after": 99999999999}]}`,
		"a task with no state":  `{"job_id": "j", "tasks": [{"name": "fix-api.md", "after": ["fix-db.md"]}]}`,
		"every task done":       `{"job_id": "j", "tasks": [{"name": "fix-api.md", "state": "merged"}]}`,
		"finished before":       `{"job_id": "j", "finished_at": 1, "tasks": [` + legacy + `}]}`,
		"a seat nobody is in":   `{"job_id": "j", "seat": "acme", "tasks": [` + legacy + `}]}`,
		"an after that is text": `{"job_id": "j", "tasks": [{"name": "fix-api.md", "state": "queued", "after": "fix-db.md"}]}`,
	} {
		t.Run(name, func(t *testing.T) {
			home := t.TempDir()
			t.Setenv("HOME", home)
			t.Setenv("USERPROFILE", home)
			t.Setenv("TMUX_TMPDIR", t.TempDir())
			path := filepath.Join(home, ".agentkit", "jobs", "j", "job.json")
			if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte(receipt), 0o666); err != nil {
				t.Fatal(err)
			}
			if _, err := ResumeJob("j", io.Discard); !errors.Is(err, ErrPython) {
				t.Fatalf("resumed it: %v", err)
			}
			if kept, _ := os.ReadFile(path); string(kept) != receipt {
				t.Fatalf("the receipt reads %s", kept)
			}
		})
	}
}
