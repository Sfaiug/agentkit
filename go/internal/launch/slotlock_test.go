package launch

import (
	"context"
	"errors"
	"os"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/loop"
)

func TestLaunchAndLoopShareAdmissionAndItsCancellableWait(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("USERPROFILE", os.Getenv("HOME"))
	if err := config.EnsureDirs(); err != nil {
		t.Fatal(err)
	}
	held, err := holdSlots()
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	file, err := loop.HoldSlots(ctx)
	if file != nil {
		file.Close()
	}
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("the loop did not wait on the launch's held lock: %v", err)
	}
}
