//go:build unix

package tick

import (
	"bytes"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A maintainer's merge of a PR from a fork goes on the run that opened it, with what its delivered
// commit declares, and is typed into its seat only where the seat owes work for it, a merge still
// inside its health window included: a seat owing nothing keeps the merge's notice as the run's
// hand-back, recorded and never typed.  A hand-back's line left unsent is Python's, with nothing
// written.
func TestAForkPRsMergeIsTypedOnlyWhereItsSeatOwesWork(t *testing.T) {
	address := "https://github.com/acme/widgets/pull/7"
	merged := "PR #7 Add retry file: merged by the maintainer"
	notice := merged + " -- " + address + ". Nothing was posted to Discord; this is the maintainer's decision on a PR of ours, for you to act on or not."
	for _, each := range []struct {
		name, plan string
		unsent     any
		left       error
		typed      string
	}{
		{name: "a seat owing nothing"},
		{name: "a seat owing work", plan: "- [ ] The work is done · check: `false` · lead · written 2026-10-23 09:00\n", typed: notice + "\nEnter\n"},
		{name: "a hand-back's line left unsent", unsent: run.Fields("line", "run 20261107-0900-add-retry-file finished", "seat", 1000), left: errLeft},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak, home := forkSeat(t)
			worktree := filepath.Join(t.TempDir(), "widgets")
			put(t, filepath.Join(worktree, "AGENTS.md"), "---\nhealth: curl -fsS https://acme.example/health\ndeployed: ./deploy.sh\n---\n")
			for _, args := range [][]string{
				{"init", "-q", "-b", "main", worktree},
				{"-C", worktree, "add", "-A"},
				{"-C", worktree, "-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-q", "-m", "init"},
			} {
				if out, err := exec.Command("git", args...).CombinedOutput(); err != nil {
					t.Fatalf("git %v: %s", args, out)
				}
			}
			sha, err := exec.Command("git", "-C", worktree, "rev-parse", "HEAD").Output()
			if err != nil {
				t.Fatal(err)
			}
			dir := filepath.Join(ak, "runs", "20261107-0900-add-retry-file")
			record := run.Fields("run_id", filepath.Base(dir), "state", "pass", "verdict", "PASS", "round_summaries", []any{}, "title", "Add retry file", "foreign", true, "pr", address,
				"merged", false, "launched_session", "lead", "merge_note", "waiting for the maintainer", "repo", worktree, "worktree", worktree,
				"delivery_sha", strings.TrimSpace(string(sha)), "finished_at", run.Float(epoch(time.Now())), "handed_back", run.Float(epoch(time.Now())), "reported", true)
			if each.unsent != nil {
				record.Set("handback_typed", each.unsent)
			}
			put(t, filepath.Join(dir, "run.json"), run.Line(record))
			put(t, filepath.Join(dir, "result.md"), "# NOT MERGED (1 of 3) — Add retry file\n")
			put(t, filepath.Join(dir, "task.md"), "# Add retry file\n\n## Done when\n\n```bash\ntest -f retry.txt\n```\n")
			if each.plan != "" {
				put(t, filepath.Join(ak, "state", "plan-lead.md"), each.plan)
			}
			put(t, filepath.Join(home, "view"), `{"state": "MERGED", "reviewDecision": "APPROVED", "title": "Add retry file", "number": 7}`)
			before := read(t, filepath.Join(dir, "run.json"))
			state, _ := loadState()
			var said bytes.Buffer
			if err := (&ticking{state: state, log: newLog(&said, io.Discard), clock: time.Now}).outgoing("beta"); !errors.Is(err, each.left) {
				t.Fatalf("the pass ended %v, saying %q", err, said.String())
			}
			typed, _ := os.ReadFile(filepath.Join(home, "keys"))
			if string(typed) != each.typed {
				t.Fatalf("typed %q into the seat, saying %q", typed, said.String())
			}
			if each.left != nil {
				if read(t, filepath.Join(dir, "run.json")) != before || state.Dict("own").Has(address) {
					t.Fatalf("handed to Python after writing: %s", run.Line(state))
				}
				return
			}
			after, _ := run.Read(dir)
			if !after.Truthy("merged") || after.Str("merge_note") != merged || after.Dict("health").Str("command") != "curl -fsS https://acme.example/health" ||
				after.Str("deployed") != "./deploy.sh" || !state.Dict("own").Dict(address).Truthy("done") {
				t.Fatalf("the merge was recorded as %s, followed as %s", run.Line(after), run.Line(state))
			}
			if result := read(t, filepath.Join(dir, "result.md")); !strings.Contains(result, merged) {
				t.Fatalf("result.md holds %q", result)
			}
			if each.typed != "" {
				if after.Has("merge_handback") || !strings.Contains(said.String(), "told the lead seat: "+merged) {
					t.Fatalf("a merge typed into its seat was kept as %s, saying %q", run.Line(after), said.String())
				}
				return
			}
			if after.Str("merge_handback") != notice || after.Str("handback_note") != "routine ending: recorded, not typed" || !after.Truthy("handed_back") {
				t.Fatalf("a routine merge's hand-back is %s", run.Line(after))
			}
		})
	}
}
