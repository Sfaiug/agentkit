//go:build linux

package loop

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
	"agentkit/internal/uncommitted"
)

func rawConsumerRepo(t *testing.T) gitcall.Git {
	t.Helper()
	t.Setenv("HOME", t.TempDir())
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	g := gitcall.Git{Repo: t.TempDir(), Env: []string{"GIT_AUTHOR_NAME=acme", "GIT_AUTHOR_EMAIL=acme@example.test", "GIT_COMMITTER_NAME=acme", "GIT_COMMITTER_EMAIL=acme@example.test"}}
	for _, args := range [][]string{{"init", "-q", "-b", "main"}, {"commit", "-q", "--allow-empty", "-m", "base"}} {
		if _, err := g.Must(args...); err != nil {
			t.Fatal(err)
		}
	}
	return g
}

func TestRawConsumerProbeLeavesReadableRecord(t *testing.T) {
	g := rawConsumerRepo(t)
	name := "out\xffside.txt"
	if err := os.WriteFile(filepath.Join(g.Repo, name), []byte("worker work\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	if err := run.Create(dir, run.Fields("state", "running")); err != nil {
		t.Fatal(err)
	}
	l := &loop{ctx: context.Background(), dir: dir}
	r := &repoPlace{wt: g.Repo}
	head, err := g.Must("rev-parse", "HEAD")
	if err != nil {
		t.Fatal(err)
	}
	_, probeErr := r.onRevision(l, "review proof", head, "", func() (int, string, bool, error) {
		return 0, "", false, nil
	})
	if _, err := run.Read(dir); err != nil {
		t.Fatalf("a review proof made its run.json unreadable: %v (probe error: %v)", err, probeErr)
	}
	if probeErr != nil {
		t.Fatal(probeErr)
	}
	if _, err := os.Stat(filepath.Join(g.Repo, name)); err != nil {
		t.Fatalf("proof lost the worker file: %v", err)
	}
}

func TestRawConsumerArtifactsLeaveReadableRecord(t *testing.T) {
	l, r := repoRig(t)
	command := "python3 -c 'open(bytes([111,117,116,255])+b\"side.txt\", \"w\").write(\"generated\")'"
	ok, _, err := r.checks(l, []string{command}, filepath.Join(t.TempDir(), "check.log"), nil)
	if err != nil || !ok {
		t.Fatalf("check failed: %v", err)
	}
	if _, err := run.Read(l.dir); err != nil {
		t.Fatalf("a check artifact made its run.json unreadable: %v", err)
	}
}

func TestRawConsumerStagesDeletedNames(t *testing.T) {
	for _, name := range []string{" leading.txt", "out\rside.txt", "out\xffside.txt"} {
		for _, stage := range []string{"add", "tree"} {
			t.Run(stage+"/"+name, func(t *testing.T) {
				g := rawConsumerRepo(t)
				path := filepath.Join(g.Repo, name)
				if err := os.WriteFile(path, []byte("before\n"), 0o600); err != nil {
					t.Fatal(err)
				}
				for _, args := range [][]string{{"add", "-A"}, {"commit", "-qm", "before"}} {
					if _, err := g.Must(args...); err != nil {
						t.Fatal(err)
					}
				}
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
				if stage == "add" {
					if err := uncommitted.Add(g, []string{name}); err != nil {
						t.Fatal(err)
					}
					code, _, _, err := g.Bytes("diff", "--cached", "--quiet", "HEAD")
					if err != nil {
						t.Fatal(err)
					}
					if code == 0 {
						t.Fatalf("Add did not stage the deletion of %q", name)
					}
					return
				}
				tree, err := uncommitted.Tree(g, nil, filepath.Join(t.TempDir(), "index"))
				if err != nil {
					t.Fatal(err)
				}
				code, _, _, err := g.Bytes("cat-file", "-e", tree+":"+name)
				if err != nil {
					t.Fatal(err)
				}
				if code == 0 {
					t.Fatalf("workspace tree still holds deleted file %q", name)
				}
			})
		}
	}
}

func TestRawConsumerStagesDeletedJunk(t *testing.T) {
	for _, stage := range []string{"tree", "leftovers"} {
		for _, name := range []string{".ak-test-x/out\rside.txt", ".ak-test-x/out\xffside.txt"} {
			t.Run(stage+"/"+name, func(t *testing.T) {
				l, r := repoRig(t)
				g := r.git()
				path := filepath.Join(g.Repo, name)
				if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte("old sandbox\n"), 0o600); err != nil {
					t.Fatal(err)
				}
				for _, args := range [][]string{{"add", "-A"}, {"commit", "-qm", "before"}, {"rm", "--", ":(literal)" + name}} {
					if _, err := g.Must(args...); err != nil {
						t.Fatal(err)
					}
				}
				tree := "HEAD"
				if stage == "tree" {
					var err error
					tree, err = uncommitted.Tree(g, nil, filepath.Join(t.TempDir(), "index"))
					if err != nil {
						t.Fatal(err)
					}
				} else if err := r.commitLeftovers(l); err != nil {
					t.Fatal(err)
				}
				code, _, _, err := g.Bytes("cat-file", "-e", tree+":"+name)
				if err != nil {
					t.Fatal(err)
				}
				if code == 0 {
					t.Fatalf("%s retained the staged deletion of junk file %q", stage, name)
				}
			})
		}
	}
}
