package loop

import (
	"fmt"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// A workplace is where a run's work is done and all that follows from where: the one home of how
// a scratch run and a repository's differ.  Python's are `lp.scratch` branches through its stages.
type workplace interface {
	// open makes the place and puts it on the record with the fields every run writes.
	open(l *loop, meta map[string]string, path string, common []any) error
	// reopen goes back to the place a record names.
	reopen(l *loop, record *run.Object) error
	// where opens the prompt, and rules are what the place's own rules add to a task's body.
	where(l *loop) string
	rules() string
	// landing is whether the run lands, and the suite that then runs once.
	landing() (bool, string)
	// role is the rules a turn of that word takes.
	role(word string) string
	// doneChecks is what a builder's done holds a turn of that word to.
	doneChecks(l *loop, word string) *run.Object
	// beforeTurn readies the place for a worker, worked follows the executor's turn.
	beforeTurn(l *loop)
	worked(l *loop) error
	// verify runs the round's checks on what the place holds: whether they passed, what they said.
	verify(l *loop, path string) (bool, string, error)
	// beforeReview is the last word before the reviewer is told anything.
	beforeReview(l *loop) error
	// baseProof starts the base proof beside the review where ok and the record owes one, nil otherwise.
	baseProof(l *loop, ok bool) (*besideReview, error)
	// view is what a reviewer is shown, what opens its text, and how its checks' heading reads, of
	// which passed of total commands exited 0: it says on j what a later round's review reads.
	view(l *loop, j *judging, passed, total int) (section, checks, heading string, err error)
	// inCopy runs a reviewer's turn where its edits reach nothing.
	inCopy(l *loop, out string, turn func(cwd string) error) error
	// weigh is one finding or follow-up as ak holds it.
	weigh(l *loop, row *run.Object, index int, j *judging) (*run.Object, error)
	// prove replays a command on the work under review, its evidence as a record holds it.
	prove(l *loop, command, path string) (*run.Object, error)
	// moved is the lines where a line of path can stand now, since that commit, and whether the
	// change since touched it.
	moved(path string, line int, since string) ([]int, bool, error)
	// judged is the verdict as the place lets it stand, and what it adds to the evidence.
	judged(l *loop, verdict string) (string, []any, error)
	// held is whether the place still holds what the round's checks ran on, and that as evidence.
	held() (bool, []any, error)
	// finished follows a PASS.
	finished(l *loop) error
	// head is what opens a result of the run the record describes.
	head(dir string, record *run.Object) []string
}

// placeOf is the workplace a record describes, for what reads a run from outside its driver.
func placeOf(record *run.Object) workplace {
	if record.Truthy("own_pr") {
		return &ownPull{pullFrom(record)}
	}
	if record.Truthy("review_pr") {
		return pullFrom(record)
	}
	if record.Truthy("scratch") || !record.Truthy("repo") {
		return scratch{}
	}
	return repoFrom(record)
}

// scratch is a directory of a run's own: whatever it leaves there is the delivery.  files is the
// task's `files:`, which its turns' checks name as Python's do.
type scratch struct{ files []string }

func (scratch) open(l *loop, _ map[string]string, _ string, common []any) error {
	l.workspace = filepath.Join(config.Home(), "work", l.id)
	if err := os.MkdirAll(l.workspace, 0o777); err != nil {
		return err
	}
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "repo", nil, "scratch", true, "base", nil, "target", nil, "base_sha", nil, "branch", nil,
			"worktree", l.workspace, "no_merge", true, "base_proof", nil)
		run.SetAll(record, common...)
	}); err != nil {
		return err
	}
	l.say(fmt.Sprintf("scratch workspace %s: no repository, so no branch, no PR and no merge", l.workspace))
	return nil
}

func (scratch) reopen(l *loop, record *run.Object) error {
	l.workspace = record.Str("worktree")
	l.sayResuming("")
	return nil
}

func (scratch) where(l *loop) string {
	return "Workspace: " + l.workspace + "\nThere is no git repository here: nothing to commit, no branch and no PR. What you leave in the workspace is the deliverable."
}

func (scratch) rules() string { return "" }

func (scratch) landing() (bool, string) { return false, "" }

func (scratch) role(word string) string { return word + "-scratch" }

func (scratch) beforeTurn(*loop) {}

func (scratch) worked(*loop) error { return nil }

// verify is the round's checks in the workspace, beside the rules a workspace has none of.
func (scratch) verify(l *loop, path string) (bool, string, error) {
	if _, err := l.rulesOn(""); err != nil {
		return false, "", err
	}
	return l.checks(l.every, path)
}

func (scratch) beforeReview(*loop) error { return nil }

// baseProof is none: a scratch run has no base to prove on.
func (scratch) baseProof(*loop, bool) (*besideReview, error) { return nil, nil }

func (scratch) view(l *loop, _ *judging, passed, total int) (string, string, string, error) {
	return fmt.Sprintf("## Workspace (%s)\n```\n%s\n```", l.workspace, listing(l.workspace)), "",
		fmt.Sprintf("## Done-when output (run by the loop; %d of %d commands exited 0)", passed, total), nil
}

func (scratch) prove(l *loop, command, path string) (*run.Object, error) {
	return l.proof(command, path)
}

// moved is the line itself: a scratch run has no commits to read a fix from.
func (scratch) moved(_ string, line int, _ string) ([]int, bool, error) {
	return []int{line}, false, nil
}

func (scratch) inCopy(_ *loop, _ string, turn func(string) error) error { return turn("") }

// weigh is Python's weigh_review on a scratch run: a finding handed in with a quote is a note, as
// is one whose command does not fail when ak runs it; a follow-up has no base to be proven on, so
// it is a note too.
func (scratch) weigh(l *loop, row *run.Object, index int, _ *judging) (*run.Object, error) {
	weighed := row.Copy()
	switch {
	case row.Str("kind") == "follow-up":
		weighed.Set("kind", "note")
		weighed.Set("dropped", "no base commit")
		l.say(fmt.Sprintf("Dropped follow-up %s:%v: no base commit", row.Str("path"), row.Get("line")))
	case row.Dict("evidence").Has("quote"):
		weighed.Set("kind", "note")
	default:
		proof, err := l.proof(row.Dict("evidence").Str("run"), filepath.Join(l.roundDir(), fmt.Sprintf("proof-%d-commit.log", index+1)))
		if err != nil {
			return nil, err
		}
		weighed.Set("evidence", proof)
		if !handin.ProofFailed(proof) {
			weighed.Set("kind", "note")
		}
	}
	return weighed, nil
}

func (scratch) judged(_ *loop, verdict string) (string, []any, error) { return verdict, nil, nil }

func (scratch) finished(*loop) error { return nil }

func (scratch) head(_ string, record *run.Object) []string {
	workspace := record.Str("worktree")
	return []string{"workspace: " + workspace,
		"executor: " + run.Field(record, "executor", "None") + "   reviewer: " + reviewedBy(record),
		"", "## Deliverables", links(workspace)}
}
