package notify

import (
	"cmp"
	"errors"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/transcript"
)

// OwnerSaid is when the owner wrote each of their messages in that seat's conversation, oldest
// first (notify.owner_said), as OwnerMessages reads them: none where they cannot be read.
func OwnerSaid(name string) ([]float64, error) {
	_, messages, err := OwnerMessages(name)
	if errors.Is(err, ErrUnread) {
		return nil, err
	}
	var said []float64
	for _, message := range messages {
		said = append(said, message.At)
	}
	return said, nil
}

// OwnerMessages is the conversation that seat's record owns and the owner's messages in it,
// oldest first (notify.owner_messages), as Conversations reads them: none with no record or no
// conversation to read; ErrUnread where its harness's are not Go's to read yet, and the error
// where the seat's typing receipts cannot be read (strict).
func OwnerMessages(name string) (string, []transcript.Prompt, error) {
	current, had, err := Listed(name, false)
	if err != nil || len(had) == 0 {
		return "", nil, err
	}
	// with those it left under its harness, as a line ak typed may have gone into one of them
	now := had[len(had)-1].Harness
	had = slices.DeleteFunc(had, func(was Conversation) bool { return was.Harness != now })
	if err := Read(current, had, false); err != nil {
		return "", nil, err
	}
	return had[len(had)-1].Name, had[len(had)-1].Messages, nil
}

// withoutAk takes the lines ak typed itself out of each conversation the seat that goes by current
// had, as each reads as the owner's (Python's `user_messages`): each of the seat's typing receipts
// takes one line in its words, the first not before the messages it came `after` in the
// conversation it went into, else, where that one is the seat's, the first at or after its `at`
// in another of its harness's, as a screen showing another than the record names takes it.  One
// the owner relayed stays theirs, as do identical later lines.
func withoutAk(current string, had []Conversation) error {
	type conversation struct{ harness, name string }
	type line struct {
		conversation
		index int
	}
	said := map[conversation][]transcript.Prompt{}
	var lines []line
	for _, each := range had {
		read := conversation{each.Harness, each.Name}
		// one its harness has not named yet no receipt names; one the seat went back to, once
		if _, again := said[read]; each.Name == "" || again {
			continue
		}
		said[read] = each.Messages
		for index := range each.Messages {
			lines = append(lines, line{read, index})
		}
	}
	message := func(of line) transcript.Prompt { return said[of.conversation][of.index] }
	// oldest first; of two at one time, by their conversations' names, so a receipt takes the
	// same whichever conversation is read
	slices.SortFunc(lines, func(a, b line) int {
		return cmp.Or(cmp.Compare(message(a).At, message(b).At), cmp.Compare(a.name, b.name),
			cmp.Compare(a.harness, b.harness), cmp.Compare(a.index, b.index))
	})
	taken, ours := map[line]bool{}, map[line]bool{}
	take := func(sent *run.Object) (line, bool) {
		named := conversation{sent.Str("harness"), harness.WentInto(sent.Str("harness"), sent)}
		_, held := said[named]
		after, dated := sent.Num("after")
		since, timed := sent.Num("at")
		var other line
		found := false
		for _, each := range lines {
			switch {
			case each.harness != named.harness || taken[each] || message(each).Text != sent.Str("text"):
			case each.conversation == named:
				if dated && float64(each.index) >= after {
					return each, true
				}
			case !found && held && timed && message(each).At >= since:
				other, found = each, true
			}
		}
		return other, found
	}
	err := harness.Entries(filepath.Join(config.Home(), "state", config.SeatFileNames(current)["input"]), func(sent *run.Object) {
		if took, found := take(sent); found {
			taken[took], ours[took] = true, sent.Str("source") != "owner"
		}
	})
	if err != nil {
		return err
	}
	for i, each := range had {
		var theirs []transcript.Prompt
		for index, message := range each.Messages {
			if !ours[line{conversation{each.Harness, each.Name}, index}] {
				theirs = append(theirs, message)
			}
		}
		had[i].Messages = theirs
	}
	return nil
}
