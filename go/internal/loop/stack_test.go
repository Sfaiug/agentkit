//go:build linux

package loop

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestPrefixAcceptsDeliveryRebasesButRejectsChangedWork(t *testing.T) {
	saved := run.Fields("state", "waiting", "waiting_on", run.Fields("line", ".merge-acme.lock", "joined", 1, "land", "stack-tree"),
		"review", run.Fields("verdict", "PASS", "head_sha", "reviewed", "passed_head_sha", "reviewed", "tree_sha", "own-tree"))
	for _, each := range []struct {
		name   string
		change func(*run.Object)
		want   bool
	}{
		{"waiting", func(*run.Object) {}, true},
		{"merged rebase", func(r *run.Object) {
			run.SetAll(r, "state", "pass", "merged", true)
			r.Delete("waiting_on")
			run.SetAll(r.Dict("review"), "head_sha", "rebased", "tree_sha", "stack-tree")
		}, true},
		{"other work, same tree", func(r *run.Object) { r.Dict("review").Set("passed_head_sha", "other") }, false},
		{"other merged tree", func(r *run.Object) {
			run.SetAll(r, "state", "pass", "merged", true)
			r.Dict("review").Set("tree_sha", "different-tree")
		}, false},
		{"rejoined", func(r *run.Object) { r.Dict("waiting_on").Delete("land") }, false},
		{"stopped", func(r *run.Object) { r.Set("state", "stopped") }, false},
	} {
		t.Run(each.name, func(t *testing.T) {
			current := saved.Copy()
			current.Set("review", saved.Dict("review").Copy())
			current.Set("waiting_on", saved.Dict("waiting_on").Copy())
			each.change(current)
			if got := sameDelivery(saved, current); got != each.want {
				t.Fatalf("accepted=%v, want %v", got, each.want)
			}
		})
	}
}

func TestSuffixReleasesTheDeliveryLockToItsPrefix(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	const line = ".merge-acme.lock"
	first, second := filepath.Join(run.Runs(), "first"), filepath.Join(run.Runs(), "second")
	for dir, wait := range map[string]*run.Object{
		first:  run.Fields("line", line, "joined", 2, "land", "first-tree"),
		second: run.Fields("line", line, "joined", 1, "land", "second-tree", "after", run.Fields("first", "first-tree")),
	} {
		if err := os.MkdirAll(dir, 0o777); err != nil {
			t.Fatal(err)
		}
		if err := run.Create(dir, run.Fields("state", "waiting", "waiting_on", wait)); err != nil {
			t.Fatal(err)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	l := &loop{ctx: ctx, dir: second, voice: io.Discard}
	ended := make(chan error, 1)
	go func() {
		defer close(ended)
		held, err := l.deliveryLock(filepath.Join(run.Runs(), line))
		if held != nil {
			held.Close()
		}
		ended <- err
	}()
	defer func() {
		cancel()
		<-ended
	}()
	for {
		if record, _ := run.Read(second); record.Has("delivery_wait") {
			break
		}
		select {
		case err := <-ended:
			t.Fatalf("suffix acquired before its prefix: %v", err)
		case <-ctx.Done():
			t.Fatal(ctx.Err())
		case <-time.After(time.Millisecond):
		}
	}
	held, err := (&loop{ctx: ctx, dir: first}).deliveryLock(filepath.Join(run.Runs(), line))
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	if err := run.Change(first, func(r *run.Object) error { r.Set("merged", true); return nil }); err != nil {
		t.Fatal(err)
	}
	held.Close()
	if err := <-ended; err != nil {
		t.Fatal(err)
	}
	if record, _ := run.Read(second); record.Has("delivery_wait") {
		t.Fatal("delivery_wait survived the acquisition")
	}
}
