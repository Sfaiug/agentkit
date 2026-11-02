package loop

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

// listCap is how many files a reviewer is shown before it is told the count.
const listCap = 500

const flakyRule = "A `flaky:` record is ak's own rule, not a weakened check: a done-when command that fails runs once more at once, and it passes if that re-run does."

var flakyRecord = regexp.MustCompile(`(?m)^flaky: `)

// review is the reviewer's turn on what the workspace holds and its verdict on the record, Python's
// review on a scratch run in its first round.  A FAIL is recorded, and its fixer round is a road Go
// does not carry out.  The author's summary is recorded, never handed to the reviewer, whom it
// would prime.
func (l *loop) review(summary, checked string) error {
	if err := l.step("reviewer", "verdict", nil, "review", nil, "review_pending", run.Fields("round", 1, "summary", summary,
		"since", "", "earlier", []any{}, "failed", []any{})); err != nil {
		return err
	}
	work := fmt.Sprintf("## Workspace (%s)\n```\n%s\n```", l.workspace, listing(l.workspace))
	heading := fmt.Sprintf("## Done-when output (run by the loop; %d of %d commands exited 0)\n", len(l.every), len(l.every))
	if flakyRecord.MatchString(checked) {
		heading += flakyRule + "\n"
	}
	body := l.body + "\n\n" + work + "\n\n" + heading + "```\n" + checked + "\n```"
	l.say("--- round 1: reviewer " + l.reviewer)
	name := "reviewer"
	if other := l.another(); other != "" {
		l.say(fmt.Sprintf("reviewer %s has room: %s does not review its own work", other, l.reviewer))
		l.reviewer, name = other, "reviewer-"+other
		if err := l.save(func(record *run.Object) { run.SetAll(record, "reviewer", other, "review_session", nil) }); err != nil {
			return err
		}
	}
	model, err := l.model(l.reviewer)
	if err != nil {
		return err
	}
	out := filepath.Join(l.dir, roundName, name)
	session, err := l.turn(l.reviewer, model, "reviewer", "reviewer-scratch", body, out)
	if err != nil {
		return err
	}
	if err := l.save(func(record *run.Object) { record.Set("review_session", session) }); err != nil {
		return err
	}
	submitted, _ := handin.Read(filepath.Join(out, handin.File))
	if submitted == nil || !submitted.Done() {
		return notYet(fmt.Sprintf("reviewer %s gave no verdict; see %s", l.reviewer, filepath.Join(out, "stderr.log")), "a silent turn")
	}
	weighed, err := l.weigh(submitted)
	if err != nil {
		return err
	}
	return l.record(summary, out, model, weighed)
}

// another is the marked reviewer to take over from a writer about to review its own work: one
// reviews itself only while no other has room, and that is read as the meters stand now.
func (l *loop) another() string {
	rules, ok := l.rules()
	if !ok || !rules.Same(l.executor, l.reviewer) {
		return ""
	}
	readings, err := usage.Read()
	if err != nil {
		return ""
	}
	return rules.Independent(withRoom(readings), l.executor)
}

// weigh is the review as ak holds it, Python's weigh_review on a scratch run: the reviewer's copy
// cannot decide what blocks.  A finding handed in with a quote is a note, as is one whose command
// does not fail when ak runs it; a follow-up has no base to be proven on, so it is a note too.
func (l *loop) weigh(submitted *handin.Review) (*handin.Review, error) {
	var records []*run.Object
	for index, row := range submitted.Records {
		was := row.Str("kind")
		if was != "finding" && was != "follow-up" {
			records = append(records, row)
			continue
		}
		weighed := row.Copy()
		switch {
		case was == "follow-up":
			weighed.Set("kind", "note")
			weighed.Set("dropped", "no base commit")
			l.say(fmt.Sprintf("Dropped follow-up %s:%v: no base commit", row.Str("path"), row.Get("line")))
		case row.Dict("evidence").Has("quote"):
			weighed.Set("kind", "note")
		default:
			command := row.Dict("evidence").Str("run")
			proof, err := l.proof(command, filepath.Join(l.dir, roundName, fmt.Sprintf("proof-%d-commit.log", index+1)))
			if err != nil {
				return nil, err
			}
			weighed.Set("evidence", proof)
			if !handin.ProofFailed(proof) {
				weighed.Set("kind", "note")
			}
		}
		if weighed.Str("kind") != was {
			weighed.Set("handed", was)
		}
		records = append(records, weighed)
	}
	return &handin.Review{Records: records}, nil
}

// record puts the verdict on the record: review.md and findings.json beside the reviewer's turn,
// the round's summary and the evidence delivery is decided on.  A FAIL ends here.
func (l *loop) record(summary, out string, reviewed config.Model, submitted *handin.Review) error {
	verdict := submitted.Verdict()
	text := submitted.Text()
	report := filepath.Join(out, "review.md")
	if err := os.WriteFile(report, []byte(text), 0o666); err != nil {
		return err
	}
	findings := make([]any, 0)
	for _, row := range submitted.Of("finding") {
		findings = append(findings, row)
	}
	if err := os.WriteFile(filepath.Join(out, "findings.json"), []byte(run.Line(findings)), 0o666); err != nil {
		return err
	}
	records := make([]any, 0, len(submitted.Records))
	for _, row := range submitted.Records {
		records = append(records, row)
	}
	executed, err := l.model(l.executor)
	if err != nil {
		return err
	}
	tail := []rune(strings.TrimFunc(text, config.Space))
	followups := []any{}
	if verdict == "PASS" {
		// each flaky check's evidence stays with the review that passed over it
		checked, _ := os.ReadFile(filepath.Join(l.dir, roundName, "donewhen.log"))
		for _, part := range strings.Split(string(checked), "\n\n") {
			if strings.HasPrefix(part, "flaky: ") {
				followups = append(followups, part)
			}
		}
	}
	err = l.save(func(record *run.Object) {
		record.Set("round_summaries", append(record.List("round_summaries"), run.Fields(
			"round", 1, "verdict", verdict, "done_when", true, "finding_count", len(findings),
			"summary", strings.TrimFunc(summary, config.Space))))
		run.SetAll(record, "findings", string(tail[max(0, len(tail)-8000):]), "findings_file", report,
			"review_records", records, "notes", submitted.Notes(), "followups", followups,
			"followup_checks", run.NewObject(), "followup_commits", run.NewObject(), "followup_defects", run.NewObject(),
			"verdict", verdict,
			"review", run.Fields("executor", l.executor, "executor_provider", executed.Provider, "reviewer", l.reviewer,
				"reviewer_provider", reviewed.Provider, "returncode", 0, "verdict", verdict, "done_when", true))
		record.Delete("review_pending")
	})
	if err != nil {
		return err
	}
	l.say("round 1 verdict: " + verdict)
	if verdict != "PASS" {
		return notYet("round 1 verdict: "+verdict, "a FAIL verdict's fixer round")
	}
	return nil
}

// files is every file under root by its path there, a dangling link among them, in Python's
// sorted order of paths: part by part.
func files(root string) []string {
	var found []string
	filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || path == root {
			return nil
		}
		if info, err := os.Stat(path); err == nil && info.IsDir() {
			return nil // a link to a folder is no file, and is not walked into
		}
		relative, _ := filepath.Rel(root, path)
		found = append(found, relative)
		return nil
	})
	slices.SortFunc(found, func(a, b string) int {
		return slices.Compare(strings.Split(a, string(filepath.Separator)), strings.Split(b, string(filepath.Separator)))
	})
	return found
}

// listing is every file in the workspace with its size: what a scratch run has instead of a diff,
// Python's gitcall.listing.
func listing(root string) string {
	found := files(root)
	var rows []string
	for _, relative := range found[:min(len(found), listCap)] {
		var size int64
		if info, err := os.Stat(filepath.Join(root, relative)); err == nil {
			size = info.Size()
		}
		rows = append(rows, fmt.Sprintf("%10d  %s", size, relative))
	}
	if len(found) > listCap {
		rows = append(rows, fmt.Sprintf("... and %d more files", len(found)-listCap))
	}
	if len(rows) == 0 {
		return "(the workspace is empty)"
	}
	return strings.Join(rows, "\n")
}
