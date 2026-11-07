//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/gitcall"
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
