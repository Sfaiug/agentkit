package run

import (
	"os"
	"testing"

	"agentkit/internal/host"
)

// Each case of land.member: a place is held by a record waiting in a line, or a green delivery
// that has not ended, is on its way and runs or is resumed by the tick.
func TestAPlaceInTheLineIsPythonsLandMember(t *testing.T) {
	worktree := t.TempDir()
	line := func() *Object { return Fields("line", ".merge-acme.lock", "joined", 1) }
	green := func() *Object { return Fields("line", ".merge-acme.lock", "joined", 1, "land", "tree") }
	alive := Fields("state", "running", "waiting_on", green(), "pid", os.Getpid())
	if born, ok := host.ReadIdentity(os.Getpid()); ok {
		alive.Set("process_identity", Fields("boot", born.Boot, "ticks", int(born.Ticks)))
	}
	for _, each := range []struct {
		name   string
		record *Object
		member bool
	}{
		{"waiting", Fields("state", "waiting", "waiting_on", line()), true},
		{"waiting on a red", Fields("state", "waiting", "waiting_on", SetAll(line(), "fix", Fields())), true},
		{"merged", Fields("state", "waiting", "merged", true, "waiting_on", line()), false},
		{"no line", Fields("state", "waiting", "waiting_on", Fields("joined", 1)), false},
		{"joined no number", Fields("state", "waiting", "waiting_on", Fields("line", ".merge-acme.lock", "joined", true)), false},
		{"no wait", Fields("state", "waiting"), false},
		{"running green, its process alive", alive, true},
		{"running green the tick resumes", Fields("state", "running", "waiting_on", green(), "worktree", worktree), true},
		{"running green, its last death parked", Fields("state", "running", "waiting_on", green(), "worktree", worktree,
			"deaths", []any{Fields("parked", true)}), false},
		{"running green, its worktree gone", Fields("state", "running", "waiting_on", green(), "worktree", worktree+"/gone"), false},
		{"running, no verdict", Fields("state", "running", "waiting_on", line(), "worktree", worktree), false},
		{"running red", Fields("state", "running", "waiting_on", SetAll(green(), "fix", Fields()), "worktree", worktree), false},
		{"ended green", Fields("state", "error", "waiting_on", green(), "worktree", worktree), false},
		{"queued green, a slot awaited", Fields("state", "queued", "slot_waiting", true, "waiting_on", green(), "worktree", worktree), true},
		{"queued green, nothing to start it", Fields("state", "queued", "waiting_on", green(), "worktree", worktree), false},
		{"waiting_login green", Fields("state", "waiting_login", "waiting_on", green(), "worktree", worktree), true},
		{"exhausted green on a window", Fields("state", "exhausted", "quota_dry", true, "waiting_on", green(), "worktree", worktree), true},
		{"exhausted green on a reviewer", Fields("state", "exhausted", "error", "reviewer: API/transport errors", "waiting_on", green(),
			"worktree", worktree), true},
		{"exhausted green, replaced", Fields("state", "exhausted", "quota_dry", true, "replaced", true, "waiting_on", green(),
			"worktree", worktree), false},
		{"exhausted green on nobody", Fields("state", "exhausted", "waiting_on", green(), "worktree", worktree), false},
		{"interrupted green with a death", Fields("state", "interrupted", "deaths", []any{Fields()}, "waiting_on", green(),
			"worktree", worktree), true},
		{"interrupted green, no death", Fields("state", "interrupted", "waiting_on", green(), "worktree", worktree), false},
		{"stalled green", Fields("state", "stalled", "waiting_on", green(), "worktree", worktree), false},
	} {
		t.Run(each.name, func(t *testing.T) {
			if got := Member(each.record); got != each.member {
				t.Fatalf("Member = %v, want %v: %s", got, each.member, Encode(each.record))
			}
		})
	}
}
