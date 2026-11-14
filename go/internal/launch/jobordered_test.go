//go:build linux

package launch

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// An ordered job's task is judged on origin's tip, fetched at its start, where the one before it
// merged: a round budget or executors off that only origin's tip holds settle it there, before
// any run is made.
func TestAnOrderedTaskIsJudgedOnOriginsTip(t *testing.T) {
	for _, each := range []struct{ policy, settled, line string }{
		{"review_rounds: 1", "blocked", "b.md: BLOCKED: " + task.RoundsOver("3", "task rounds", 1)},
		{"executor_lines: 0", "failed", "b.md: FAIL: needs you (executor_lines = 0: " + config.ExecutorsOff + ")"},
	} {
		t.Run(each.policy, func(t *testing.T) {
			home := jobHome(t)
			repo, origin, peer := filepath.Join(home, "widget"), filepath.Join(home, "origin.git"), filepath.Join(home, "peer")
			git := func(args ...string) {
				t.Helper()
				if said, err := exec.Command("git", append([]string{"-c", "user.name=Acme", "-c", "user.email=acme@example.invalid"}, args...)...).CombinedOutput(); err != nil {
					t.Fatalf("git %v: %v: %s", args, err, said)
				}
			}
			write(t, filepath.Join(repo, "AGENTS.md"), "---\nusers: none\ntests: none\nhealth: none\n---\n")
			git("init", "--bare", "--initial-branch=main", origin)
			git("init", "--initial-branch=main", repo)
			git("-C", repo, "add", "AGENTS.md")
			git("-C", repo, "commit", "-m", "The contract")
			git("-C", repo, "remote", "add", "origin", origin)
			git("-C", repo, "push", "origin", "main")
			git("-C", repo, "remote", "set-head", "origin", "--auto")
			// the one before it merged on origin, which this checkout has not fetched
			git("clone", origin, peer)
			write(t, filepath.Join(peer, "AGENTS.md"), "---\nusers: none\ntests: none\nhealth: none\n"+each.policy+"\n---\n")
			git("-C", peer, "commit", "-am", "The policy")
			git("-C", peer, "push", "origin", "main")

			j := createdJob(t, "a.md", "b.md")
			j.flags["--in-order"] = true
			b := j.receipt.List("tasks")[1].(*run.Object)
			write(t, b.Str("task_file"), "---\nrepo: "+repo+"\nrounds: 3\n---\n# Add b\n\n## Done when\n```bash\ntrue\n```\n")
			if begun, err := j.begin(b, make(chan ending)); begun || err != nil {
				t.Fatalf("began %v: %v", begun, err)
			}
			if made, _ := os.ReadDir(run.Runs()); b.Str("state") != each.settled || b.Str("verdict_line") != each.line || len(made) > 0 {
				t.Fatalf("b settled %s (%s), making %v", b.Str("state"), b.Str("verdict_line"), made)
			}
		})
	}
}
