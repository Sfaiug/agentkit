package run

import (
	"cmp"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var conflictNote = regexp.MustCompile(`(?i)conflict|did not finish the (?:rebase|merge)`)
var conflictRef = regexp.MustCompile(`(?:rebase|merge) of ([^\s;]+)`)

// ConflictUpstream names what integration tripped over, as transitions.conflict_upstream does.
func ConflictUpstream(record *Object) string {
	if match := conflictRef.FindStringSubmatch(record.Str("merge_note")); match != nil {
		return match[1]
	}
	return "origin/" + cmp.Or(record.Str("base"), "main")
}

func integrationFailure(dir string, record *Object) bool {
	if state := record.Str("state"); state != "fail" && state != "waiting" || record.Truthy("review_pr") || !isDir(worktree(record)) {
		return false
	}
	for _, key := range []string{"branch", "base", "base_sha", "rounds", "merge_note"} {
		if !record.Truthy(key) {
			return false
		}
	}
	log, err := os.ReadFile(filepath.Join(dir, "log.txt"))
	return err == nil && strings.Contains(string(log), "not merged:")
}

// ParkableConflict is Python's parkable_conflict: only untold integration failures with rounds left.
func ParkableConflict(dir string, record *Object, now time.Time) bool {
	rounds, _ := record.Int("rounds")
	return !record.Truthy("job_id") && conflictNote.MatchString(record.Str("merge_note")) &&
		len(record.List("round_summaries")) < rounds && TickAdmission(record, now) != "" && integrationFailure(dir, record)
}

// IntegrationNote distinguishes an aborted integration from a tree a reviewer failed.
func IntegrationNote(dir string, record *Object) bool {
	summaries := record.List("round_summaries")
	var last *Object
	if len(summaries) > 0 {
		last, _ = summaries[len(summaries)-1].(*Object)
	}
	return !judged(last) && !judged(record.Dict("review")) && integrationFailure(dir, record)
}
