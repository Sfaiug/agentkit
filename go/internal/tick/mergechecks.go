package tick

import (
	"cmp"
	"fmt"
	"slices"
	"strings"
	"time"

	"agentkit/internal/gh"
	"agentkit/internal/run"
)

const mergeWindow = 3 * 3600

func followsMerge(record *run.Object, now float64) bool {
	finished, dated := dated(record, "finished_at")
	if !record.Truthy("merged") || !dated || !(0 <= now-finished) || !record.Truthy("pr") {
		return false
	}
	health := record.Dict("health")
	return now-finished <= mergeWindow || health != nil && health.Has("output") || record.Truthy("live_at") && !record.Truthy("live_notified")
}

// A dry tick does not ask GitHub for a merge's commit or checks.
func noMergeWork() bool {
	return run.Every(func(_ string, record *run.Object) bool { return !followsMerge(record, epoch(time.Now())) })
}

// Merge checks read the merge's commit and check runs, just as after_merge_checks does. A
// health probe, untold live notice or failed check is Python's; green and pending checks
// need no action. The commit is kept once, under the run's lock, as after_merge_health keeps it.
func (t *ticking) mergeChecks() error {
	var failed error
	carried := run.Every(func(dir string, record *run.Object) bool {
		if !followsMerge(record, epoch(t.clock())) {
			return true
		}
		parts := gh.PullURL.FindStringSubmatch(record.Str("pr"))
		if parts == nil || record.Truthy("live_at") && !record.Truthy("live_notified") {
			return false
		}
		if health := record.Dict("health"); health != nil && health.Truthy("command") || !record.Has("health") && record.Truthy("repo") {
			return false
		}
		sha := ""
		for _, key := range []string{"merge_sha", "merge_commit", "merge_commit_sha"} {
			if sha = strings.TrimSpace(record.Str(key)); sha != "" {
				break
			}
		}
		if sha == "" {
			value, why, err := gh.JSON(run.Runs(), "pr", "view", record.Str("pr"), "--json", "mergeCommit")
			if err != nil {
				return false
			}
			if answer, ok := value.(*run.Object); ok && answer.Dict("mergeCommit") != nil {
				sha = strings.TrimSpace(answer.Dict("mergeCommit").Str("oid"))
			}
			if sha == "" {
				t.log.line(fmt.Sprintf("WARN %s: cannot read its merge commit: %s", record.Str("pr"), cmp.Or(why, "")))
				return true
			}
		}
		value, _, err := gh.JSON(run.Runs(), "api", "--paginate", fmt.Sprintf("repos/%s/%s/commits/%s/check-runs?filter=latest&per_page=100", parts[1], parts[2], sha))
		if err != nil {
			return false
		}
		pages, ok := value.([]any)
		if !ok {
			return false
		}
		for _, page := range pages {
			answer, ok := page.(*run.Object)
			if !ok || answer.List("check_runs") == nil {
				return false
			}
			for _, each := range answer.List("check_runs") {
				check, ok := each.(*run.Object)
				if ok && check.Str("status") == "completed" && !slices.Contains([]string{"success", "neutral", "skipped", "cancelled"}, check.Str("conclusion")) {
					return false
				}
			}
		}
		if record.Str("merge_sha") != sha {
			failed = run.Change(dir, func(current *run.Object) error {
				if current.Truthy("merged") && run.Equal(current.Get("finished_at"), record.Get("finished_at")) {
					current.Set("merge_sha", sha)
				}
				return nil
			})
		}
		return failed == nil
	})
	if !carried {
		return cmp.Or(failed, errLeft)
	}
	return nil
}
