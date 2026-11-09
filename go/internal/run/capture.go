package run

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

// LaunchValues and LaunchSwitches are the options Python's launch_opts records, in order.
var (
	LaunchValues   = []string{"--rounds", "--exec", "--review", "--review-pr", "--parallel"}
	LaunchSwitches = []string{"--no-worktree", "--no-merge", "--bg", "--anyway", "--first"}
)

// Capture builds a launch receipt as Python's capture_launch does. The caller writes it
// under the slots lock, adding any origin and admission marks before that first write.
func Capture(dir, path string, values map[string]string, flags map[string]bool, bound config.Binding, seat string) *Object {
	depth, _ := strconv.Atoi(os.Getenv("AK_RUN_DEPTH"))
	at := float64(time.Now().UnixNano()) / 1e9
	var parent, identity any
	if value, set := os.LookupEnv("AK_PARENT_RUN"); set {
		parent = value
	}
	if born, ok := host.ReadIdentity(os.Getpid()); ok {
		identity = Fields("boot", born.Boot, "ticks", int(born.Ticks), "started_at", born.StartedAt)
	}
	launched, efforts := NewObject(), NewObject()
	for _, flag := range LaunchValues {
		launched.Set(flag, nil)
		if value, given := values[flag]; given {
			launched.Set(flag, value)
		}
	}
	for _, flag := range LaunchSwitches {
		launched.Set(flag, flags[flag])
	}
	var owner any
	if seat != "" {
		owner = seat
	}
	// the plan line a seat's task serves is its launch's to name (launch.Task)
	first := []any{"run_id", filepath.Base(dir), "state", "running", "verdict", nil,
		"launched_session", owner, "plan_line", nil, "started_at", at, "queued_at", at, "slot_waiting", false,
		"run_depth", depth, "parent_run", parent, "reservation_pending", true,
		"unattended", seat == "" && os.Getenv("AGENTKIT_UNATTENDED") != "", "pid", os.Getpid(),
		"process_identity", identity, "launch_opts", launched}
	// a seat binds its own lists, and the config its own where it names reviewers apart
	if seat != "" || bound.Reviewers != nil {
		first = append(first, "workers", bound.Workers)
	}
	if bound.Reviewers != nil {
		first = append(first, "reviewers", bound.Reviewers)
	}
	for _, model := range bound.Models {
		keys := NewObject()
		for _, effort := range bound.Efforts[model] {
			keys.Set(effort[0], effort[1])
		}
		efforts.Set(model, keys)
	}
	// a review's proof is its plan's lines, and it has no task file
	var reviewed, proof any = nil, "owed"
	if url, given := values["--review-pr"]; given {
		reviewed, proof = url, nil
	}
	first = append(first, "efforts", efforts, "review_pr", reviewed, "reported", false, "base_proof", proof,
		"notify_sink", strings.TrimFunc(os.Getenv("AK_NOTIFY_SINK"), config.Space))
	if path != "" {
		first = append(first, "task_file", path)
	}
	if flags["--first"] {
		first = append(first, "first", true)
	}
	return Fields(append(first, "slot_started_at", at)...)
}
