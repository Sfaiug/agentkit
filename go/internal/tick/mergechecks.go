package tick

import (
	"cmp"
	"errors"
	"fmt"
	"net/url"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/run"
)

// A merge's live product is followed for three hours (watch.AFTER_MERGE_WINDOW), and one break
// per repository is handed back to fix, as Python's after_merge_checks does. Go reads what the
// runs recorded: a deployment to probe or revert, a declaration to read at the merge's commit, a
// probe to run and a pass still to tell its seat are Python's.
const mergeWindow = 3 * 3600

// A merge is one followed run as the merge checks read it, with its verdict: passed, failed,
// unknown where its commit cannot be read, or "" where nobody declared its health.
type merge struct {
	finished           float64
	name, pr, sha      string
	record             *run.Object
	verdict, check, at string // at: the failure's address and output, one typed line
}

var pullPath = regexp.MustCompile(`^/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$`)

// repoKey is the repository a pull request's address names, `host/owner/repo` in lower case
// (after_merge_repo); "" where it names none.
func repoKey(pr string) string {
	address, err := url.Parse(pr)
	if err != nil || address.Scheme != "https" || address.Hostname() == "" || address.User != nil ||
		address.RawQuery != "" || address.Fragment != "" {
		return ""
	}
	parts := pullPath.FindStringSubmatch(address.EscapedPath())
	if parts == nil {
		return ""
	}
	return strings.ToLower(address.Host + "/" + parts[1] + "/" + parts[2])
}

// inWindow is whether a merge is still watched: a late deployment gets a window of its own.
func inWindow(record *run.Object, now float64) bool {
	finished, _ := run.Num(record.Get("finished_at"))
	deployed, _ := dated(record, "deployed_at")
	return now-max(finished, deployed) < mergeWindow
}

// followed is the merge checks' key for a run they read, "" for one they do not: a dated merge
// inside its window, or past it with a failed probe kept, or a pass or deployment that bounds its
// episode.
func followed(record *run.Object, now float64) string {
	finished, ok := dated(record, "finished_at")
	if !record.Truthy("merged") || !ok || !(0 <= now-finished) || !inWindow(record, now) &&
		!healthOf(record).Has("output") && !record.Truthy("live_at") && !record.Truthy("deployed") {
		return ""
	}
	pr, _ := record.Get("pr").(string)
	return repoKey(pr)
}

func healthOf(record *run.Object) *run.Object { return cmp.Or(record.Dict("health"), run.NewObject()) }

// passedBefore is a pass past its window, told already: its episode's bound, with nothing to read.
func passedBefore(record *run.Object, now float64) bool {
	return !inWindow(record, now) && record.Truthy("live_at") && record.Truthy("live_notified") && !healthOf(record).Has("output")
}

// pythons is whether a followed merge needs what Go does not do: a deployment, a declaration to
// read at its commit (merge_record), a probe to run, or a pass still to be told.
func pythons(record *run.Object, now float64) bool {
	inside := inWindow(record, now)
	switch {
	case passedBefore(record, now):
		return false
	case record.Truthy("deployed") || record.Truthy("health") && record.Dict("health") == nil:
		return true
	case record.Truthy("live_at"):
		return !record.Truthy("live_notified")
	case inside && (!record.Has("health") || !record.Has("deployed")) && record.Truthy("repo"):
		return true
	}
	return inside && healthOf(record).Truthy("command")
}

// noMergeWork is a dry tick's read: no episode kept, and no merge but passes told before.
func noMergeWork() bool {
	state, ok := loadState()
	now := epoch(time.Now())
	return ok && len(state.Dict("after_merge").Keys()) == 0 && run.Every(func(_ string, record *run.Object) bool {
		return followed(record, now) == "" || passedBefore(record, now)
	})
}

// mergeChecks reads each followed merge's verdict off its run, keeping its commit there once,
// under the run's lock, and then each repository's break (breaks).
func (t *ticking) mergeChecks() error {
	now := epoch(t.clock())
	grouped := map[string][]*merge{}
	carried := run.Every(func(dir string, record *run.Object) bool {
		key := followed(record, now)
		if key != "" {
			finished, _ := dated(record, "finished_at")
			grouped[key] = append(grouped[key], &merge{finished: finished, name: filepath.Base(dir), pr: record.Str("pr"), record: record})
		}
		return key == "" || !pythons(record, now)
	})
	if !carried {
		return errLeft
	}
	keys := t.state.Dict("after_merge").Keys()
	for key := range grouped {
		keys = append(keys, key)
	}
	slices.Sort(keys)
	for _, key := range slices.Compact(keys) {
		found := grouped[key]
		slices.SortFunc(found, func(a, b *merge) int {
			return cmp.Or(cmp.Compare(a.finished, b.finished), strings.Compare(a.name, b.name))
		})
		for _, each := range found {
			if err := t.verdict(each, now); errors.Is(err, errLeft) {
				return err
			} else if err != nil && (each.record.Truthy("health") || each.record.Truthy("live_at")) {
				each.verdict = "unknown"
				t.log.line(fmt.Sprintf("WARN run %s's health could not be followed: %s", each.name, config.PyError(err)))
			}
		}
		if err := t.breaks(key, found, now); err != nil {
			return err
		}
	}
	return nil
}

// verdict is after_merge_health on what the run recorded.
func (t *ticking) verdict(each *merge, now float64) error {
	record := each.record
	if passedBefore(record, now) {
		each.sha, each.verdict = record.Str("merge_sha"), "passed"
		return nil
	}
	for _, key := range []string{"merge_sha", "merge_commit", "merge_commit_sha"} {
		if each.sha = strings.TrimSpace(record.Str(key)); each.sha != "" {
			break
		}
	}
	if each.sha == "" {
		value, why, err := gh.JSON(run.Runs(), "pr", "view", each.pr, "--json", "mergeCommit")
		if err != nil {
			return errLeft
		}
		if answer, ok := value.(*run.Object); ok && answer.Dict("mergeCommit") != nil {
			each.sha = strings.TrimSpace(answer.Dict("mergeCommit").Str("oid"))
		}
		if each.sha == "" {
			said := []rune(config.Fold(why))
			t.log.line(fmt.Sprintf("WARN %s: cannot read its merge commit: %s", each.pr, string(said[:min(len(said), 160)])))
			each.verdict = "unknown"
			return nil
		}
	}
	if record.Str("merge_sha") != each.sha {
		err := run.Change(filepath.Join(run.Runs(), each.name), func(current *run.Object) error {
			if current.Truthy("merged") && run.Equal(current.Get("finished_at"), record.Get("finished_at")) {
				current.Set("merge_sha", each.sha)
			}
			return nil
		})
		if err != nil {
			return err
		}
	}
	health := healthOf(record)
	switch command := run.Text(health.Get("command")); {
	case record.Truthy("live_at"):
		each.verdict = "passed"
	case health.Truthy("command"):
		// One typed line: a line break would reach the seat as Enter and send half of it.
		output := cmp.Or(health.Str("output"), "command exited nonzero without output")
		parts := []string{each.pr}
		for _, line := range config.SplitLines(output) {
			if strings.TrimFunc(line, config.Space) != "" {
				parts = append(parts, line)
			}
		}
		each.verdict, each.check, each.at = "failed", "health: "+command, strings.Join(parts, "; ")
	}
	return nil
}
