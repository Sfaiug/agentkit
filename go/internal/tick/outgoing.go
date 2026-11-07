package tick

import (
	"cmp"
	"context"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/handback"
	"agentkit/internal/lock"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// The outgoing pass is Python's outgoing: each pull request of this account's on a repository it
// does not own is followed in watch.json's `own`, and what the maintainer decided is handed on
// once, never to Discord.  A request for changes or a close goes on the run that opened it and is
// typed into the seat that answers for it; any other decision stays in `own`.  A merge is
// Python's, as is any case Go does not carry, each at its own point, before anything is written.

const authoredSearch = "search/issues?q=is:pr+is:open+author:@me&per_page=100"

// outgoing is Python's outgoing; false leaves the rest to Python.
func (t *ticking) outgoing(me string) bool {
	urls, seats, ok := t.ownPRs(me)
	for _, address := range urls {
		ok = ok && t.follow(address, seats[address])
	}
	return ok
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
// once.  Its entry in `own` changes only where Go carries it: a merge (milestone 186c), and any
// case Go does not type or wake, go to Python with it as it stood.
func (t *ticking) follow(address, session string) bool {
	own := t.state.Dict("own")
	entry := run.Fields("decision", nil, "done", false)
	if kept, ok := own.Get(address).(*run.Object); ok { // ownPRs read each kept one as an object
		if kept.Truthy("done") {
			return true
		}
		entry = kept.Copy()
	}
	value, why, err := gh.JSON(run.Runs(), "pr", "view", address, "--json", "state,reviewDecision,title,number")
	view, _ := value.(*run.Object)
	if err != nil || view != nil && view.Get("state") == "MERGED" {
		return false
	}
	if session != "" {
		entry.Set("session", session)
	}
	carried := true
	if view == nil {
		t.log.line(fmt.Sprintf("WARN %s: gh pr view failed: %s", address, why))
	} else {
		label := "PR #" + run.Text(view.Get("number")) + " " + run.Text(view.Get("title"))
		decision, said := view.Get("reviewDecision"), false
		switch {
		case view.Get("state") == "CLOSED":
			if said, carried = t.say(label+": closed by the maintainer without a merge", address, session); said {
				entry.Set("done", true)
			}
		case decision == "CHANGES_REQUESTED" && entry.Get("decision") != "CHANGES_REQUESTED":
			if said, carried = t.say(label+": the maintainer requested changes", address, session); said {
				entry.Set("decision", decision)
			}
		case view.Truthy("reviewDecision") && !run.Equal(entry.Get("decision"), decision):
			// the line an earlier decision left unsent in the seat's composer gets its Enter
			// first, or the next tick comes back here
			if said = t.dry; !said {
				said, carried = t.sentPending(runFor(address))
			}
			if said {
				entry.Set("decision", decision)
				entry.Set("decision_at", run.Float(epoch(t.clock())))
			}
		}
	}
	if carried {
		own.Set(address, entry)
	}
	return carried
}

// say is Python's say of a close or a request for changes: on the run that opened the pull request
// once, where the menu and `ak run status` showed `waiting for the maintainer`, then typed at the
// quiet prompt of the seat answering for it, woken first where it sleeps, the line's mark kept on
// the run (`decision_typed`) so one typed and never seen sent gets its Enter, not a second copy.
// Said is whether it landed everywhere it goes, or has nowhere left to.
func (t *ticking) say(text, address, session string) (said, carried bool) {
	if t.dry {
		t.log.line("would hand on: " + text + " (" + address + ")")
		return false, true
	}
	dir, record := runFor(address)
	line := text + " -- " + address + ". Nothing was posted to Discord; this is the maintainer's decision on a PR of ours, " +
		"for you to act on or not."
	held := record.Dict("decision_typed")
	name, _, err := config.ResolveSession(session)
	// what Go does not type or wake is Python's, before anything is written: Python's seat_notice
	// points to result.md where the line would not fit, and its editor reads a mark naming a pane
	if session != "" && (err != nil || !reaches(name)) || config.TooLong(line) ||
		record.Truthy("decision_typed") && (held == nil || held.Has("pane")) {
		return false, false
	}
	if note := config.Fold(text); dir != "" && record.Str("merge_note") != note {
		if !recordDecision(dir, record, note) {
			return false, false
		}
		t.log.line("recorded on run " + filepath.Base(dir) + ": " + text)
	}
	if session != "" {
		awake, woken := seat.Wake(name, t.log.line)
		if !awake {
			return false, woken // owed its line: the next tick wakes it
		}
	}
	if session == "" || !seat.Watching(name) {
		if dir == "" {
			t.log.line("no live seat and no run for " + address + "; not followed further: " + text)
		}
		return true, true
	}
	if held != nil && held.Get("line") != line {
		// an earlier decision's line left in the composer would hold this one back as a draft
		if sent, carried := t.sentPending(dir, record); !sent {
			return false, carried
		}
	}
	kept := func(mark any) bool {
		return dir == "" || handback.MarkDelivery(dir, record, "decision_typed", mark)
	}
	unmarked := false
	if !seat.TypeAtPrompt(name, line, held, func(mark *run.Object) error {
		unmarked = !kept(mark) // its Enter goes all the same: a line that leaves needs no mark
		return nil
	}, t.log.line) {
		// a line left in the composer with no mark reads as the owner's draft to Go, which only
		// Python's editor types past
		return false, !unmarked
	}
	if !kept(nil) {
		return false, true // the next tick reads it sent, and takes the mark off then
	}
	t.log.line("told the " + name + " seat: " + text)
	return true, true
}

// reaches is whether Go carries a line to that seat: none up or asleep to take it, or one whose
// harness Go types into, asleep only where Go wakes it.
func reaches(name string) bool {
	asleep := seat.Asleep(name)
	return !asleep && !seat.Watching(name) || seat.Typable(name) && (!asleep || seat.Wakes(name))
}

// sentPending is Python's sent_pending: whether no line typed about the run's pull request is
// left unsent in its seat's composer, the Enter of one that is pressed first, as long as the seat
// it went into is up, and its mark then taken off the run.
func (t *ticking) sentPending(dir string, record *run.Object) (sent, carried bool) {
	if !record.Truthy("decision_typed") {
		return true, true
	}
	if mark := record.Dict("decision_typed"); mark != nil && mark.Truthy("line") {
		name := run.Seat(record)
		if born, up := seat.Up()[name]; up && run.Equal(born, mark.Get("seat")) {
			if mark.Has("pane") || !seat.Typable(name) {
				return false, false
			}
			if !seat.TypeAtPrompt(name, mark.Str("line"), mark, func(*run.Object) error { return nil }, t.log.line) {
				return false, true
			}
		}
	}
	return dir == "" || handback.MarkDelivery(dir, record, "decision_typed", nil), true
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

// recordDecision is Python's record_decision of a decision no merge made: the run's merge_note
// becomes it, and result.md says so, written again while the run's worktree is there, else the
// note added under a heading of its own; false where the record could not be written.
func recordDecision(dir string, record *run.Object, note string) bool {
	if run.Change(dir, func(current *run.Object) error {
		current.Set("merge_note", note)
		return nil
	}) != nil {
		return false
	}
	record.Set("merge_note", note)
	// the note is on the run; a result that cannot be written again from here is not news
	if info, err := os.Stat(record.Str("worktree")); record.Truthy("worktree") && err == nil && info.IsDir() {
		loop.WriteResult(dir, record)
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
