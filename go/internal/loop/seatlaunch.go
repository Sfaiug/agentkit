package loop

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/task"
)

// HoldSlots and WaitSlot are supplied by launch, which owns admission and uses the loop to drive
// runs: the slots lock, and the run's wait for its slot in its driver, done once it holds one or
// waits in no other process's stead.
var (
	HoldSlots func(context.Context) (*os.File, error)
	WaitSlot  func(ctx context.Context, dir string) error
)

// ErrLeft is a slot wait Go leaves to Python: nothing of it written, its waiter's going leaves it for
// Python's tick, which takes up a waiter whose process is gone.
var ErrLeft = errors.New("a slot wait left to Python")

// launchForSeat prepares a sibling run with the seat's lists now, not the ending's slot,
// marker or ancestry, ahead of the queue where origin says `first`. Its first record is queued,
// recoverable by Python's tick if cut off. The returned start runs only after its plan line is
// written.
func launchForSeat(dir string, state, origin *run.Object) (func() error, error) {
	session, lists, err := config.ResolveSession(run.Seat(state))
	if err != nil {
		return nil, err
	}
	bound, err := config.BindSeat(lists)
	if err != nil {
		return nil, err
	}
	policy, err := run.TaskPolicy(origin.Str("repo"))
	if err != nil {
		return nil, err
	}
	if !run.Carried(policy) {
		// no receipt: the line stays the seat's own to build, as where a launch fails
		return nil, errors.New("review off is Python's to carry")
	}
	path := filepath.Join(dir, "task.md")
	text, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	held, err := HoldSlots(context.Background())
	if err != nil {
		return nil, err
	}
	record := run.Capture(dir, path, nil, map[string]bool{"--bg": true, "--first": origin.Truthy("first")}, bound, session)
	for _, key := range origin.Keys() {
		record.Set(key, origin.Get(key))
	}
	run.SetAll(record, "title", task.Title(string(text), "task"), "state", "queued", "slot_waiting", true,
		"run_depth", 0, "parent_run", nil, "unattended", false, "slot_started_at", nil,
		"project", seat.CheckoutOf(record.Str("repo")), "notify_sink", state.Get("notify_sink"),
		"policy", run.Fields(policy.Said()...))
	err = run.Create(dir, record)
	held.Close()
	if err != nil {
		return nil, err
	}
	// its row, out of the slots lock, as Python's capture_launch writes it
	history.Start(record, nil)
	return func() error {
		// General host admission is still Python's. Keep its queued receipt, not an
		// error ending, if the gates changed since this run's own launch.
		if os.Getenv("AK_MAX_RUNS") != "0" {
			return fmt.Errorf("queued for Python's host admission")
		}
		held, err := HoldSlots(context.Background())
		if err != nil {
			return err
		}
		defer held.Close()
		seat.Redress(session)
		return Start(dir, io.Discard, true)
	}, nil
}

// siblingEnv drops the ending's process-sweep marker and turn variables. The fix's own
// driver installs its marker and ancestry after taking its own slot.
func siblingEnv(record *run.Object) ([]string, error) {
	env, err := config.ChildEnv()
	if err != nil {
		return nil, err
	}
	env = slices.DeleteFunc(env, func(pair string) bool {
		key, _, _ := strings.Cut(pair, "=")
		return slices.Contains([]string{host.Marker, "AK_PARENT_RUN", "AK_RUN_LOG", "AK_RUN_DEPTH",
			"AGENTKIT_UNATTENDED", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE", "AGENTKIT_SESSION"}, key)
	})
	return append(env, "AK_RUN_DEPTH=0", "AGENTKIT_SESSION="+run.Seat(record)), nil
}

// A queued launch that could not spawn keeps its place for the tick to recover.
func failedStart(dir, reason string) {
	queued := false
	run.Change(dir, func(record *run.Object) error {
		queued = record.Str("state") == "queued" && record.Truthy("slot_waiting")
		if queued {
			run.SetAll(record, "pid", nil, "process_identity", nil, "launch_pending", false, "launch_error", reason)
		}
		return nil
	})
	if !queued {
		End(dir, reason)
	}
}
