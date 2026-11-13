package seat

import (
	"context"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// SyncTitle is watch.sync_title as the tick's health row makes it before its look, where Go
// carries it: a seat up on ak's own server, its pane bound, of a harness Go types a title into
// (harness.TitleLine), with no send of a title on its record, and no title of the owner's on its
// conversation for the seat to follow (watch.follow_title).  A title its conversation already
// gives it is recorded; else the line naming it goes in at its quiet prompt, its try recorded the
// moment its text is in, and the title is the seat's once that line left the composer and the
// conversation names it, or names nothing where the harness says an unread title confirms it.
// Any other seat's title is left as it is, which its look leaves to Python.
func SyncTitle(name string, log func(string)) error {
	own, _ := seatHarness(name)
	line, unreadable := harness.TitleLine(own, name)
	if line == "" || !Watching(name) {
		return nil
	}
	if pane, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+name+":", "#{"+tmux.HarnessPane+"}"); err != nil || pane == "" {
		return nil // watch.bind_pane's first
	}
	named := []field{{"session_title", name}, {"title_sync", nil}}
	var conversation any
	send := false
	err := titleHeld(name, own, func(record *run.Object, title any) []field {
		conversation = record.Get("conversation")
		switch {
		case record.Has("title_conversation") && !run.Equal(record.Get("title_conversation"), conversation), record.Get("title_sync") != nil,
			title != nil && (slices.Contains(record.List("title_superseded"), title) || title != "" && title != name && title != record.Get("session_title")):
			return nil // a send to retire or retry, a title to replace or one to follow is Python's
		case record.Get("session_title") == name:
			return nil
		case title == name:
			return named
		}
		send = true
		return nil
	})
	if err != nil || !send {
		return err
	}
	var attempt any // the try, once its text is in
	stale := func(current string) bool {
		record := sessionRecord(current)
		return current != name || record == nil || !run.Equal(record.Get("title_sync"), attempt) ||
			!run.Equal(record.Get("conversation"), conversation) || notify.OwnerQuestion(notify.Last(current))
	}
	typed := func(*run.Object) error {
		try := run.Fields("name", name, "tries", 1, "pending", true)
		err := Update(name, func(record *run.Object) bool {
			fill(record, []field{{"title_sync", try}, {"title_conversation", conversation}})
			return true
		})
		if err == nil {
			attempt = try
		}
		return err
	}
	// each Enter only while this try is still the seat's and its line alone is in the composer,
	// as sync_title's veto holds back its retry
	if !typeAtPrompt(name, line, nil, typed, log, stale) {
		return nil
	}
	return titleHeld(name, own, func(record *run.Object, title any) []field {
		try, _ := attempt.(*run.Object)
		switch {
		case try == nil || !run.Equal(record.Get("title_sync"), try) || !run.Equal(record.Get("conversation"), conversation):
			return nil
		case title == name || title == nil && unreadable:
			return named
		}
		// sent, the composer is no longer the try's while its title waits to be read
		return []field{{"title_sync", run.SetAll(try.Copy(), "pending", false)}}
	})
}

// titleHeld reads the seat's record, and its conversation's title on from the last reading,
// under its typing lock, and writes what decide returns onto the record.
func titleHeld(name, own string, decide func(record *run.Object, title any) []field) error {
	return notify.Held(context.Background(), name, func(current string) error {
		record := sessionRecord(current)
		if current != name || record == nil {
			return nil
		}
		cache := ownFile("title", current)
		title, kept := harness.SessionTitle(own, record, cache)
		if kept != nil {
			if err := harness.KeepTitle(cache, kept); err != nil {
				return err
			}
		}
		fields := decide(record, title)
		if fields == nil {
			return nil
		}
		return Update(current, func(data *run.Object) bool {
			fill(data, fields)
			return true
		})
	})
}

// sessionRecord is the seat's record, nil where it reads none.
func sessionRecord(name string) *run.Object {
	record, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "session-"+name+".json"))
	return record
}
