package tick

import (
	"cmp"
	"errors"
	"fmt"
	"math"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/history"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

const (
	reviewDay  = 86400.0
	reviewWeek = 7 * reviewDay
	originMain = "refs/remotes/origin/main"
)

// A nightReading is what history.db says of the night review (night_review.reading): whether
// after-merge breaks arm it, each of the last two seven-day windows' broken and merged runs,
// newest first, the previous UTC day, and that day's merged runs.
type nightReading struct {
	armed bool
	weeks [2][2]int
	day   string
	rows  []history.Row
}

// readNights is the night review's reading at now, in UTC, false where Go leaves history.db to
// Python.  It is armed while, in both windows, more than one merge in 200 broke after merging.
func readNights(now time.Time) (nightReading, bool) {
	db, err := history.Reader()
	if err != nil {
		return nightReading{}, false
	}
	at := epoch(now)
	ended, _ := db.EndedRuns(at-2*reviewWeek, at) // none where the database cannot answer, as Python's
	db.Close()
	midnight := math.Floor(at/reviewDay) * reviewDay
	read := nightReading{day: time.Unix(int64(midnight-reviewDay), 0).UTC().Format("2006-01-02")}
	for _, row := range ended {
		if !row.Merged() {
			continue
		}
		finished, _ := row.Num("finished_at")
		// the newest window takes its end too, which the read ends at
		for i, since := range []float64{at - reviewWeek, at - 2*reviewWeek} {
			if since <= finished && (i == 0 || finished < at-reviewWeek) && row["broke_after_merge"] != nil {
				read.weeks[i][1]++
				if row.Truthy("broke_after_merge") {
					read.weeks[i][0]++
				}
			}
		}
		if midnight-reviewDay <= finished && finished < midnight {
			read.rows = append(read.rows, row)
		}
	}
	read.armed = read.weeks[0][0]*200 > read.weeks[0][1] && read.weeks[1][0]*200 > read.weeks[1][1]
	return read, true
}

// A review is a project the previous day merged into: its checkout, those merged runs by when
// they finished, and the seat to take its review, "" for none.
type review struct {
	checkout, seat string
	merged         []history.Row
}

// reviews are the day's projects (night_review.targets), each with the seat of its last merge, by
// that seat's name now, else the newest seat filed under its checkout, never a stopped one; false
// where Go does not read the seats or checkouts as Python does.
func (read nightReading) reviews() ([]review, bool) {
	checkouts, seen := seat.Checkouts()
	if !seen {
		return nil, false
	}
	seats, projects := map[string]*run.Object{}, map[string]string{}
	for _, path := range config.SeatFiles() {
		name := strings.TrimSuffix(strings.TrimPrefix(filepath.Base(path), "session-"), ".json")
		record, err := run.Shared(path)
		mark, marked := run.Shared(filepath.Join(config.Home(), "state", "seat-"+name+".json"))
		if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(marked, run.ErrLoneSurrogate) {
			return nil, false
		}
		if record != nil && !record.Has(config.Renamed) && (mark == nil || !mark.Truthy("stopped_at")) {
			seats[name], projects[name] = record, seat.CheckoutOf(record.Str("repo"))
		}
	}
	var found []review
	for _, checkout := range checkouts {
		each := review{checkout: checkout}
		for _, row := range read.rows {
			if row.Text("repo") == filepath.Base(checkout) {
				each.merged = append(each.merged, row)
			}
		}
		if each.merged == nil {
			continue
		}
		slices.SortStableFunc(each.merged, func(a, b history.Row) int {
			x, _ := a.Num("finished_at")
			y, _ := b.Num("finished_at")
			return cmp.Compare(x, y)
		})
		if named := each.merged[len(each.merged)-1].Text("session"); named != "" {
			each.seat, _, _ = config.ResolveSession(named) // a name no file can have is no seat
		}
		if seats[each.seat] == nil {
			each.seat = ""
			newest := 0.0
			for name, record := range seats {
				created, _ := record.Num("created")
				if projects[name] == checkout && (each.seat == "" || created > newest || created == newest && name > each.seat) {
					each.seat, newest = name, created
				}
			}
		}
		found = append(found, each)
	}
	return found, true
}

// NightReviewLine is `ak doctor`'s night review line (night_review.doctor_line): armed or not, each
// window's broken and merged runs, and each project of the day with no seat to take its review;
// false where Go does not read them.
func NightReviewLine() (string, bool) {
	read, ok := readNights(time.Now())
	if !ok {
		return "", false
	}
	reviews, ok := read.reviews()
	if !ok {
		return "", false
	}
	line := "night review  disarmed · last two weeks "
	if read.armed {
		line = "night review  armed · last two weeks "
	}
	var shares, missing []string
	for _, counts := range read.weeks {
		share := "no merges"
		if counts[1] > 0 {
			share = fmt.Sprintf("%d/%d (%.1f%%)", counts[0], counts[1], float64(counts[0])/float64(counts[1])*100)
		}
		shares = append(shares, share)
	}
	for _, each := range reviews {
		if each.seat == "" {
			missing = append(missing, filepath.Base(each.checkout)+": no seat")
		}
	}
	line += strings.Join(shares, " · ")
	if missing != nil {
		line += " · " + strings.Join(missing, ", ")
	}
	return line, true
}

// nightReview is the night review row (night_review.tick): while armed, one ordinary run for each
// project the previous UTC day merged into, on the seat its review takes.  Any run of its task
// file, in any state, claims the day; a launch that fails says so, and the next tick tries again.
func (t *ticking) nightReview() error {
	read, ok := readNights(t.clock())
	if !ok {
		return errLeft
	}
	if !read.armed {
		return nil
	}
	claimed := map[string]bool{}
	if !run.Every(func(_ string, record *run.Object) bool {
		if file := record.Str("task_file"); file != "" {
			claimed[config.Absolute(file)] = true
		}
		return true
	}) {
		return errLeft
	}
	reviews, ok := read.reviews()
	if !ok {
		return errLeft
	}
	for _, each := range reviews {
		name := filepath.Base(each.checkout)
		path := filepath.Join(config.Home(), "tasks", name, "night-review-"+read.day+".md")
		if each.seat == "" || claimed[config.Absolute(path)] {
			continue
		}
		err := each.start(read.day, path)
		if errors.Is(err, loop.ErrLeft) {
			return errLeft
		}
		if err != nil {
			t.log.line(fmt.Sprintf("WARN %s: no night review for %s: %s", name, read.day, config.PyError(err)))
		}
	}
	return nil
}

// start launches the review of the day's merged commits, as origin's main has them on its
// first-parent line, checked by the project's declared tests, as a follow-up of the day's last
// merged run (night_review._start): its first executor may end it not needed without a review.
func (each review) start(day, path string) error {
	g := gitcall.Git{Repo: each.checkout, Env: gitcall.ProjectEnv(each.checkout)}
	if code, out, err := g.Fetch("origin", "+refs/heads/main:"+originMain); err != nil || code != 0 {
		return cmp.Or(err, fmt.Errorf("git fetch origin +refs/heads/main:%s failed in %s: %s", originMain, each.checkout, out))
	}
	listed, err := g.Must("rev-list", "--first-parent", "--reverse", originMain)
	if err != nil {
		return err
	}
	wanted := map[any]bool{}
	for _, row := range each.merged {
		wanted[row["merge_sha"]] = true
	}
	var commits []string
	for _, sha := range config.SplitLines(listed) {
		if wanted[sha] {
			commits = append(commits, sha)
		}
	}
	if commits == nil || len(commits) != len(wanted) {
		return errors.New("the day's merged commits are not all on origin/main")
	}
	tests := gitcall.DeclaredAt(each.checkout, originMain, "tests", g.Env...)
	if tests == "" {
		return errors.New("no tests: on origin/main")
	}
	name := filepath.Base(each.checkout)
	text := "---\nrepo: " + each.checkout + "\nbase: " + originMain + "\ntarget: main\n---\n" +
		"# Review " + name + "'s merged changes for " + day + "\n\n" +
		"Read the day's merged diff on origin/main, from " + commits[0] + " through " + commits[len(commits)-1] +
		", including the first commit's change.\n" +
		"Look for defects the changes together introduced or the per-change review missed.\n" +
		"If a test can show a defect, add it, show it failing on the current origin/main tip,\n" +
		"then fix the defect. Otherwise hand in `ak hand-in not-needed \"<why>\"` without edits.\n\n" +
		"## Done when\n```bash\n" + tests + "\n```\n"
	last := each.merged[len(each.merged)-1]
	followup := run.Fields("run", last["run_id"], "text", "Review "+day+"'s merged changes", "place", path)
	_, err = loop.LaunchForSeat(each.seat, "night-review-"+name+"-"+day, path, text, run.Fields("followup", followup, "repo", each.checkout))
	return err
}
