//go:build linux

package loop

import (
	"cmp"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// redLine is a line of one member, fix-1, adding a file to a target whose suite is red while the
// repository's git directory holds `red`, its record holding extra too: the suite, the line, the
// target's tip and tree, and the member's tree.
func redLine(t *testing.T, extra ...any) (string, string, *lineTarget, string, string) {
	_, repo := repoRig(t)
	t.Setenv("AK_HOST_READINGS", `{"cpus":4,"load":0,"free_mb":16000}`)
	suite := `test ! -f "$(git rev-parse --git-common-dir)/red"`
	shell(t, repo.repo, "printf '%s\\n' '---' 'tests: "+suite+"' '---' '# acme' > AGENTS.md; git add -A; git commit -qm suite; touch .git/red")
	tip := strings.TrimSpace(shell(t, repo.repo, "git rev-parse HEAD"))
	tree := strings.TrimSpace(shell(t, repo.repo, "git rev-parse HEAD^{tree}"))
	shell(t, repo.wt, "git checkout -q --detach "+tip+"; echo x > member.txt; git add -A; git commit -qm member")
	head, own, err := repo.identity()
	if err != nil {
		t.Fatal(err)
	}
	turn := filepath.Join(run.Runs(), ".merge-acme.lock")
	dir := filepath.Join(run.Runs(), "fix-1")
	// A directory at its log refuses the wake before it can spawn this test binary.
	if err := os.MkdirAll(filepath.Join(dir, "log.txt"), 0o777); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "task.md"), []byte("# Fix api\n\n## Done when\n```bash\ntrue\n```\n"), 0o666); err != nil {
		t.Fatal(err)
	}
	record := run.Fields("state", "waiting", "repo", repo.repo, "worktree", repo.wt, "base_sha", tip, "merge_method", "squash",
		"review", run.Fields("verdict", "PASS", "head_sha", head, "tree_sha", own), "waiting_on", run.Fields("line", filepath.Base(turn), "joined", 1))
	if err := run.Create(dir, run.SetAll(record, extra...)); err != nil {
		t.Fatal(err)
	}
	return suite, turn, &lineTarget{upstream: "origin/main", tip: tip, tree: tree}, dir, own
}

// landerPass is one lander pass over the line of dir on the target.
func landerPass(t *testing.T, turn string, target *lineTarget, dir string) {
	t.Helper()
	saved, _ := run.Read(dir)
	pass := *target
	pass.green = map[string]bool{}
	if err := narrowLine(turn, "", saved.Str("repo"), &pass, []member{{dir, saved}}, io.Discard); err != nil {
		t.Fatal(err)
	}
}

// A red target holds its line (land._probe_tip, paused): the first stack's red suite runs again on
// the tip alone, and red there pauses the line, nobody blamed, probed again only once the ladder's
// step has passed.  Red through the whole ladder, it holds the line on its repair; a pass on the tip
// clears it, and the member's own check decides.
func TestARedTargetPausesTheLineOnTheRetryLadder(t *testing.T) {
	suite, turn, target, dir, own := redLine(t)
	tip, tree := target.tip, target.tree
	pass := func(probes int) *run.Object {
		t.Helper()
		landerPass(t, turn, target, dir)
		red := cmp.Or(evidence(turn, "red").Dict(tree), run.NewObject())
		probe := cmp.Or(red.Dict("probe"), run.NewObject())
		if counted, _ := red.Int("probes"); counted != probes || probe.Str("sha") != tip || probe.Str("check") != suite+"  # once" {
			t.Fatalf("after a pass the red is %s, want %d probes of the tip", run.Encode(red), probes)
		}
		if current, _ := run.Read(dir); current.Dict("waiting_on").Has("fix") || current.Dict("waiting_on").Has("land") {
			t.Fatalf("a member was given a verdict on a red target: %s", run.Encode(current))
		}
		return red
	}
	due := func(probes int) {
		note(turn, func(_, red, _ *run.Object) { run.SetAll(red.Dict(tree), "at", 0, "probes", probes) })
	}
	pass(1)
	pass(1) // the ladder's first step has not passed: no probe
	due(1)
	pass(2)
	due(len(transientBackoff))
	if red := pass(len(transientBackoff) + 1); red.Has("run") {
		t.Fatalf("a repair started for a member of no seat: %s", run.Encode(red))
	}
	pass(len(transientBackoff) + 1) // its repair cannot start: the line waits on it
	record, _ := run.Read(dir)
	shell(t, record.Str("repo"), "rm .git/red")
	due(1)
	landerPass(t, turn, target, dir)
	if evidence(turn, "red").Has(tree) || evidence(turn, "trees").Dict(tree) == nil {
		t.Fatalf("a tip that passed is still red: %s", run.Encode(evidence(turn, "red")))
	}
	if current, _ := run.Read(dir); current.Dict("waiting_on").Str("land") != own {
		t.Fatalf("the member was not checked once the tip passed: %s", run.Encode(current))
	}
}

// A repair lands on the red target, which is never probed for it (land.check_line): its own red is
// its fixer's at once, and the line keeps no red of the target for it.
func TestARepairsRedIsItsOwn(t *testing.T) {
	_, turn, target, dir, _ := redLine(t, "repair", run.Fields("target", "main", "command", "suite"))
	landerPass(t, turn, target, dir)
	if current, _ := run.Read(dir); !current.Dict("waiting_on").Has("fix") {
		t.Fatalf("a repair red on the red target was not given its fix: %s", run.Encode(current))
	}
	if evidence(turn, "red").Has(target.tree) {
		t.Fatalf("the tip was probed for a repair: %s", run.Encode(evidence(turn, "red")))
	}
}

// A probe that proves nothing of the target leaves its red as it found it, due, for the next pass:
// a piece the kernel killed for memory on the tip is the host's red, and a checkout that cannot be
// put on the tip is the pass's error.
func TestAProbeWithNoVerdictLeavesTheRedAsItWas(t *testing.T) {
	_, turn, target, dir, _ := redLine(t)
	record, _ := run.Read(dir)
	cgroup := filepath.Join(record.Str("repo"), ".git", "cgroups")
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
	starved := `: AK_SHARD; events="$(git rev-parse --git-common-dir)/cgroups/acme/memory.events"; n=$(sed -n 's/^oom_kill //p' "$events"); echo "oom_kill $((n + 1))" >"$events"; kill -9 $$`
	probe := func(command string) error {
		t.Helper()
		note(turn, func(_, red, _ *run.Object) {
			red.Set(target.tree, run.Fields("at", 0, "probes", 1, "probe",
				run.Fields("command", command, "piece", "1/2", "check", command+"  # once", "sha", target.tip, "text", "red")))
		})
		before := run.Encode(evidence(turn, "red"))
		pass := *target
		pass.green = map[string]bool{}
		err := narrowLine(turn, "", record.Str("repo"), &pass, []member{{dir, record}}, io.Discard)
		if after := run.Encode(evidence(turn, "red")); after != before {
			t.Errorf("a probe of %q changed the target's red: %s", command, after)
		}
		return err
	}
	if err := probe(starved); err != nil {
		t.Fatal(err)
	}
	git, err := exec.LookPath("git")
	if err != nil {
		t.Fatal(err)
	}
	bin := t.TempDir()
	refusing := "#!/bin/sh\ncase \"$*\" in *'checkout --force --detach'*) exit 1;; esac\nexec " + git + " \"$@\"\n"
	if err := os.WriteFile(filepath.Join(bin, "git"), []byte(refusing), 0o777); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	if err := probe("false"); err == nil {
		t.Error("a checkout refused on the tip was no error")
	}
}
