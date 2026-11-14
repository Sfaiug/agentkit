//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A terminal following a run parked in its line starts its lander again only landerAgain after
// the run's driver left, which starts one itself: never at once, however long the follow ran.
func TestAFollowerStartsNoLanderAsTheDriverLeaves(t *testing.T) {
	home := t.TempDir()
	// no user manager: each starts plainly
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "XDG_RUNTIME_DIR": t.TempDir(),
		"AK_TEST_LANDER": filepath.Join(home, "lander")} {
		t.Setenv(key, value)
	}
	again := landerAgain
	landerAgain = time.Second
	t.Cleanup(func() { landerAgain = again })
	dir := filepath.Join(run.Runs(), "fix-api")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := run.Create(dir, run.Fields("state", "waiting", "pid", os.Getpid(), "process_identity", Identity(os.Getpid()),
		"waiting_on", run.Fields("line", ".merge-acme.lock", "joined", 1))); err != nil {
		t.Fatal(err)
	}
	started := filepath.Join(run.Runs(), ".merge-acme.log") // the line's log, which a lander's start opens
	began, alive, left := time.Now(), time.Time{}, false
	Await(dir, func() {
		_, err := os.Stat(started)
		switch {
		case !left && time.Since(began) < 2*landerAgain:
			if err == nil {
				t.Fatal("a lander started while the driver lived")
			}
			alive = time.Now() // the follow saw it live after this look
			return
		case !left:
			left = true
			err = run.Change(dir, func(record *run.Object) error {
				run.SetAll(record, "pid", nil, "process_identity", nil)
				return nil
			})
		case err != nil && time.Since(alive) < 30*time.Second:
			return
		case err != nil:
			t.Fatal("no lander started after the driver left")
		case time.Since(alive) < landerAgain:
			t.Fatal("a lander started as the driver left")
		default:
			err = run.Change(dir, func(record *run.Object) error {
				record.Set("state", "done")
				record.Delete("waiting_on")
				return nil
			})
		}
		if err != nil {
			t.Fatal(err)
		}
	})
	for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
		if data, _ := os.ReadFile(os.Getenv("AK_TEST_LANDER")); len(data) > 0 {
			return
		}
	}
	t.Fatal("no lander started")
}
