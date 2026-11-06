package loop

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A pass of a line is Python's lander's while a seat's own PR waits in it on a red, which only
// Python's wake takes to its writer; its green, and a task run's red, Go's lander carries.
func TestALineIsPythonsWhileAnOwnPullWaitsInItOnARed(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	line := ".merge-acme.lock"
	waits := func(verdict string) *run.Object {
		return run.Fields("line", line, "joined", 1, verdict, run.Fields("line", "red", "log", "lander.log"))
	}
	create := func(name string, record *run.Object) {
		dir := filepath.Join(run.Runs(), name)
		if err := os.MkdirAll(dir, 0o777); err != nil {
			t.Fatal(err)
		}
		if err := run.Create(dir, run.SetAll(record, "state", "waiting")); err != nil {
			t.Fatal(err)
		}
	}
	for name, record := range map[string]*run.Object{
		"task-red":  run.Fields("waiting_on", waits("fix")),
		"own-green": run.Fields("waiting_on", waits("land"), "review_pr", "https://github.com/acme/api/pull/1", "own_pr", true),
	} {
		create(name, record)
	}
	if LineToPython(line) {
		t.Fatal("a line Go's lander carries was handed to Python")
	}
	create("own-red", run.Fields("waiting_on", waits("fix"), "review_pr", "https://github.com/acme/api/pull/2", "own_pr", true))
	if !LineToPython(line) || LineToPython(".merge-other.lock") {
		t.Fatal("the pass of the line holding an own PR's red is Python's, and only that line's")
	}
}
