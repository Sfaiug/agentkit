package tick

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/handback"
	"agentkit/internal/history"
	"agentkit/internal/lock"
	"agentkit/internal/loop"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// The outgoing pass is Python's outgoing: each pull request of this account's on a repository it
// does not own is followed in watch.json's `own`, and what the maintainer decided is handed on
// once, never to Discord.  A request for changes or a close goes on the run that opened it and is
// typed into the seat that answers for it, and a merge goes on it too (forkmerge.go); any other
// decision stays in `own`.  Any case Go does not carry is Python's, each at its own point, before
// anything is written.

const authoredSearch = "search/issues?q=is:pr+is:open+author:@me&per_page=100"

// outgoing is Python's outgoing: errLeft leaves the rest to Python, and any other error fails the
// tick where Python's raises.
func (t *ticking) outgoing(me string) error {
	urls, seats, ok := t.ownPRs(me)
	if !ok {
		return errLeft
	}
	for _, address := range urls {
		if err := t.follow(address, seats[address]); err != nil {
			return err
		}
	}
	return nil
}

// ownPRs is Python's own_prs: each pull request to follow, in its order, and the seat answering
// for it, "" for none: those the runs opened from a fork, those GitHub's search finds open on
// another's repository, and those followed before that are not done.
func (t *ticking) ownPRs(me string) ([]string, map[string]string, bool) {
	var urls []string
	seats := map[string]string{}
	add := func(address, session string, over bool) {
		if _, seen := seats[address]; !seen {
			urls = append(urls, address)
		} else if !over {
			return
		}
		seats[address] = session
	}
	if !run.Every(func(_ string, record *run.Object) bool {
		if !record.Truthy("foreign") || !record.Truthy("pr") {
			return true
		}
		address, ok := record.Get("pr").(string)
		session, err := "", error(nil)
		if name := run.Launched(record); name != "" {
			session, _, err = config.ResolveSession(name)
		}
		if ok && err == nil {
			add(address, session, true)
		}
		return ok && err == nil
	}) {
		return nil, nil, false
	}
	value, why, err := gh.JSON(run.Runs(), "api", "--paginate", authoredSearch)
	if err != nil {
		return nil, nil, false
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
		found = nil
	}
	for _, item := range found {
		address, ok := theirs(item, me)
		if !ok {
			return nil, nil, false
		}
		if address != "" {
			add(address, "", false)
		}
	}
	own := t.state.Dict("own")
	for _, address := range own.Keys() {
		entry, ok := own.Get(address).(*run.Object)
		if !ok {
			return nil, nil, false
		}
		session, named := entry.Get("session").(string)
		if entry.Truthy("session") && !named {
			return nil, nil, false
		}
		if !entry.Truthy("done") {
			add(address, session, false)
		}
	}
	return urls, seats, true
}

// theirs is the address of the pull request a search's item is on another's repository, "" for
// none: no pull request's address, or one on this account's own.  False for an item Go cannot read.
func theirs(item any, me string) (string, bool) {
	found, ok := item.(*run.Object)
	if !ok {
		return "", false
	}
	if !found.Truthy("pull_request") {
		return "", true
	}
	pull, ok := found.Get("pull_request").(*run.Object)
	if !ok {
		return "", false
	}
	if !pull.Truthy("html_url") {
		return "", true
	}
	address, ok := pull.Get("html_url").(string)
	if !ok {
		return "", false
	}
	parsed, err := url.Parse(address)
	if err != nil {
		return "", false
	}
	owner, _, _ := strings.Cut(strings.Trim(parsed.Path, "/"), "/")
	if owner == "" || strings.EqualFold(owner, me) {
		return "", true
	}
	return address, true
}

// follow is Python's outgoing of one pull request: read, and what the maintainer decided handed on
// once.  Its entry in `own` changes only where Go carries it: any case Go does not type or wake
// goes to Python with it as it stood.
func (t *ticking) follow(address, session string) error {
	own := t.state.Dict("own")
	entry := run.Fields("decision", nil, "done", false)
	if kept, ok := own.Get(address).(*run.Object); ok { // ownPRs read each kept one as an object
		if kept.Truthy("done") {
			return nil
		}
		entry = kept.Copy()
	}
	value, why, err := gh.JSON(run.Runs(), "pr", "view", address, "--json", "state,reviewDecision,title,number")
	view, _ := value.(*run.Object)
	if err != nil {
		return errLeft
	}
	if session != "" {
		entry.Set("session", session)
	}
	if view == nil {
		t.log.line(fmt.Sprintf("WARN %s: gh pr view failed: %s", address, why))
	} else {
		label := "PR #" + run.Text(view.Get("number")) + " " + run.Text(view.Get("title"))
		decision, said := view.Get("reviewDecision"), false
		switch {
		case view.Get("state") == "MERGED":
			if said, err = t.say(label+": merged by the maintainer", address, session, true); said {
				entry.Set("done", true)
			}
		case view.Get("state") == "CLOSED":
			if said, err = t.say(label+": closed by the maintainer without a merge", address, session, false); said {
				entry.Set("done", true)
			}
		case decision == "CHANGES_REQUESTED" && entry.Get("decision") != "CHANGES_REQUESTED":
			if said, err = t.say(label+": the maintainer requested changes", address, session, false); said {
				entry.Set("decision", decision)
			}
		case view.Truthy("reviewDecision") && !run.Equal(entry.Get("decision"), decision):
			// the line an earlier decision left unsent in the seat's composer gets its Enter
			// first, or the next tick comes back here
			if said = t.dry; !said {
				said, err = t.sentPending(runFor(address))
			}
			if said {
				entry.Set("decision", decision)
				entry.Set("decision_at", run.Float(epoch(t.clock())))
			}
		}
	}
	if !errors.Is(err, errLeft) {
		own.Set(address, entry)
	}
	return err
}

// say is Python's say: on the run that opened the pull request once, where the menu and `ak run
// status` showed `waiting for the maintainer`, then typed at the quiet prompt of the seat
// answering for it, owed one an older ak put to sleep until the tick reopens it, the line's mark
// kept on the run (`decision_typed`) so one typed and never seen sent gets its Enter, not a second
// copy; a merge only where its seat owes work for it (untyped).  Said is whether it landed
// everywhere it goes, or has nowhere left to.
func (t *ticking) say(text, address, session string, merged bool) (said bool, err error) {
	if t.dry {
		t.log.line("would hand on: " + text + " (" + address + ")")
		return false, nil
	}
	dir, record := runFor(address)
	line := text + " -- " + address + ". Nothing was posted to Discord; this is the maintainer's decision on a PR of ours, " +
		"for you to act on or not."
	held := record.Dict("decision_typed")
	name, _, err := config.ResolveSession(session)
	// what Go does not type is Python's, before anything is written: Python's seat_notice
	// points to result.md where the line would not fit, its editor reads a mark naming a pane, it
	// sends a hand-back's line left unsent, which a merge's notice replaces (endings), it starts a
	// merge's follow-up that has no command, and it weighs the seat's plan where Go cannot
	if session != "" && (err != nil || !reaches(name)) || config.TooLong(line) ||
		record.Truthy("decision_typed") && (held == nil || held.Has("pane")) ||
		merged && (record.Truthy("handback_typed") || handback.Unclaimed(record) || plan.Readable(run.Seat(record)) != nil) {
		return false, errLeft
	}
	if note := config.Fold(text); dir != "" && (record.Str("merge_note") != note || merged && !record.Truthy("merged")) {
		if !recordDecision(dir, record, note, merged) {
			return false, errLeft
		}
		t.log.line("recorded on run " + filepath.Base(dir) + ": " + text)
	}
	if merged && (dir == "" || untyped(record)) {
		return t.endRoutine(dir, record, line)
	}
	if session != "" && seat.Asleep(name) {
		return false, nil // the line is owed it, and the tick reopens it first
	}
	if session == "" || !seat.Watching(name) {
		if dir == "" {
			t.log.line("no live seat and no run for " + address + "; not followed further: " + text)
		}
		return true, nil
	}
	if held != nil && held.Get("line") != line {
		// an earlier decision's line left in the composer would hold this one back as a draft
		if sent, err := t.sentPending(dir, record); !sent {
			return false, err
		}
	}
	var unkept error
	if !seat.TypeAtPrompt(name, line, held, func(mark *run.Object) error {
		// no Enter goes without its own mark on the run, which alone holds a second copy back:
		// the line stays in the composer, a draft no later tick types past
		unkept = keep(dir, record, mark)
		return unkept
	}, t.log.line) {
		return false, unkept
	}
	// a mark that cannot come off stays, and the next tick, handed it, finds the line sent
	if err := keep(dir, record, nil); err != nil {
		return false, err
	}
	t.log.line("told the " + name + " seat: " + text)
	return true, nil
}

// keep puts the mark of a line typed about the run's pull request on its record, nil taking it
// off; one that cannot be written fails the tick, as Python's raise does.
func keep(dir string, record *run.Object, mark any) error {
	if dir == "" || handback.MarkDelivery(dir, record, "decision_typed", mark) {
		return nil
	}
	return errors.New("run " + filepath.Base(dir) + ": the mark of the line typed into its seat could not be written")
}

// reaches is whether Go carries a line to that seat: none up to take it, or one whose harness Go
// types into.
func reaches(name string) bool {
	return !seat.Watching(name) || seat.Typable(name)
}

// sentPending is Python's sent_pending: whether no line typed about the run's pull request is
// left unsent in its seat's composer, the Enter of one that is pressed first, as long as the seat
// it went into is up, and its mark then taken off the run.
func (t *ticking) sentPending(dir string, record *run.Object) (bool, error) {
	if !record.Truthy("decision_typed") {
		return true, nil
	}
	if mark := record.Dict("decision_typed"); mark != nil && mark.Truthy("line") {
		name := run.Seat(record)
		if born, up := seat.Up()[name]; up && run.Equal(born, mark.Get("seat")) {
			if mark.Has("pane") || !seat.Typable(name) {
				return false, errLeft
			}
			if !seat.TypeAtPrompt(name, mark.Str("line"), mark, func(*run.Object) error { return nil }, t.log.line) {
				return false, nil
			}
		}
	}
	if err := keep(dir, record, nil); err != nil {
		return false, err
	}
	return true, nil
}

// runFor is the run that opened that pull request, Python's run_for_pr: "" and an empty record
// for none.
func runFor(address string) (string, *run.Object) {
	for _, dir := range run.Dirs() {
		if record, _ := run.Read(dir); record != nil && record.Get("pr") == address {
			return dir, record
		}
	}
	return "", run.NewObject()
}

// recordDecision is Python's record_decision: the run's merge_note becomes the decision, and a
// merge records what it leaves on the run (mergeRecord), ends the run's history row, and runs its
// seat's plan checks and follow-ups; result.md says so, written again while the run's worktree is
// there, else the note added under a heading of its own.  False where nothing was written.
func recordDecision(dir string, record *run.Object, note string, merged bool) bool {
	fields := run.Fields("merge_note", note)
	if merged && mergeRecord(record, fields) != nil {
		return false
	}
	put := func(to *run.Object) {
		for _, name := range fields.Keys() {
			to.Set(name, fields.Get(name))
		}
	}
	if run.Change(dir, func(current *run.Object) error { put(current); return nil }) != nil {
		return false
	}
	put(record)
	result := record
	if merged {
		history.Finish(record, nil)
		result = cmp.Or(loop.FinishSeat(dir, record), record)
	}
	// the note is on the run; a result that cannot be written again from here is not news
	if info, err := os.Stat(record.Str("worktree")); record.Truthy("worktree") && err == nil && info.IsDir() {
		loop.WriteResult(dir, result)
		return true
	}
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return true
	}
	defer held.Close()
	path := filepath.Join(dir, "result.md")
	if saved, err := os.ReadFile(path); err == nil && !strings.Contains(string(saved), note) {
		if file, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND, 0); err == nil {
			file.WriteString("\n## The maintainer decided\n\n" + note + "\n")
			file.Close()
		}
	}
	return true
}
