package handback

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A job's task ending with its seat gone, in a process its job started, is only marked reported,
// its job's one line saying it; in a process of another job's, or of none, it is left as it stands.
func TestAJobsTaskWhoseSeatIsGoneIsLeftToItsJobsLine(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("AGENTKIT_SESSION", "")
	bin := filepath.Join(home, "bin")
	if err := os.MkdirAll(bin, 0o700); err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(bin, "tmux"), []byte("#!/bin/sh\nexit 1\n"), 0o700) // no seat on any server
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	dir, jobs := filepath.Join(home, ".agentkit", "runs", "fix-api"), filepath.Join(home, ".agentkit", "jobs")
	ending := run.Fields("state", "fail", "launched_session", "acme", "job_id", "20261108-090000-fix-api",
		"handback_pending", true, "finished_at", run.Float(seconds()))
	if err := os.MkdirAll(dir, 0o700); err != nil || run.Create(dir, ending) != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(filepath.Join(dir, "run.json"))
	for _, started := range []string{"", filepath.Join(jobs, "20261108-090000-fix-db")} {
		t.Setenv("AGENTKIT_JOB_DIR", started)
		if after, _ := os.ReadFile(filepath.Join(dir, "run.json")); Give(dir, nil, func(string) {}) || string(after) != string(before) {
			t.Fatalf("under %q: %s", started, after)
		}
	}
	t.Setenv("AGENTKIT_JOB_DIR", filepath.Join(jobs, "20261108-090000-fix-api"))
	if Give(dir, nil, func(string) {}) {
		t.Fatal("told a seat that is gone")
	}
	if after, _ := run.Read(dir); !after.Truthy("reported") || after.Has("handback_pending") || after.Truthy("handed_back") {
		t.Fatalf("the record: %s", run.Line(after))
	}
}
