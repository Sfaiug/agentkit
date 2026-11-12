package worker

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/helper"
	"agentkit/internal/machines"
)

// A turn on a checkout holding a stopped rebase, merge or cherry-pick, one picking several commits
// included, runs here though a machine takes turns: none is offered to it, as a checkout with none
// stopped is.
func TestAStoppedRebaseTurnsHere(t *testing.T) {
	home := t.TempDir()
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "GIT_CONFIG_NOSYSTEM": "1", "GIT_EDITOR": "true",
		"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@example.com", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@example.com"} {
		t.Setenv(key, value)
	}
	for _, key := range []string{"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"} {
		t.Setenv(key, "")
		os.Unsetenv(key)
	}
	if os.MkdirAll(filepath.Join(home, ".agentkit"), 0o700) != nil ||
		os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte("[machines.acme]\nwork = ['turns', 'tests']\n"), 0o600) != nil {
		t.Fatal("no config")
	}
	if !machines.TakesTurns() {
		t.Fatal("acme takes no turns")
	}
	offered := 0
	shipped := placed
	placed = func(config.Model, []string, string, string, map[string]string, string) *helper.Turn {
		offered++
		return nil
	}
	t.Cleanup(func() { placed = shipped })
	for _, stop := range []struct {
		name  string
		stops func(git func(fails bool, args ...string) string, wt string)
		left  []string // what git keeps of it in the checkout's own git directory
	}{
		{"none", func(func(bool, ...string) string, string) {}, nil},
		{"merge", func(git func(bool, ...string) string, _ string) { git(true, "merge", "other") }, []string{"MERGE_HEAD"}},
		{"cherry-pick", func(git func(bool, ...string) string, _ string) { git(true, "cherry-pick", "other~1") }, []string{"CHERRY_PICK_HEAD"}},
		{"rebase", func(git func(bool, ...string) string, _ string) { git(true, "rebase", "other") }, []string{"rebase-merge"}},
		{"sequencer", func(git func(bool, ...string) string, wt string) {
			// the first of two picks stops, and is committed by hand: the rest still waits
			git(true, "cherry-pick", "other~1", "other")
			if err := os.WriteFile(filepath.Join(wt, "f.txt"), []byte("both\n"), 0o644); err != nil {
				t.Fatal(err)
			}
			git(false, "add", "f.txt")
			git(false, "commit", "-q", "--no-edit")
		}, []string{"sequencer"}},
	} {
		t.Run(stop.name, func(t *testing.T) {
			root := t.TempDir()
			repo, wt := filepath.Join(root, "repo"), filepath.Join(root, "wt")
			at := repo
			git := func(fails bool, args ...string) string {
				said, err := exec.Command("git", append([]string{"-C", at}, args...)...).CombinedOutput()
				if err == nil == fails {
					t.Fatalf("git %s: %v\n%s", strings.Join(args, " "), err, said)
				}
				return strings.TrimSpace(string(said))
			}
			put := func(name, text, message string) {
				if err := os.WriteFile(filepath.Join(at, name), []byte(text), 0o644); err != nil {
					t.Fatal(err)
				}
				git(false, "add", name)
				git(false, "commit", "-q", "-m", message)
			}
			if err := os.Mkdir(repo, 0o755); err != nil {
				t.Fatal(err)
			}
			git(false, "init", "-q", "-b", "main")
			put("f.txt", "base\n", "base")
			git(false, "checkout", "-q", "-b", "other")
			put("f.txt", "theirs\n", "theirs")
			put("g.txt", "more\n", "more")
			git(false, "checkout", "-q", "main")
			// a run's checkout is a worktree, its own git directory not the repository's
			git(false, "worktree", "add", "-q", "-b", "work", wt, "main")
			at = wt
			put("f.txt", "ours\n", "ours")
			stop.stops(git, wt)
			own := git(false, "rev-parse", "--absolute-git-dir")
			for _, name := range stop.left {
				if _, err := os.Stat(filepath.Join(own, name)); err != nil {
					t.Fatalf("git left no %s: %v", name, err)
				}
			}
			if _, err := os.Stat(filepath.Join(own, "CHERRY_PICK_HEAD")); stop.name == "sequencer" && err == nil {
				t.Fatal("the sequencer's pick is still stopped")
			}
			before := offered
			turn := elsewhere(config.Model{Harness: "acme"}, []string{"acme.sh", "turn"}, wt, t.TempDir(), map[string]string{"HOME": home}, "")
			switch {
			case turn != nil:
				t.Fatal("a turn went to a machine")
			case stop.left == nil && offered == before:
				t.Fatal("a checkout with nothing stopped was offered no machine")
			case stop.left != nil && offered != before:
				t.Fatalf("the stopped %s was offered a machine", stop.name)
			}
		})
	}
}
