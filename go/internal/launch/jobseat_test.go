//go:build linux

package launch

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/job"
	"agentkit/internal/run"
)

// A seat's job, foreground or told --bg, launches every task under that seat, one at a time, even
// once the seat's record is gone after its first task started.
func TestAJobsTasksStayItsSeatsOnceItsRecordIsGone(t *testing.T) {
	for _, background := range []bool{false, true} {
		t.Run(map[bool]string{false: "foreground", true: "background"}[background], func(t *testing.T) {
			home := seatJobHome(t)
			t.Setenv("AK_TEST_DROP_SEAT", "1")
			dir := ranJob(t, jobTasks(t, home), map[string]string{"--parallel": "1"}, map[string]bool{"--bg": background}, -1)
			receipt, _ := job.Read(dir)
			for _, each := range receipt.List("tasks") {
				record, _ := run.Read(filepath.Join(run.Runs(), each.(*run.Object).Str("run_id")))
				if record == nil || run.Seat(record) != "acme" || record.Truthy("unattended") {
					t.Fatalf("%s left its job's seat: %s", each.(*run.Object).Str("name"), run.Line(record))
				}
			}
		})
	}
}

// A foreground job's task whose seat is gone at its ending is left to the job's one line, its
// ending marked reported by its own driver, which carries the job's directory as a --bg job's does.
func TestAForegroundJobsTaskEndingAGoneSeatIsLeftToItsLine(t *testing.T) {
	home := seatJobHome(t)
	receipt, _ := job.Read(ranJob(t, jobTasks(t, home), map[string]string{}, map[string]bool{}, 1))
	for _, each := range receipt.List("tasks") {
		if record, _ := run.Read(filepath.Join(run.Runs(), each.(*run.Object).Str("run_id"))); record == nil || !record.Truthy("reported") {
			t.Fatalf("not left to its job's line: %s", run.Line(record))
		}
	}
}

// A job's own launcher whose receipt keeps a run, running, waiting or queued again, leaves the job
// to Python, which adopts kept runs (job_adopt_worker), its receipt as it was.
func TestAJobsOwnLauncherLeavesKeptRunsToPython(t *testing.T) {
	for _, state := range []string{"running", "waiting", "queued"} {
		t.Run(state, func(t *testing.T) {
			jobHome(t)
			j := createdJob(t, "fix-api.md", "fix-db.md")
			for _, each := range j.receipt.List("tasks") {
				run.SetAll(each.(*run.Object), "state", state, "run_id", "20261108-0900-"+each.(*run.Object).Str("title"))
			}
			if err := job.Save(j.dir, j.receipt); err != nil {
				t.Fatal(err)
			}
			t.Setenv("AGENTKIT_JOB_DIR", j.dir)
			before, _ := os.ReadFile(job.ReceiptPath(j.id()))
			code, err := ResumeJob(j.id(), io.Discard)
			if after, _ := os.ReadFile(job.ReceiptPath(j.id())); !errors.Is(err, ErrPython) || !bytes.Equal(before, after) {
				t.Fatalf("resumed (%d, %v): %s", code, err, after)
			}
		})
	}
}

// seatJobHome is a home the seat acme launches a job from, no tmux server up, each task's driver
// failing it and handing its ending back.
func seatJobHome(t *testing.T) string {
	home := queuedHome(t)
	t.Setenv("AK_MAX_RUNS", "0") // a job a gate decides is Python's
	t.Setenv("AK_TEST_DONE", "fail")
	t.Setenv("AGENTKIT_SESSION", "acme")
	write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"), `{"orchestrator": "opus", "workers": ["opus"], `+
		`"cwd": "`+home+`", "created": 1799000000, "conversation": "conv-acme", "id_source": "launcher", "resumable": true}`)
	write(t, filepath.Join(home, "bin", "tmux"), "#!/bin/sh\nexit 1\n")
	t.Setenv("PATH", filepath.Join(home, "bin")+string(os.PathListSeparator)+os.Getenv("PATH"))
	return home
}

// jobTasks are two task files in home that name no repository.
func jobTasks(t *testing.T, home string) []string {
	var paths []string
	for _, name := range []string{"api", "db"} {
		path := filepath.Join(home, "tasks", "fix-"+name+".md")
		write(t, path, "---\nrepo: none\n---\n# Fix the "+name+"\n\n## Done when\n```bash\ntrue\n```\n")
		paths = append(paths, path)
	}
	return paths
}

// ranJob launches the job and waits for it to finish, its directory; a foreground job's exit status
// is the one wanted, -1 for any.
func ranJob(t *testing.T, paths []string, values map[string]string, flags map[string]bool, want int) string {
	var out bytes.Buffer
	code, why, err := Job(paths, values, flags, &out)
	entries, _ := os.ReadDir(job.Jobs())
	if why != "" || err != nil || len(entries) != 1 || !flags["--bg"] && want >= 0 && code != want {
		t.Fatalf("launched (%d, %q, %v), %d jobs: %s", code, why, err, len(entries), &out)
	}
	dir := filepath.Join(job.Jobs(), entries[0].Name())
	receipt, _ := job.Read(dir)
	pid, _ := receipt.Int("pid")
	if flags["--bg"] {
		t.Cleanup(func() { gone(t, pid) })
	}
	for deadline := time.Now().Add(60 * time.Second); !receipt.Truthy("finished_at"); time.Sleep(50 * time.Millisecond) {
		if time.Now().After(deadline) {
			t.Fatalf("never finished: %s", run.Line(receipt))
		}
		receipt, _ = job.Read(dir)
	}
	if flags["--bg"] {
		gone(t, pid)
	}
	return dir
}
