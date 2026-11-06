package notify

import (
	"io"
	"time"

	"agentkit/internal/run"
)

// Asked is the seat's word at now once notice is the question it asks, since when, and whether that
// word is the question: "" where Go does not read it.
type Asked func(name string, notice *run.Object, now time.Time) (word string, since any, question bool)

// once is what Python's shaped reads of the seat just after recording notice (watch.session_state):
// `needs you` from the question for a seat with no seat file, and the ladder's word for one with.
// "" where that is Python's: a file Go cannot read, one whose `ak wait` the question ends, as only
// Python writes it, a seat its owner closed, and a done, whose card covers the seat's work.
func once(name string, notice *run.Object, asked Asked, now time.Time) (word string, since any, question bool) {
	file, err := readObject(seatFile("seat", name, "json"))
	switch {
	case err != nil:
		return "", nil, false
	case file == nil:
		return "needs you", notice.Get("time"), true
	case file.Get("wait") != nil || file.Truthy("closed_by_owner"):
		return "", nil, false
	}
	if word, since, question = asked(name, notice, now); word == "done" {
		return "", nil, false
	}
	return word, since, question
}

// worded is Python's transition (notify.transition) of the seat's card, under its lock, for the
// question shaped just recorded: its word from since, its episode begun at the command, at stamp,
// and no wait.  A card of another word gives way to an episode of this one, unless the question's
// needs you stands through a turn; a needs you goes to page, the owner present only in a seat whose
// word is the question.
func worded(name string, card, notice *run.Object, word string, since any, present bool, stamp float64, errOut io.Writer) (int, error) {
	from, dated := finite(since)
	if !dated {
		from = stamp
	}
	carded := card.Str("word")
	if word == "needs you" {
		if carded != word {
			asked, _ := notice.Num("time")
			card = episode(card, word, run.Float(max(from, asked)), run.Float(max(from, asked)))
		}
		return page(name, card, notice, present, errOut)
	}
	if carded != word && (carded != "needs you" || word != "working") {
		if carded == "needs you" {
			if err := retire(card); err != nil {
				return 0, err
			}
		}
		card = episode(card, word, run.Float(from), run.Float(from))
	}
	if card.Truthy("sent") {
		return 0, nil
	}
	card.Set("began", run.Float(stamp))
	return 0, writeCard(name, card)
}
