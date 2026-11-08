//go:build linux

package launch

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/job"
	"agentkit/internal/run"
)

// A seat's job told --bg names itself and its receipt at once, its launcher apart adopting the
// receipt that holds its pid: each task is a run of the seat's own, driven in a process carrying the
// job's directory, and once every task delivered the job's line is typed at the seat's quiet prompt
// once, its receipt saying so with nothing left pending.
func TestASeatsBackgroundJobHandsItsLineBackOnce(t *testing.T) {
	home := queuedHome(t)
	t.Setenv("AK_MAX_RUNS", "0") // a job a gate decides is Python's
	t.Setenv("AK_TEST_DONE", "1")
	t.Setenv("AGENTKIT_SESSION", "acme")
	write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"), `{"orchestrator": "opus", "workers": ["opus"], `+
		`"cwd": "`+home+`", "created": 1799000000, "conversation": "conv-acme", "id_source": "launcher", "resumable": true}`)
	quiet(t, home)
	var paths []string
	for _, name := range []string{"api", "db"} {
		path := filepath.Join(home, "tasks", "fix-"+name+".md")
		write(t, path, "---\nrepo: none\n---\n# Fix the "+name+"\n\n## Done when\n```bash\ntrue\n```\n")
		paths = append(paths, path)
	}

	var out bytes.Buffer
	code, why, err := Job(paths, map[string]string{}, map[string]bool{"--bg": true}, &out)
	entries, _ := os.ReadDir(job.Jobs())
	if code != 0 || why != "" || err != nil || len(entries) != 1 {
		t.Fatalf("launched (%d, %q, %v), %d jobs", code, why, err, len(entries))
	}
	id := entries[0].Name()
	dir := filepath.Join(job.Jobs(), id)
	receipt, _ := job.Read(dir)
	pid, _ := receipt.Int("pid")
	t.Cleanup(func() { gone(t, pid) })
	if out.String() != id+"\n"+job.ReceiptPath(id)+"\n" || receipt.Str("seat") != "acme" || pid == os.Getpid() {
		t.Fatalf("said %q; the receipt: %s", out.String(), run.Line(receipt))
	}

	for deadline := time.Now().Add(60 * time.Second); !receipt.Truthy("card_sent"); time.Sleep(50 * time.Millisecond) {
		if time.Now().After(deadline) {
			logged, _ := os.ReadFile(filepath.Join(dir, "log.txt"))
			t.Fatalf("never handed back: %s\n%s", run.Line(receipt), logged)
		}
		receipt, _ = job.Read(dir)
	}
	gone(t, pid)
	line := "job " + id + ": all 2 tasks finished. Result: " + filepath.Join(dir, "log.txt") + ". Decide the next step."
	if typed, _ := os.ReadFile(filepath.Join(home, "typed")); strings.Count(string(typed), line) != 1 {
		t.Fatalf("typed %q", typed)
	}
	if receipt.Dict("card_sent").Str("kind") != "handback" || receipt.Has("handback_pending") || !receipt.Truthy("finished_at") {
		t.Fatalf("the receipt: %s", run.Line(receipt))
	}
	for _, each := range receipt.List("tasks") {
		task := each.(*run.Object)
		runDir := filepath.Join(run.Runs(), task.Str("run_id"))
		record, _ := run.Read(runDir)
		under, _ := os.ReadFile(filepath.Join(runDir, "done-under"))
		if task.Str("state") != "passed" || record == nil || run.Seat(record) != "acme" || record.Str("job_id") != id ||
			string(under) != dir+"\n"+"acme" {
			t.Fatalf("%s: %s, its run %s, driven under %q", task.Str("name"), run.Line(task), run.Line(record), under)
		}
	}
}

// quiet is the seat acme on ak's own server sitting at its quiet prompt, its tmux a fake that
// keeps in HOME/typed each line typed into it, which an Enter sends.
func quiet(t *testing.T, home string) {
	const prompt = "────────\n❯\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
	write(t, filepath.Join(home, "prompt"), prompt)
	write(t, filepath.Join(home, "shown"), prompt)
	bin := filepath.Join(home, "bin")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *"-t =acme: #{pane_id}"*|*"-t %1 #{pane_id}"*) printf '%%1\t1000\t4242\n' ;;
  *send-keys*)
    for last do :; done
    if [ "$last" = Enter ]; then cp "$HOME/prompt" "$HOME/shown"
    else printf '%s\n' "$last" >> "$HOME/typed"
      printf '────────\n❯ %s\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n' "$last" > "$HOME/shown"; fi ;;
esac
`)
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
}

// done is a driver finding its task done already, saying the job and seat its process runs under.
func done(dir string) int {
	os.WriteFile(filepath.Join(dir, "done-under"), []byte(os.Getenv("AGENTKIT_JOB_DIR")+"\n"+os.Getenv("AGENTKIT_SESSION")), 0o600)
	if err := run.Change(dir, func(record *run.Object) error {
		run.SetAll(record, "state", "not_needed", "finished_at", run.Float(float64(time.Now().UnixNano())/1e9))
		return nil
	}); err != nil {
		return 2
	}
	return 0
}

// gone waits for that process to end.
func gone(t *testing.T, pid int) {
	for deadline := time.Now().Add(30 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
		if stat, known := host.ReadStat(pid); !known || stat.Exited() {
			return
		}
	}
	t.Errorf("process %d did not end", pid)
}
