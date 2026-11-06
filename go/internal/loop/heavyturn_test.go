//go:build linux

package loop

import (
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/turn"
)

// A `# once` command and each piece of a suite hold a turn of their own and are told so, a light
// command neither; a suite answering that its turn is busy gives it back for a poll and runs again,
// which is no failure.
func TestAHeavyCommandIsToldItsTurn(t *testing.T) {
	l := rig(t, time.Minute)
	t.Setenv("AK_MAX_RUNS", "")
	t.Setenv("AK_HOST_READINGS", `{"cpus": 4, "load": 0, "free_mb": 400}`)
	if err := run.Change(l.dir, func(record *run.Object) error { record.Set("repo", l.workspace); return nil }); err != nil {
		t.Fatal(err)
	}
	told := `echo "${AK_HEAVY_TURN:-}" >>told`
	l.once = []string{told + " # once"}
	path := filepath.Join(l.dir, "checks.log")
	if ok, text, _, err := l.checksIn(l.workspace, []string{told, told + " # once", told + " # AK_SHARD"}, path, nil); err != nil || !ok {
		t.Fatal(err, text)
	}
	if said, _ := os.ReadFile(filepath.Join(l.workspace, "told")); string(said) != "\n1\n1\n1\n" {
		t.Errorf("light, once and two pieces were told %q", said)
	}
	l.once = []string{"[ -f tried ] || { touch tried; exit 75; }"}
	if ok, text, _, err := l.checksIn(l.workspace, l.once, path, nil); err != nil || !ok {
		t.Fatal(err, text)
	}
	if failed, _ := filepath.Glob(filepath.Join(l.dir, "checks-failed-*.log")); len(failed) > 0 {
		t.Errorf("a busy answer was taken for a failure: %v", failed)
	}
}

// Each go of a piece answers busy once: its first, its retry once the kernel killed it for memory,
// its failed tests alone and the whole piece again.  Each goes again on a turn after a poll, and
// the check passes, as no busy answer is a failure.
func TestEveryAttemptThatSaysBusyRunsAgain(t *testing.T) {
	l := rig(t, time.Minute)
	t.Setenv("AK_MAX_RUNS", "")
	t.Setenv("AK_HOST_READINGS", `{"cpus": 4, "load": 0, "free_mb": 400}`) // one turn, two pieces
	defer func(poll time.Duration) { turn.Poll = poll }(turn.Poll)
	turn.Poll = 300 * time.Millisecond
	if err := run.Change(l.dir, func(record *run.Object) error { record.Set("repo", l.workspace); return nil }); err != nil {
		t.Fatal(err)
	}
	// the cgroup's oom_kill count, which a go the kernel killed for memory raised
	cgroup := filepath.Join(l.workspace, "cgroup")
	membership := filepath.Join(t.TempDir(), "membership")
	if err := os.MkdirAll(filepath.Join(cgroup, "acme"), 0o777); err != nil {
		t.Fatal(err)
	}
	for path, text := range map[string]string{filepath.Join(cgroup, "acme", "memory.events"): "oom_kill 0\n", membership: "0::/acme\n"} {
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AK_CGROUP_ROOT", cgroup)
	t.Setenv("AK_CGROUP_FILE", membership)
	suite := `[ "$AK_SHARD" = 2/2 ] && exit 0
n=$(cat goes 2>/dev/null || echo 0); echo $((n + 1)) >goes
echo "$n ${AK_HEAVY_TURN:-none} ${AK_ONLY:+named} $(date +%s%N)" >>went
case $n in
0|2|4|6) exit 75 ;;
1) echo "oom_kill 1" >cgroup/acme/memory.events; kill -9 $$ ;;
3) echo bad.sh >"$AK_FAILED"; exit 1 ;;
5) echo bad.sh >"$AK_RAN" ;;
esac # AK_SHARD`
	if ok, text, _, err := l.checksIn(l.workspace, []string{suite}, filepath.Join(l.dir, "checks.log"), nil); err != nil || !ok {
		t.Fatal(err, text)
	}
	went, _ := os.ReadFile(filepath.Join(l.workspace, "went"))
	goes := strings.Split(strings.TrimSpace(string(went)), "\n")
	if len(goes) != 8 {
		t.Fatalf("went %q", went)
	}
	var busy int64
	for n, line := range goes {
		fields := strings.Fields(line)
		at, _ := strconv.ParseInt(fields[len(fields)-1], 10, 64)
		if named := n == 4 || n == 5; fields[1] != "1" || (len(fields) == 4) != named {
			t.Errorf("go %d was %q: told it holds a turn, and its failed tests alone %v", n, line, named)
		}
		if n%2 == 1 && time.Duration(at-busy) < turn.Poll {
			t.Errorf("go %d went %v after its busy answer, before a poll", n, time.Duration(at-busy))
		}
		busy = at
	}
}

// A line's check waiting for a turn gives up the line's place and hands over once its member
// leaves the line.
func TestALinesCheckWhoseMemberLeftHandsOver(t *testing.T) {
	l, repo := repoRig(t)
	t.Setenv("AK_MAX_RUNS", "")
	head, tree, err := repo.identity()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(l.dir, "task.md"), []byte("# Acme\n\n## Done when\n```bash\ntrue # once\n```\n"), 0o666); err != nil {
		t.Fatal(err)
	}
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "state", "waiting", "pid", nil, "base_sha", head, "merge_method", "squash",
			"review", run.Fields("verdict", "PASS", "head_sha", head, "tree_sha", tree),
			"waiting_on", run.Fields("line", ".merge-acme.lock", "joined", 1))
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	saved, _ := run.Read(l.dir)
	stacks, err := buildNarrowing(repo.repo, head, "main", nil, []member{{l.dir, saved}}, io.Discard)
	if err != nil || len(stacks) != 1 {
		t.Fatal(err, len(stacks))
	}
	defer closeNarrowing(stacks)
	holder, err := lock.Try(host.HeavyTurns(1)[0])
	if err != nil {
		t.Fatal(err)
	}
	defer holder.Close()
	t.Setenv("AK_HOST_READINGS", `{"cpus": 4, "load": 0, "free_mb": 400}`)
	selection := &checkSelection{}
	done := make(chan error, 1)
	go func() {
		_, err := stacks[0].check([]string{"true"}, "", selection)
		done <- err
	}()
	for deadline := time.Now().Add(30 * time.Second); !host.LineCheckWaits(); time.Sleep(10 * time.Millisecond) {
		if time.Now().After(deadline) {
			t.Fatal("the line's check never waited")
		}
	}
	if err := run.Change(l.dir, func(record *run.Object) error { record.Delete("waiting_on"); return nil }); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		if err != nil || !selection.handoff {
			t.Errorf("ended %v, handed over %v", err, selection.handoff)
		}
	case <-time.After(30 * time.Second):
		t.Fatal("the line's check went on waiting")
	}
	if host.LineCheckWaits() {
		t.Error("the line's check kept its place")
	}
}
