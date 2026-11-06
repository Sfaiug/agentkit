//go:build linux

package loop

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestNarrowingProbeLeavesTheOriginalTreeForItsWholeCheck(t *testing.T) {
	l, repo := repoRig(t)
	head, tree, err := repo.identity()
	if err != nil {
		t.Fatal(err)
	}
	stack := &narrowingStack{l: l, checkout: &landingCheckout{path: repo.wt}, head: head, tree: tree}
	stack.dir = l.dir
	answer, err := stack.checkTests("touch probe-output", "", &checkSelection{shard: "1/1"})
	if err != nil || answer == nil || !answer.Has("land") {
		t.Fatalf("probe: %v, %v", answer, err)
	}
	if _, err := os.Stat(filepath.Join(repo.wt, "probe-output")); !os.IsNotExist(err) {
		t.Fatalf("probe output survived into the next check: %v", err)
	}
	answer, err = stack.check([]string{"test ! -e probe-output"}, "", &checkSelection{})
	if err != nil || answer == nil || !answer.Has("land") {
		t.Fatalf("whole check: %v, %v", answer, err)
	}
}

func TestDeliveryRedRetainsItsFixReceipt(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	dir := filepath.Join(run.Runs(), "fix-api")
	if err := os.MkdirAll(dir, 0o777); err != nil {
		t.Fatal(err)
	}
	wait := run.Fields("line", ".merge-acme.lock", "joined", 1, "land", "tree",
		"fix", run.Fields("line", "required checks failed"), "after", run.Fields("first", "first-tree"))
	if err := run.Create(dir, run.Fields("state", "waiting", "waiting_on", wait, "review", run.Fields("verdict", "PASS"))); err != nil {
		t.Fatal(err)
	}
	saved, _ := run.Read(dir)
	if err := narrowLine("", "", "", "", "", []member{{dir, saved}}, io.Discard); err != nil {
		t.Fatal(err)
	}
	current, _ := run.Read(dir)
	if !run.Equal(current.Dict("waiting_on"), wait) {
		t.Fatalf("a delivery red was replaced by a new stack check: %s", run.Encode(current))
	}
}

// A member not ready (land.check_line) keeps its place and holds nothing behind it; a handoff
// leaves the rest to Python's lander.
func TestNarrowingLandsTheReadyPrefixBeforeAHandoff(t *testing.T) {
	passedOver := map[string]bool{"active": true, "missing-review": true, "delivery-red": true, "review-pr-moved": true, "repair-moved": true}
	for _, kind := range []string{"conflict", "review-pr", "repair", "active", "missing-review", "rules", "changed", "delivery-red",
		"review-pr-moved", "repair-moved"} {
		t.Run(kind, func(t *testing.T) {
			_, repo := repoRig(t)
			t.Setenv("AK_HOST_READINGS", `{"cpus":4,"load":0,"free_mb":16000}`)
			shell(t, repo.repo, "printf '%s\\n' '---' 'tests: true' '---' '# acme' > AGENTS.md; echo original > same.txt; git add -A; git commit -qm suite")
			tip := strings.TrimSpace(shell(t, repo.repo, "git rev-parse HEAD"))
			turn := filepath.Join(run.Runs(), ".merge-acme.lock")
			var members []member
			for n := 1; n <= 3; n++ {
				shell(t, repo.wt, "git checkout -q --detach "+tip)
				file, text := fmt.Sprintf("member-%d.txt", n), "x\n"
				if kind == "conflict" && n <= 2 {
					file, text = "same.txt", fmt.Sprintf("%d\n", n)
				} else if kind == "rules" && n == 2 {
					file, text = "README.md", strings.Repeat("word ", 301)+"\n"
				}
				if err := os.WriteFile(filepath.Join(repo.wt, file), []byte(text), 0o666); err != nil {
					t.Fatal(err)
				}
				shell(t, repo.wt, "git add -A; git commit -qm member")
				head, tree, err := repo.identity()
				if err != nil {
					t.Fatal(err)
				}
				dir := filepath.Join(run.Runs(), fmt.Sprintf("fix-%d", n))
				// A directory at its log refuses the wake before it can spawn this test binary.
				if err := os.MkdirAll(filepath.Join(dir, "log.txt"), 0o777); err != nil {
					t.Fatal(err)
				}
				task := "# Fix api\n\n## Done when\n```bash\ntrue\n```\n"
				record := run.Fields("state", "waiting", "repo", repo.repo, "worktree", repo.wt, "base_sha", tip, "merge_method", "squash",
					"review", run.Fields("verdict", "PASS", "head_sha", head, "tree_sha", tree),
					"waiting_on", run.Fields("line", filepath.Base(turn), "joined", n))
				if n == 2 {
					switch kind {
					case "review-pr", "repair", "review-pr-moved", "repair-moved":
						record.Set(strings.ReplaceAll(strings.TrimSuffix(kind, "-moved"), "-", "_"), true)
					case "active":
						run.SetAll(record, "pid", os.Getpid(), "process_identity", identity(os.Getpid()))
					case "missing-review":
						record.Set("review", nil)
					case "changed":
						task = strings.Replace(task, "true\n", ": \"$AK_CHANGED\"; true # once\n", 1)
					case "delivery-red":
						run.SetAll(record.Dict("waiting_on"), "land", tree, "fix", run.Fields("line", "required checks failed"))
					}
				}
				if err := os.WriteFile(filepath.Join(dir, "task.md"), []byte(task), 0o666); err != nil {
					t.Fatal(err)
				}
				if err := run.Create(dir, record); err != nil {
					t.Fatal(err)
				}
				saved, _ := run.Read(dir)
				members = append(members, member{dir, saved})
			}
			if strings.HasSuffix(kind, "-moved") {
				// its record changed since the line was read: passed over before any handoff
				if err := run.Change(members[1].dir, func(record *run.Object) error {
					record.Set("error", "moved on")
					return nil
				}); err != nil {
					t.Fatal(err)
				}
			}
			if err := narrowLine(turn, "", repo.repo, tip, "main", members, io.Discard); err != nil {
				t.Fatal(err)
			}
			first, _ := run.Read(members[0].dir)
			if !green(first.Dict("waiting_on")) {
				t.Fatalf("ready member has no green verdict: %s", run.Encode(first))
			}
			second, _ := run.Read(members[1].dir)
			if !run.Equal(second.Dict("waiting_on"), members[1].record.Dict("waiting_on")) {
				t.Fatalf("the member not ready or handed off was changed: %s", run.Encode(second))
			}
			third, _ := run.Read(members[2].dir)
			if checked := !run.Equal(third.Dict("waiting_on"), members[2].record.Dict("waiting_on")); checked != passedOver[kind] {
				t.Fatalf("checked behind %s: %v, %s", kind, checked, run.Encode(third))
			}
			if passedOver[kind] && !green(third.Dict("waiting_on")) {
				t.Fatalf("the member behind one not ready has no green verdict: %s", run.Encode(third))
			}
		})
	}
}

func TestNarrowingWaitsForAMissingReview(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	dir := filepath.Join(run.Runs(), "fix-api")
	if err := os.MkdirAll(dir, 0o777); err != nil {
		t.Fatal(err)
	}
	record := run.Fields("state", "waiting", "waiting_on", run.Fields("line", ".merge-acme.lock", "joined", 1), "review", nil)
	if err := run.Create(dir, record); err != nil {
		t.Fatal(err)
	}
	saved, _ := run.Read(dir)
	if err := narrowLine("", "", "", "", "", []member{{dir, saved}}, io.Discard); err != nil {
		t.Fatal(err)
	}
}
