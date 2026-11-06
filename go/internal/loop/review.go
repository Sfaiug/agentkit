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
		pending := record.Dict("review_pending")
		// where this review began on its reviewer's session, kept from its first entry across a death
		if pending != nil && pending.Has("since") {
			since = pending.Str("since")
		} else {
			since = reviewTurn(l.roundDir(), l.reviewSession, "")
		}
		if pending != nil && pending.Get("record") == false {
			// the repair that brought it here is nobody's fix round: the whole change is judged again
			j.uncounted, j.passed = true, passedReviewHead(record)
		}
	}); err != nil {
		return false, err
	}
	pending := run.Fields("round", l.rnd, "summary", summary, "since", since, "earlier", j.earlierList(), "failed", []any{})
	if j.uncounted {
		pending.Set("record", false)
	}
	if err := l.step("reviewer", "verdict", nil, "review", nil, "review_pending", pending); err != nil {
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
	decided, err := decidedSection(l.dir)
	if err != nil {
		return false, err
	}
	body := func(section string) string {
		text := l.body + "\n\n" + decided + section + "\n\n"
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
	var (
		submitted *handin.Review
		reviewed  config.Model
		done      *try
		asking    string // the record file of the answer that gave no verdict, for the call asking once more
	)
	for {
		asked := asking != ""
		turn := ask{body: noVerdictAsk, out: freeDir(l.roundDir(), name), session: l.reviewSession, previous: asking}
		asking = ""
		if !asked {
			if turn, err = l.goOn(name, "reviewer", whole, l.reviewSession); err != nil {
				return false, err
			}
			if turn.body == whole && turn.session != "" {
				turn.body = body(work)
			}
			if turn.previous == "" && turn.cut == "" {
				// a turn that handed in before the driver died hands on what it found: its `done` alone is no verdict
				if prior := reviewTurn(l.roundDir(), turn.session, since); prior != "" {
					turn.previous = filepath.Join(prior, handin.File)
				}
			}
		}
		l.reviewSession = turn.session
		if err := l.notice(turn); err != nil {
			return false, err
		}
		if reviewed, err = l.model(l.reviewer); err != nil {
			return false, err
		}
		c := &call{l: l, name: l.reviewer, role: l.place.role("reviewer"), model: reviewed, body: turn.body, fresh: whole, out: turn.out, session: turn.session,
			findings: j.listed, previous: turn.previous, notice: turn.shown, copied: true, handover: l.reviewerHandover(turn.out)}
		var failed error
		done, failed = c.run()
		var broken *cannotRun
		var refused *ranDry
		var handed *handedOver
		switch {
		case errors.As(failed, &handed):
			name = handed.next
			continue
		case errors.As(failed, &broken):
			// the fallback road; with no reviewer left, the run is blocked on the harness's own line
			next, err := l.fallBack(broken.detail(), turn.out, true, false)
			if tired := (*exhausted)(nil); errors.As(err, &tired) {
				return false, failed
			}
			if err != nil {
				return false, err
			}
			name = next
			continue
		case errors.As(failed, &refused):
			// a spent window takes the same road out: the next marked reviewer, as the meters stand now
			if refused.code != 0 {
				l.say(fmt.Sprintf("WARN reviewer %s; see %s", cmp.Or(killedWord(refused.code), fmt.Sprintf("exited %d", refused.code)), filepath.Join(turn.out, "stderr.log")))
			}
			if err := l.saveSession(&l.reviewSession, c.session, "review_session"); err != nil {
				return false, err
			}
			if err := l.giveUp(refused.out); err != nil {
				return false, err
			}
			if name, err = l.fallBack("ran dry", turn.out, true, true); err != nil {
				return false, err
			}
			continue
		case failed != nil:
			// the parked or killed conversation is on the record before the run parks
			if err := l.saveSession(&l.reviewSession, c.session, "review_session"); err != nil {
				return false, err
			}
			return false, failed
		}
		if done.code != 0 {
			l.say(fmt.Sprintf("WARN reviewer %s; see %s", cmp.Or(killedWord(done.code), fmt.Sprintf("exited %d", done.code)), filepath.Join(turn.out, "stderr.log")))
		}
		if err := l.saveSession(&l.reviewSession, c.session, "review_session"); err != nil {
			return false, err
		}
		submitted, _ = handin.Read(filepath.Join(done.out, handin.File))
		if submitted != nil && submitted.Done() {
			break
		}
		// a missing verdict is a reviewer that has not answered, never an answer: its session is
		// asked once more.
		if asked {
			if err := l.giveUp(done.out); err != nil {
				return false, err
			}
			if name, err = l.fallBack("gave no verdict twice", turn.out, true, false); err != nil {
				return false, err
			}
			continue
		}
		l.say(fmt.Sprintf("reviewer %s gave no verdict; asking once more", l.reviewer))
		asking = filepath.Join(done.out, handin.File)
	}
	weighed, err := l.weigh(submitted, j)
	if err != nil {
		return false, err
	}
	dropped, err := l.dropped(j, disputes, weighed)
	if err != nil {
		return false, err
	}
	return l.record(summary, done.out, reviewed, weighed, done.code, ok, checked, dropped, j)
}

// giveUp keeps what a reviewer that gave no verdict said, on the record for whoever reads it next.
func (l *loop) giveUp(out string) error {
	submitted, _ := handin.Read(filepath.Join(out, handin.File))
	if submitted == nil {
		submitted = &handin.Review{}
	}
	kept, err := l.keepFindings(out, submitted)
	if err != nil {
		return err
	}
	return l.save(func(record *run.Object) { run.SetAll(record, kept...) })
}

// another is the marked reviewer to take over from a writer about to review its own work: one
// reviews itself only while no other has room, and that is read as the meters stand now.
func (l *loop) another() string {
	record, _ := run.Read(l.dir)
	rules, ok := l.rules()
	if record == nil || !ok || !rules.Wrote(l.reviewer, headWriters(record)) {
		return ""
	}
	if _, offered, _ := l.readyReviewers(nil); len(offered) > 0 {
		return offered[0]
	}
	return ""
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
// the round's summary unless the review spends no round, and the evidence delivery is decided on:
// whether it passed.  What the reviewer passed the loop fails where its turn exited non-zero, a
// check is failing, or the checkout moved after verification.
func (l *loop) record(summary, out string, reviewed config.Model, submitted *handin.Review, code int, ok bool, checked string, dropped []any, j *judging) (bool, error) {
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
	said, err := l.keepFindings(out, submitted)
	if err != nil {
		return false, err
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
	entry := run.Fields("round", l.rnd, "verdict", verdict, "done_when", ok, "finding_count", len(submitted.Of("finding")),
		"summary", strings.TrimFunc(summary, config.Space))
	review := run.Fields("executor", none(l.executor), "executor_provider", executedOn, "reviewer", l.reviewer,
		"reviewer_provider", reviewed.Provider, "returncode", code, "verdict", verdict, "done_when", ok)
	run.SetAll(entry, evidence...)
	run.SetAll(review, evidence...)
	if j.uncounted && len(l.once) > 0 {
		// checks deferred to landing have not run on this head yet: the task's checks last passed
		// on the head they did
		review.Delete("passed_head_sha")
		if j.passed != "" {
			review.Set("passed_head_sha", j.passed)
		}
	}
	entry.Delete("overridden")
	if overridden != "" && !review.Has("overridden") {
		review.Set("overridden", overridden)
	}
	checks, commits, defects := submitted.FollowupRecords()
	err = l.save(func(record *run.Object) {
		if !j.uncounted {
			record.Set("round_summaries", append(record.List("round_summaries"), entry))
		}
		run.SetAll(record, said...)
		record.Set("notes", submitted.Notes())
		keepFollowups(record, checks, commits, defects)
		run.SetAll(record, "verdict", verdict, "review", review)
		if verdict == "PASS" {
			keepFlakes(record, checked)
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

// keepFlakes keeps each flaky check's evidence in the checks' text with the review that passed
// over it, Python's record_flakes.
func keepFlakes(record *run.Object, text string) {
	kept := record.List("followups")
	for _, part := range strings.Split(text, "\n\n") {
		if strings.HasPrefix(part, "flaky: ") && !slices.Contains(kept, any(part)) {
			kept = append(kept, part)
		}
	}
	record.Set("followups", kept)
}
