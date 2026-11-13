package plan

import (
	"cmp"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io/fs"
	"os"
	"slices"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// owedCheck is what a seat owes while its plan's every line is done and no check found that its
// work holds everything its owner said (done_check.OWED), as OwedLine names it.
const owedCheck = "a check of its finished plan against what its owner said"

// A Said is one message or answer of the owner's to a seat: when, their words, and the file of a
// check's workspace that shows them.
type Said struct {
	At           float64
	Words, Shown string
}

// checkOwed is whether the seat, its plan's lines holding box lines and every one done, owes a
// done check (done_check.owed): one is on, the owner wrote it a message or answered a question
// card in one of its conversations, and no check that found no gap read what they have said and
// what the plan holds now (Fingerprint).  Their words are read only where what an answer was kept
// from changed since (asked), and the answer held with what it read, for the command's end to keep
// (KeepAnswers).  A record or config that is there and cannot be read holds the seat and keeps
// nothing; ErrUnread, before anything is read, where Go does not read the owner's words as Python
// does.  Nothing here makes a check.
func checkOwed(name string, lines []string) (bool, error) {
	if !slices.ContainsFunc(lines, boxed) || slices.ContainsFunc(lines, open) {
		return false, nil
	}
	switch on, err := config.DoneCheckOn(); {
	case err != nil:
		return true, nil
	case !on:
		return false, nil
	}
	current, had, err := notify.Listed(name, true)
	if err != nil {
		return false, ErrUnread
	}
	var kept any // none where no check was kept
	switch text, err := os.ReadFile(seatFile("checked", name, "txt")); {
	case err == nil && utf8.Valid(text):
		kept = strings.TrimFunc(string(text), config.Space)
	case !errors.Is(err, fs.ErrNotExist):
		return true, nil
	}
	path := seatFile("owed", name, "json")
	read, err := asked(current, had, lines, kept)
	if err != nil {
		return true, nil
	}
	if owes, ok := answered(path, read); ok {
		return owes, nil
	}
	// read as Listed gave them, so the conversations read are those the digest claimed
	err = notify.Read(current, had, true)
	var owner []Said
	if err == nil {
		_, owner, err = OwnerWords(had)
	}
	switch {
	case errors.Is(err, notify.ErrUnread):
		return false, ErrUnread
	case err != nil:
		return true, nil
	}
	owes := len(owner) > 0 && kept != Fingerprint(owner, lines) // none with no conversation
	keepAnswer(path, read, owes)
	return owes, nil
}

// OwnerWords is each conversation of had, as notify.Conversations gives them, as its harness shows
// it, and the owner's words in them, oldest first (done_check.owner_words): each message they wrote
// the seat, then each answer they gave on its question cards, a message replying on a card counting
// only as those answers (harness.Replies).  Read strictly (harness.strictly):
// Answered reads each conversation whole, so one there that cannot be read is an error, though
// notify.Conversations reads it as holding no message; one that is gone holds none.  ErrUnread
// where Go reads the owner's words in none of that harness's (harness.Reads).
func OwnerWords(had []notify.Conversation) ([][]harness.Turn, []Said, error) {
	var owner []Said
	for _, each := range had {
		for _, message := range each.Messages {
			if !harness.Replies(each.Harness, message.Text) {
				owner = append(owner, Said{message.At, message.Text, message.Text})
			}
		}
	}
	said := make([][]harness.Turn, len(had))
	for i, each := range had {
		if !harness.Reads(each.Harness, false) {
			return nil, nil, notify.ErrUnread
		}
		if each.Name == "" {
			continue // a current one its harness names none of yet, which conversations_of leaves out
		}
		turns, cards, err := harness.Answered(each.Harness, each.Record)
		if err != nil {
			return nil, nil, err
		}
		said[i] = turns
		for _, card := range cards {
			owner = append(owner, Said{card.At, card.Answer, shown(card)})
		}
	}
	slices.SortStableFunc(owner, func(a, b Said) int { return cmp.Compare(a.At, b.At) })
	return said, owner, nil
}

// shown is an answer's file (done_check.card): the question and choices the seat wrote, each
// choice's description after its label where it has one, then the owner's answer.
func shown(card harness.Card) string {
	shown := "The seat asked on its question card: " + card.Question + "\n"
	for _, choice := range card.Choices {
		shown += "- " + choice.Label
		if choice.Description != "" {
			shown += ": " + choice.Description
		}
		shown += "\n"
	}
	return shown + "\nThe owner answered:\n" + card.Answer + "\n"
}

// Fingerprint is what a check of the owner's words against the plan's lines read, for a later one
// to be compared with (done_check.fingerprint): each word of theirs with when it was said, and the
// plan's box lines stripped, a line `ak plan` wrote without the done field a renewed proof changes
// (plan.undone), hashed as Python's json.dumps writes them.
func Fingerprint(owner []Said, lines []string) string {
	said, checked := []any{}, []any{}
	for _, each := range owner {
		said = append(said, []any{run.Float(each.At), each.Words})
	}
	for _, line := range lines {
		if !boxed(line) {
			continue
		}
		line = strings.TrimFunc(line, config.Space)
		if entry, ok := parse(line); ok {
			line = line[:len("- [ ] ")] + entry.bare
		}
		checked = append(checked, line)
	}
	sum := sha256.Sum256([]byte(run.Line([]any{said, checked})))
	return hex.EncodeToString(sum[:])
}
