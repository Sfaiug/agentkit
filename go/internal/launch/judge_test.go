//go:build linux

package launch

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A launch waiting in this process `from:` a branch deleted since is refused on a new version, but
// a run resumed into the line is not: its own checkout carries it on, as Python's resume_run judges
// only a launch that never started.
func TestJudgeRefusesOnlyALaunchThatNeverStarted(t *testing.T) {
	home := gatedHome(t, "dry-run")
	repo, wt := filepath.Join(home, "acme"), filepath.Join(home, "acme-work")
	for _, args := range [][]string{
		{"init", "--quiet", "--initial-branch=main", repo},
		{"-C", repo, "-c", "user.name=Acme", "-c", "user.email=acme@example.invalid", "commit", "--quiet", "--allow-empty", "-m", "Initial"},
		{"-C", repo, "branch", "fix-api"},
		{"-C", repo, "worktree", "add", "--quiet", "-b", "ak/fix-api", wt, "fix-api"},
		{"-C", repo, "branch", "--quiet", "-D", "fix-api"},
	} {
		if out, err := exec.Command("git", args...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	for _, started := range []bool{false, true} {
		id := map[bool]string{false: "fix-api", true: "fix-api-resumed"}[started]
		dir := filepath.Join(run.Runs(), id)
		waiter(t, id, time.Hour, os.Getpid(), repo)
		write(t, filepath.Join(dir, "task.md"), "---\nrepo: "+repo+"\nfrom: fix-api\n---\n# Fix the API\n\n## Done when\n```bash\ntrue\n```\n")
		if err := run.Change(dir, func(record *run.Object) error {
			record.Set("judged_on", "aaa1111")
			if started {
				run.SetAll(record, "worktree", wt, "branch", "ak/fix-api", "resume_from", "interrupted")
			}
			return nil
		}); err != nil {
			t.Fatal(err)
		}
		err := judge(dir, "bbb2222")
		if refused := err != nil && strings.HasSuffix(err.Error(), ": from: 'fix-api' is not a local branch"); refused == started {
			t.Errorf("started %v: judged %v", started, err)
		}
	}
}
