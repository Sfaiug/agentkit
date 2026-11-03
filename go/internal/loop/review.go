package loop

import (
	"cmp"
	"errors"
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

// review is the reviewer's turn on what the workplace holds and its verdict on the record, Python's
// review: whether it passed.  The author's summary is recorded, never handed to the reviewer, whom
// it would prime.
func (l *loop) review(summary string, ok bool, checked, preface string) (bool, error) {
	var j *judging
	since := ""
	if err := l.save(func(record *run.Object) {
		j = judgingFrom(record)
		// where this review began on its reviewer's session, kept from its first entry across a death
		if pending := record.Dict("review_pending"); pending != nil && pending.Has("since") {
			since = pending.Str("since")
		} else {
			since = reviewTurn(l.roundDir(), l.reviewSession, "")
		}
	}); err != nil {
		return false, err
	}
	if err := l.step("reviewer", "verdict", nil, "review", nil, "review_pending", run.Fields("round", l.rnd, "summary", summary,
		"since", since, "earlier", j.earlierList(), "failed", []any{})); err != nil {
		return false, err
	}
	passed, total := doneWhenCounts(checked, l.cmds)
	work, opening, heading, err := l.place.view(l, j, passed, total)
	if err != nil {
		return false, err
	}
	disputes, err := l.reviewDisputes(j)
	if err != nil {
		return false, err
	}
	heading += "\n"
	if len(l.once) > 0 {
		for _, cmd := range l.once {
			heading += "runs once at landing on the commit to be merged: " + cmd + "\n"
		}
		heading += "These run at landing; their absence here is by design and is never a finding.\n"
	}
	if flakyRecord.MatchString(checked) {
		heading += flakyRule + "\n"
	}
	body := func(section string) string {
		text := l.body + "\n\n" + section + "\n\n"
		if len(disputes.Records) > 0 {
			text += disputes.Text() + "\n"
		}
		text += heading + "```\n" + checked + "\n```"
		if preface != "" {
			text = preface + "\n\n" + text
		}
		return opening + text
	}
	l.say(fmt.Sprintf("--- round %d: reviewer %s", l.rnd, l.reviewer))
	// a review cut off goes on where it was: a reviewer that took it over wrote in its own directory
	name, _, _ := openReview(l.roundDir())
	name = cmp.Or(name, "reviewer")
	if other := l.another(); other != "" {
		l.say(fmt.Sprintf("reviewer %s has room: %s does not review its own work", other, l.reviewer))
		l.reviewer, l.reviewSession, name = other, "", "reviewer-"+other
		if err := l.save(func(record *run.Object) { run.SetAll(record, "reviewer", other, "review_session", nil) }); err != nil {
			return false, err
		}
	}
	// a conversation that resumes holds the whole change already; one that starts fresh gets it too
	whole := body(work)
	if j.whole != "" {
		whole = body(j.whole + "\n\n" + work)
	}
	ask, err := l.goOn(name, "reviewer", whole, l.reviewSession)
	if err != nil {
		return false, err
	}
	if ask.body == whole && ask.session != "" {
		ask.body = body(work)
	}
	if ask.previous == "" && ask.cut == "" {
		// a turn that handed in before the driver died hands on what it found: its `done` alone is no verdict
		if turn := reviewTurn(l.roundDir(), ask.session, since); turn != "" {
			ask.previous = filepath.Join(turn, handin.File)
		}
	}
	l.reviewSession = ask.session
	if err := l.notice(ask); err != nil {
		return false, err
	}
	model, err := l.model(l.reviewer)
	if err != nil {
		return false, err
	}
	out := ask.out
	var session string
	err = l.place.inCopy(l, out, func(cwd string) error {
		told, at := ask.body, l.workspace
		if cwd != "" {
			told, at = strings.ReplaceAll(told, config.Resolve(l.workspace), cwd), cwd
		}
		var failed error
		session, failed = l.turn(at, l.reviewer, model, "reviewer", l.place.role("reviewer"), told, out, ask.session, j.listed, ask.previous)
		return failed
	})
	var failed *exited
	if err != nil && !errors.As(err, &failed) {
		return false, err
	}
	if session != "" {
		l.reviewSession = session
	}
	if err := l.save(func(record *run.Object) { record.Set("review_session", none(l.reviewSession)) }); err != nil {
		return false, err
	}
	submitted, _ := handin.Read(filepath.Join(out, handin.File))
	code := 0
	if failed != nil {
		code = failed.code
		// one killed, or with nothing handed in, gave no verdict; one that exited with its verdict did
		if code < 0 || submitted == nil || !submitted.Done() {
			return false, err
		}
		l.say(fmt.Sprintf("WARN reviewer exited %d; see %s", code, filepath.Join(out, "stderr.log")))
	}
	if submitted == nil || !submitted.Done() {
		return false, notYet(fmt.Sprintf("reviewer %s gave no verdict; see %s", l.reviewer, filepath.Join(out, "stderr.log")), "a silent turn")
	}
	weighed, err := l.weigh(submitted, j)
	if err != nil {
		return false, err
	}
	dropped, err := l.dropped(j, disputes, weighed)
	if err != nil {
		return false, err
	}
	return l.record(summary, out, model, weighed, code, ok, checked, dropped)
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

// weigh is the review as ak holds it, Python's weigh_review: the reviewer's copy cannot decide what
// blocks.  A record whose kind this changes keeps the one handed in as `handed`.
func (l *loop) weigh(submitted *handin.Review, j *judging) (*handin.Review, error) {
	var records []*run.Object
	for index, row := range submitted.Records {
		was := row.Str("kind")
		if was != "finding" && was != "follow-up" {
			records = append(records, row)
			continue
		}
		weighed, err := l.place.weigh(l, row, index, j)
		if err != nil {
			return nil, err
		}
		if weighed.Str("kind") != was {
			weighed.Set("handed", was)
		}
		records = append(records, weighed)
	}
	return &handin.Review{Records: l.withReplays(records, j)}, nil
}

// record puts the verdict on the record: review.md and findings.json beside the reviewer's turn,
// the round's summary and the evidence delivery is decided on: whether it passed.  What the
// reviewer passed the loop fails where its turn exited non-zero, a check is failing, or the checkout
// moved after verification.
func (l *loop) record(summary, out string, reviewed config.Model, submitted *handin.Review, code int, ok bool, checked string, dropped []any) (bool, error) {
	verdict := submitted.Verdict()
	overridden := ""
	if code != 0 && verdict == "PASS" {
		verdict, overridden = "FAIL", fmt.Sprintf("the reviewer said PASS but exited %d", code)
		l.say("WARN " + overridden + "; overriding to FAIL")
	}
	if !ok && verdict == "PASS" {
		parts := []string{"the reviewer said PASS while done-when is failing"}
		for _, line := range config.SplitLines(checked) {
			if loopNote.MatchString(line) {
				parts = append(parts, line)
			}
		}
		verdict, overridden = "FAIL", strings.Join(parts, "; ")
		l.say("WARN " + overridden + "; overriding to FAIL")
	}
	verdict, evidence, err := l.place.judged(l, verdict)
	if err != nil {
		return false, err
	}
	text := submitted.Text()
	report := filepath.Join(out, "review.md")
	if err := os.WriteFile(report, []byte(text), 0o666); err != nil {
		return false, err
	}
	findings := make([]any, 0)
	for _, row := range submitted.Of("finding") {
		findings = append(findings, row)
	}
	if err := os.WriteFile(filepath.Join(out, "findings.json"), []byte(run.Line(findings)), 0o666); err != nil {
		return false, err
	}
	records := make([]any, 0, len(submitted.Records))
	for _, row := range submitted.Records {
		records = append(records, row)
	}
	// a review of somebody else's PR has no executor, nor its provider
	var executedOn any
	if l.executor != "" {
		executed, err := l.model(l.executor)
		if err != nil {
			return false, err
		}
		executedOn = executed.Provider
	}
	tail := []rune(strings.TrimFunc(text, config.Space))
	entry := run.Fields("round", l.rnd, "verdict", verdict, "done_when", ok, "finding_count", len(findings),
		"summary", strings.TrimFunc(summary, config.Space))
	review := run.Fields("executor", none(l.executor), "executor_provider", executedOn, "reviewer", l.reviewer,
		"reviewer_provider", reviewed.Provider, "returncode", code, "verdict", verdict, "done_when", ok)
	run.SetAll(entry, evidence...)
	run.SetAll(review, evidence...)
	entry.Delete("overridden")
	if overridden != "" && !review.Has("overridden") {
		review.Set("overridden", overridden)
	}
	checks, commits, defects := submitted.FollowupRecords()
	err = l.save(func(record *run.Object) {
		record.Set("round_summaries", append(record.List("round_summaries"), entry))
		run.SetAll(record, "findings", string(tail[max(0, len(tail)-8000):]), "findings_file", report,
			"review_records", records, "notes", submitted.Notes())
		keepFollowups(record, checks, commits, defects)
		run.SetAll(record, "verdict", verdict, "review", review)
		if verdict == "PASS" {
			// each flaky check's evidence stays with the review that passed over it
			kept := record.List("followups")
			for _, part := range strings.Split(checked, "\n\n") {
				if strings.HasPrefix(part, "flaky: ") && !slices.Contains(kept, any(part)) {
					kept = append(kept, part)
				}
			}
			record.Set("followups", kept)
		}
		kept := record.List("disputes")
		for _, each := range dropped {
			if !slices.Contains(kept, each) {
				kept = append(kept, each)
			}
		}
		if len(kept) > 0 {
			record.Set("disputes", kept)
		}
		record.Delete("dispute_files")
		record.Delete("review_pending")
	})
	if err != nil {
		return false, err
	}
	l.findings, l.findingsFile = text, report
	l.say(fmt.Sprintf("round %d verdict: %s", l.rnd, verdict))
	return verdict == "PASS", nil
}

// followupKeys are what a record keeps of its follow-ups by each one's text.
var followupKeys = []string{"followup_checks", "followup_commits", "followup_defects"}

// keepFollowups adds a review's follow-ups to the record's, each defect once, whichever round proved
// it: the same one handed in again on a later head differs only in its proof, and the first stays.
func keepFollowups(record, checks, commits, defects *run.Object) {
	known := map[string]bool{}
	if held := record.Dict("followup_defects"); held != nil {
		for _, key := range held.Keys() {
			known[held.Str(key)] = true
		}
	}
	kept := append([]any{}, record.List("followups")...)
	merged := make([]*run.Object, len(followupKeys))
	for i, key := range followupKeys {
		if merged[i] = record.Dict(key); merged[i] == nil {
			merged[i] = run.NewObject()
		}
	}
	for _, item := range defects.Keys() {
		if known[defects.Str(item)] {
			continue
		}
		known[defects.Str(item)] = true
		kept = append(kept, item)
		for i, found := range []*run.Object{checks, commits, defects} {
			if found.Has(item) {
				merged[i].Set(item, found.Get(item))
			}
		}
	}
	record.Set("followups", kept)
	for i, key := range followupKeys {
		record.Set(key, merged[i])
	}
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
