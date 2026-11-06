package handin

import (
	"os"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// File is a turn's record file in its out directory.
const File = "hand-in.jsonl"

// A Review is what a turn handed in, Python's hand_in.Review, its turn's row aside.
type Review struct {
	Records []*run.Object
	Handed  []any // the blocking findings handed to the turn, then the disputes
}

var closings = []string{"done", "blocked", "not-needed"}

func closing(kind string) bool {
	for _, each := range closings {
		if each == kind {
			return true
		}
	}
	return false
}

// Read is what that record file holds, as Python's hand_in.read reads it: false where there is no
// file, and nothing handed in where it does not hold what the loop opened it with and ak hand-in
// appends: a row of another role's kind, a closing before the last row, or a row that cannot be
// read as one.
func Read(path string) (*Review, bool) {
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil, false
	}
	empty := &Review{}
	if err != nil {
		return empty, true
	}
	var rows []*run.Object
	for _, line := range config.SplitLines(newlines(decoded(data))) {
		value, err := run.Decode([]byte(line))
		row, _ := value.(*run.Object)
		if err != nil || row == nil {
			return empty, true
		}
		rows = append(rows, row)
	}
	if len(rows) == 0 || rows[0].Str("kind") != "turn" {
		return empty, true
	}
	role := "reviewer"
	if rows[0].Has("role") {
		role = rows[0].Str("role")
	}
	records := rows[1:]
	for i, row := range records {
		kind := row.Str("kind")
		switch {
		case !allowed(role, kind), closing(kind) && i < len(records)-1:
			return empty, true
		case kind == "blocked" || kind == "not-needed":
			if blank(row.Str("why")) {
				return empty, true
			}
		case kind == "concede":
			if blank(row.Str("why")) || !sited(row) {
				return empty, true
			}
		case kind != "done" && !wellFormed(row):
			return empty, true
		}
	}
	return &Review{records, slices.Concat(rows[0].List("findings"), rows[0].List("disputes"))}, true
}

// allowed is whether a turn of that role hands in that kind of record.
func allowed(role, kind string) bool {
	switch {
	case strings.HasPrefix(role, "reviewer"):
		return kind == "finding" || kind == "follow-up" || kind == "concede" || kind == "done"
	case strings.HasPrefix(role, "fixer"):
		return kind == "dispute" || closing(kind)
	}
	return closing(kind)
}

// wellFormed is whether a finding, follow-up or dispute holds what its text is written from.
func wellFormed(row *run.Object) bool {
	if finding := row.Dict("finding"); row.Str("kind") == "dispute" && (finding == nil || !wellFormed(finding)) {
		return false
	}
	evidence := row.Dict("evidence")
	return sited(row) && row.Has("what") && row.Has("why") && evidence != nil &&
		(evidence.Has("quote") || evidence.Has("run") && evidence.Has("returncode") && evidence.Has("output"))
}

// Closing is the row that closed the turn, nil where none did.
func (r *Review) Closing() *run.Object {
	if len(r.Records) == 0 || !closing(r.Records[len(r.Records)-1].Str("kind")) {
		return nil
	}
	return r.Records[len(r.Records)-1]
}

// Done is whether the turn closed with done.
func (r *Review) Done() bool {
	found := r.Closing()
	return found != nil && found.Str("kind") == "done"
}

// Of is the records of that kind.
func (r *Review) Of(kind string) []*run.Object {
	var found []*run.Object
	for _, row := range r.Records {
		if row.Str("kind") == kind {
			found = append(found, row)
		}
	}
	return found
}

// Verdict is what a closed review says: FAIL for any finding, else PASS; "" unclosed.
func (r *Review) Verdict() string {
	switch {
	case !r.Done():
		return ""
	case len(r.Of("finding")) > 0:
		return "FAIL"
	}
	return "PASS"
}

// Notes is each note's text.
func (r *Review) Notes() []any {
	notes := []any{}
	for _, row := range r.Of("note") {
		notes = append(notes, itemText(row))
	}
	return notes
}

// Followups is each follow-up's text, each once.
func (r *Review) Followups() []any {
	items := []any{}
	seen := map[string]bool{}
	for _, row := range r.Of("follow-up") {
		if defect := defectOf(row); !seen[defect] {
			seen[defect] = true
			items = append(items, itemText(row))
		}
	}
	return items
}

// FollowupRecords is, by each follow-up's text, the command that can check its plan line, the
// commit it was proven to fail on, and the defect it names whichever head proved it, Python's
// Review.followup_checks, followup_commits and followup_defects.
func (r *Review) FollowupRecords() (checks, commits, defects *run.Object) {
	checks, commits, defects = run.NewObject(), run.NewObject(), run.NewObject()
	for _, row := range r.Of("follow-up") {
		item, evidence := itemText(row), row.Dict("evidence")
		if command := evidence.Str("run"); evidence.Has("run") && planCheck(command, "") {
			checks.Set(item, command)
		}
		if evidence.Has("commit") {
			commits.Set(item, evidence.Get("commit"))
		}
		defects.Set(item, defectOf(row))
	}
	return checks, commits, defects
}

// defectOf is what a follow-up names, without the proof's commit, exit status and output.
func defectOf(row *run.Object) string {
	evidence := row.Dict("evidence")
	proof := evidence.Get("run")
	if !evidence.Has("run") {
		proof = evidence.Get("quote")
	}
	return run.Line([]any{row.Get("path"), row.Get("line"), row.Get("what"), row.Get("why"), proof})
}

// Text is the review as review.md keeps it, Python's Review.text.
func (r *Review) Text() string {
	var parts []string
	if r.Done() {
		parts = append(parts, "VERDICT: "+r.Verdict())
	}
	for _, each := range [][2]string{{"finding", "Findings"}, {"follow-up", "Follow-ups"}, {"note", "Notes"}, {"dispute", "Disputes"}} {
		var items []string
		for _, row := range r.Of(each[0]) {
			items = append(items, "- "+strings.ReplaceAll(itemText(row), "\n", "\n  "))
		}
		if len(items) > 0 {
			parts = append(parts, "## "+each[1]+"\n"+strings.Join(items, "\n"))
		}
	}
	return strings.Join(parts, "\n\n") + "\n"
}

// ItemText is a record in words, Python's hand_in.item_text.
func ItemText(row *run.Object) string { return itemText(row) }

func itemText(row *run.Object) string {
	var text string
	if row.Str("kind") == "dispute" {
		finding := row.Dict("finding")
		text = itemText(finding) + "\nDispute: " + row.Str("why")
	} else {
		text = site(row) + " - " + row.Str("what") + " - " + row.Str("why")
	}
	evidence := row.Dict("evidence")
	if evidence.Has("quote") {
		text += "\nQuote:\n" + evidence.Str("quote")
	} else {
		text += "\n$ " + evidence.Str("run") + "\n"
		if evidence.Has("commit") {
			text += "Commit " + evidence.Str("commit") + ":\n"
		}
		text += proofText(evidence)
		if base := evidence.Dict("base"); base != nil {
			text += "\nBase " + base.Str("sha") + ":\n" + proofText(base)
		}
	}
	if row.Str("kind") == "finding" && row.Str("handed") == "follow-up" {
		text += "\nBlocking: its proof passes on base and fails on this commit, so this change caused it"
	}
	if row.Truthy("before") {
		text += "\nBefore the task: " + row.Str("before")
	}
	if row.Truthy("dropped") {
		text += "\nDropped follow-up: " + row.Str("dropped")
	}
	if row.Truthy("outside") {
		text += "\nOutside " + row.Str("outside")
	}
	if row.Truthy("replayed") {
		text += "\nRe-proven by ak on this commit: " + row.Str("replayed")
	}
	if row.Truthy("conceded") {
		text += "\nConceded: " + row.Str("conceded")
	}
	return strings.TrimFunc(text, config.Space)
}

// proofText is a proof's outcome and output, Python's hand_in.proof_text.
func proofText(proof *run.Object) string {
	code, _ := proof.Int("returncode")
	status := "exit " + strconv.Itoa(code)
	if proof.Truthy("killed") || code < 0 {
		status = "did not finish"
	}
	return "[" + status + "]\n" + proof.Str("output")
}

// ProofFailed is whether a proof ran and failed, Python's hand_in.proof_failed: an exit that says
// the command never started shows nothing, whatever its output reports.
func ProofFailed(proof *run.Object) bool {
	code, _ := proof.Int("returncode")
	return code > 0 && code != 126 && code != 127 && !proof.Truthy("killed")
}

// Answer is a file a turn wrote as Python reads its text with errors="replace", "" where there is
// none.
func Answer(path string) string {
	text, err := readText(path)
	if err != nil {
		return ""
	}
	return text
}
