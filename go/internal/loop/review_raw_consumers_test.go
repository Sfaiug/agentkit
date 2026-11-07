//go:build linux

package loop

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
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
