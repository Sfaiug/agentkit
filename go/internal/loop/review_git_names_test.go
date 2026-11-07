//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"slices"
	"testing"

	"agentkit/internal/gitcall"
	"agentkit/internal/uncommitted"
)

func reviewNamesRepo(t *testing.T) gitcall.Git {
	t.Helper()
	t.Setenv("HOME", t.TempDir())
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	g := gitcall.Git{Repo: t.TempDir(), Env: []string{"GIT_AUTHOR_NAME=acme", "GIT_AUTHOR_EMAIL=acme@example.test", "GIT_COMMITTER_NAME=acme", "GIT_COMMITTER_EMAIL=acme@example.test"}}
	reviewNamesGit(t, g, "init", "-q", "-b", "main")
	reviewNamesGit(t, g, "commit", "-q", "--allow-empty", "-m", "base")
	return g
}

func reviewNamesGit(t *testing.T, g gitcall.Git, args ...string) string {
	t.Helper()
	out, err := g.Must(args...)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

func reviewNamesWrite(t *testing.T, g gitcall.Git, name, data string) {
	t.Helper()
	path := filepath.Join(g.Repo, name)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestReviewGitNamesScopeKeepsEveryByte(t *testing.T) {
	for _, each := range []struct{ label, inside, outside string }{
		{"leading space", "docs/file.txt", " docs/file.txt"},
		{"carriage return", "docs/\nfile.txt", "docs/\rfile.txt"},
		{"non UTF-8", "docs/\ufffdfile.txt", "docs/\xfffile.txt"},
	} {
		t.Run(each.label, func(t *testing.T) {
			g := reviewNamesRepo(t)
			base := reviewNamesGit(t, g, "rev-parse", "HEAD")
			reviewNamesWrite(t, g, each.inside, "inside\n")
			reviewNamesWrite(t, g, each.outside, "outside\n")
			reviewNamesGit(t, g, "add", "-A")
			reviewNamesGit(t, g, "commit", "-qm", "work")
			r := &repoPlace{wt: g.Repo, baseSHA: base, files: []string{":(literal)" + each.inside}}
			failure, err := r.filesScope()
			if err != nil {
				t.Fatal(err)
			}
			if failure == "" {
				t.Fatalf("files scope accepted outside path %q when only %q is allowed", each.outside, each.inside)
			}
		})
	}
}

func TestReviewGitNamesDirtyPathsKeepsEveryByte(t *testing.T) {
	for _, name := range []string{" outside.txt", "out\rside.txt", "out\xffside.txt"} {
		for _, tracked := range []bool{false, true} {
			label := "untracked "
			if tracked {
				label = "tracked "
			}
			t.Run(label+name, func(t *testing.T) {
				g := reviewNamesRepo(t)
				if tracked {
					reviewNamesWrite(t, g, name, "before\n")
					reviewNamesGit(t, g, "add", "-A")
					reviewNamesGit(t, g, "commit", "-qm", "before")
				}
				reviewNamesWrite(t, g, name, "after\n")
				paths, err := uncommitted.Paths(g)
				if err != nil {
					t.Fatal(err)
				}
				if !slices.Contains(paths, name) {
					t.Fatalf("dirty paths returned %q, losing the actual filename %q", paths, name)
				}
			})
		}
	}
}
