package tick

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"math"
	"net/url"
	"os"
	"runtime"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

const authoredSearch = "search/issues?q=is:pr+is:open+author:@me&per_page=100"

// ticking is one real tick under way.
type ticking struct {
	state       *run.Object
	log         *log
	clock       func() time.Time
	slowest     time.Duration
	slowestName string
	dry         bool     // a dry tick: it runs the rows Python's does, each acting only where it checks this
	fetched     []string // each project the project rules row fetched, for the rows after it to read
	report      AuditReport
}

// Carry is a real `ak watch`, as Python's watch.main runs one: a tick that finds another holding
// the lock says so, and one under the lock goes through the passes, each read at its own turn,
// and GitHub.  False leaves the tick to Python, the lock released: at the first row that finds what
// Go does not carry, what the rows before did standing; after what Python's next tick reads as its
// own where gh names a pull request to act on; with nothing written where gh cannot be read,
// or where ak's folders, the lock or watch.json cannot be taken; and on Windows, as Overlap.
func Carry(out, errOut io.Writer, report ...AuditReport) bool {
	if Overlap(out, errOut) {
		return true
	}
	if runtime.GOOS == "windows" {
		return false
	}
	// asked before any pass, where Python asks after them: no row says whether Go carries the
	// GitHub passes, and the tick begins with the asking
	began := time.Now()
	user, why, failed := gh.JSON(run.Runs(), "api", "user")
	asked := time.Since(began)
	if failed != nil || config.EnsureDirs() != nil {
		return false
	}
	held, err := lock.Try(lockPath())
	if errors.Is(err, lock.ErrHeld) {
		return Overlap(out, errOut)
	}
	if err != nil {
		return false
	}
	defer held.Close()
	// the write is also the stamp: mtime is when this tick began
	if held.Truncate(0) != nil {
		return false
	}
	if _, err := fmt.Fprintf(held, "%d\n", os.Getpid()); err != nil {
		return false
	}
	// the passes' seat records are listed from the state folder
	state, ok := loadState()
	if !ok || !quiet(state) || !config.Listable(statePath("")) {
		return false
	}
	t := &ticking{state: state, log: newLog(out, errOut), clock: time.Now}
	if len(report) > 0 {
		t.report = report[0]
	}
	if !t.through(table(t)) {
		return false
	}
	carried := t.github(user, why, asked)
	// however the tick ends, the next one and `ak doctor` find when it ran and what held it up
	record, slowest := run.NewObject(), run.NewObject()
	record.Set("started_at", epoch(began))
	record.Set("ended_at", epoch(t.clock()))
	slowest.Set("pass", t.slowestName)
	slowest.Set("seconds", math.Round(t.slowest.Seconds()*10)/10)
	record.Set("slowest", slowest)
	state.Set("tick", record)
	return t.save() == nil && carried
}

func epoch(at time.Time) float64 { return float64(at.UnixNano()) / 1e9 }

func (t *ticking) save() error { return saveState(t.state) }

// through runs the passes in order, each asked whether it has nothing to act on just before Go
// carries out its step, the one place that says of a pass that it raised; false at the first that
// finds what Go does not carry. A dry tick runs only those Python's dry tick runs.
func (t *ticking) through(passes []pass) bool {
	for _, each := range passes {
		if t.dry && !each.dry {
			continue
		}
		if each.idle != nil && !each.idle() {
			return false
		}
		if each.step == nil {
			continue
		}
		err := t.timed(each.name, each.step)
		if errors.Is(err, errLeft) {
			return false
		}
		if err != nil {
			t.log.line(fmt.Sprintf("WARN %s did not run: %s", each.name, config.PyError(err)))
		}
	}
	return true
}

// timed runs a step and counts how long it took.
func (t *ticking) timed(name string, step func() error) error {
	start := t.clock()
	err := step()
	t.took(name, t.clock().Sub(start))
	return err
}

// took says so of a step over a second, in a real tick, and keeps the slowest.
func (t *ticking) took(name string, spent time.Duration) {
	if spent > time.Second && !t.dry {
		t.log.line(fmt.Sprintf("%s took %.1f s", name, spent.Seconds()))
	}
	if spent > t.slowest || spent == t.slowest && name > t.slowestName {
		t.slowest, t.slowestName = spent, name
	}
}

// github is what Python's main does with gh's answer to who is logged in, which took asked;
// false leaves the rest to Python. A logout is the owner's to fix and written down for every seat
// to say so; an outage is not, and an earlier logout stands until gh answers.
func (t *ticking) github(value any, why string, asked time.Duration) bool {
	t.took("github user", asked)
	me := login(value)
	if me == "" {
		line, loggedOut := unanswered(why)
		t.log.line(line)
		if loggedOut {
			out := run.NewObject()
			out.Set("at", epoch(t.clock()))
			t.state.Set("gh_out", out)
		}
		return true
	}
	t.state.Delete("gh_out")
	carried := false
	t.timed("incoming prs", func() error {
		carried = t.incoming(me)
		return nil
	})
	if !carried {
		return false
	}
	t.timed("outgoing prs", func() error {
		carried = t.outgoing(me)
		return nil
	})
	return carried
}

// login is who gh's answer says is logged in.
func login(value any) string {
	if user, ok := value.(*run.Object); ok {
		return user.Str("login")
	}
	return ""
}

// unanswered is the line for a gh that named nobody, and whether that is a logout. gh's advice
// runs to several lines; one line is the whole point here.
func unanswered(why string) (string, bool) {
	words := []rune(config.Fold(cmp.Or(why, "gh api user failed")))
	reason := string(words[:min(len(words), 160)])
	if gh.LoggedOut(reason) {
		return "gh is not logged in; PR checks skipped (" + reason + ")", true
	}
	return "WARN GitHub is unavailable; PR checks skipped (" + reason + ")", false
}

// outgoing is what Python's outgoing asks of a home following no pull request: this account's
// open ones anywhere. False where one is on another's repository, to follow.
func (t *ticking) outgoing(me string) bool {
	if !noSavedForeignPRs() {
		return false
	}
	value, why, err := gh.JSON(run.Runs(), "api", "--paginate", authoredSearch)
	if err != nil {
		return false
	}
	pages, readable := value.([]any)
	var found []any
	for _, page := range pages {
		var items any
		if object, ok := page.(*run.Object); ok {
			items = object.Get("items")
		}
		list, ok := items.([]any)
		readable = readable && ok
		found = append(found, list...)
	}
	if !readable {
		t.log.line("WARN authored PR discovery failed: " + cmp.Or(why, "gh did not return arrays of pages"))
		return true
	}
	for _, item := range found {
		if !ownOrNone(item, me) {
			return false
		}
	}
	return true
}

// ownOrNone is whether the search's item leaves nothing to follow: no pull request's address, or
// one on this account's own repository. An item Go cannot read is not that.
func ownOrNone(item any, me string) bool {
	found, ok := item.(*run.Object)
	if !ok {
		return false
	}
	if !found.Truthy("pull_request") {
		return true
	}
	pull, ok := found.Get("pull_request").(*run.Object)
	if !ok {
		return false
	}
	if !pull.Truthy("html_url") {
		return true
	}
	address, ok := pull.Get("html_url").(string)
	if !ok {
		return false
	}
	parsed, err := url.Parse(address)
	if err != nil {
		return false
	}
	owner, _, _ := strings.Cut(strings.Trim(parsed.Path, "/"), "/")
	return owner == "" || strings.EqualFold(owner, me)
}
