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

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/run"
)

// A merge's live product is followed for three hours (watch.AFTER_MERGE_WINDOW), and one break
// per repository is handed back to fix, as Python's after_merge_checks does. A deployment to probe
// or revert is Python's.
const mergeWindow = 3 * 3600

// A merge is one followed run as the merge checks read it, with its verdict: passed, failed,
// pending while its probe fails inside its window, unknown where its commit cannot be read, or ""
// where nobody declared its health.
type merge struct {
	finished           float64
	name, pr, sha      string
	record             *run.Object
	verdict, check, at string // at: the failure's address and output, one typed line
}

var pullPath = regexp.MustCompile(`^/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$`)

// pullRepo is the host, owner and repository a pull request's address names (after_merge_repo);
// "" for each where it names none.
func pullRepo(pr string) (host, owner, name string) {
	address, err := url.Parse(pr)
	if err != nil || address.Scheme != "https" || address.Hostname() == "" || address.User != nil ||
		address.RawQuery != "" || address.Fragment != "" {
		return "", "", ""
	}
	parts := pullPath.FindStringSubmatch(address.EscapedPath())
	if parts == nil {
		return "", "", ""
	}
	return address.Host, parts[1], parts[2]
}

// repoKey is the repository a pull request's address names, `host/owner/repo` in lower case; ""
// where it names none.
func repoKey(pr string) string {
	if host, owner, name := pullRepo(pr); host != "" {
		return strings.ToLower(host + "/" + owner + "/" + name)
	}
	return ""
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

// pythons is whether a followed merge needs what Go does not do before its health is read: a
// deployment, which after_merge_revert probes even past its window, or health that is no object.
func pythons(record *run.Object, now float64) bool {
	return !passedBefore(record, now) && (record.Truthy("deployed") || record.Truthy("health") && record.Dict("health") == nil)
}

// mergeChecks reads each followed merge's verdict off its run, keeping its commit there once,
// under the run's lock, and then each repository's break (breaks). Every run is read once, and
// that census answers what each merge asks of its seat's other runs: one read each was 5167 files
// read 200 times a tick (30 Oct 2026). A dry tick decides the same, and says what it would probe,
// record and hand back.
func (t *ticking) mergeChecks() error {
	now := epoch(t.clock())
	grouped, census := map[string][]*merge{}, []*run.Object{}
	carried := run.Every(func(dir string, record *run.Object) bool {
		census = append(census, record)
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
	probes := map[[2]string]probe{}
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
			if err := verdict(each, key, now, probes, census, t.log.line, t.dry); errors.Is(err, errLeft) {
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

// verdict is after_merge_checks's reading of one merge, and a live follower's: a pass told before
// is one still, and any other is followed at its merge commit, the run's own, else the one GitHub
// names.
func verdict(each *merge, key string, now float64, probes map[[2]string]probe, census []*run.Object, say func(string), dry bool) error {
	record := each.record
	if passedBefore(record, now) {
		each.sha, each.verdict = record.Str("merge_sha"), "passed"
		return nil
	}
	if err := mergeCommit(each, say); err != nil || each.sha == "" {
		return err
	}
	return mergeHealth(each, key, now, probes, census, say, dry)
}

// mergeCommit finds the commit a merge is followed at (after_merge_sha): the run's own, else the
// one GitHub names; errLeft where gh cannot be read, and none, its verdict unknown and said, where
// GitHub names none.
func mergeCommit(each *merge, say func(string)) error {
	if each.sha = recordedSHA(each.record); each.sha != "" {
		return nil
	}
	value, why, err := gh.JSON(run.Runs(), "pr", "view", each.pr, "--json", "mergeCommit")
	if err != nil {
		return errLeft
	}
	if answer, ok := value.(*run.Object); ok && answer.Dict("mergeCommit") != nil {
		each.sha = strings.TrimSpace(answer.Dict("mergeCommit").Str("oid"))
	}
	if each.sha == "" {
		said := []rune(config.Fold(why))
		say(fmt.Sprintf("WARN %s: cannot read its merge commit: %s", each.pr, string(said[:min(len(said), 160)])))
		each.verdict = "unknown"
	}
	return nil
}

// recordedSHA is the merge commit the run holds, "" for none (after_merge_sha).
func recordedSHA(record *run.Object) string {
	for _, field := range []string{"merge_sha", "merge_commit", "merge_commit_sha"} {
		if sha := strings.TrimSpace(record.Str(field)); sha != "" {
			return sha
		}
	}
	return ""
}
